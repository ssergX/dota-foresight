"""Read-only OpenDota study sourcing with fetch receipts and bounded discovery.

API metadata and rank/role estimates do not validate decision quality. This
adapter never requests a parse, refreshes a player, or sends a POST request.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
from urllib.parse import urlencode, urlsplit

import requests

from dota_coach.learning.study import MatchSource, StudyMatch

BASE = "https://api.opendota.com/api"
SCHEMA = "opendota-study-source.v1"


def _positive(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive numeric id")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(text):
    def invalid(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class FetchReceipt:
    source_url: str
    checked_at: str
    content_sha256: str
    body_json: str
    schema_version: str = SCHEMA
    from_cache: bool = False

    def __post_init__(self):
        if any(not isinstance(v, str) for v in (self.source_url, self.checked_at, self.content_sha256, self.body_json, self.schema_version)):
            raise TypeError("receipt fields must be immutable strings")
        if not self.source_url.startswith(BASE + "/") or not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ValueError("receipt requires official source URL and content digest")
        if datetime.fromisoformat(self.checked_at).tzinfo is None or type(self.from_cache) is not bool:
            raise ValueError("receipt requires aware timestamp and cache status")

    @property
    def receipt_id(self):
        return "source:" + hashlib.sha256((self.source_url + "\n" + self.checked_at + "\n" + self.content_sha256).encode()).hexdigest()

    @property
    def data(self):
        # Always a fresh copy; cached source objects cannot be mutated through a DTO.
        return _decode(self.body_json)


@dataclass(frozen=True)
class ReplayProbe:
    status: str
    source_url: str | None
    checked_at: str
    prefix_sha256: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RoleEstimate:
    role: str
    confidence: str
    method: str
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class SourcedStudyExample:
    study: StudyMatch
    account_id: int | None
    player_slot: int
    association_evidence_ref: str
    role_estimate: RoleEstimate
    expertise_class: str
    expertise_basis: str
    rank_tier: int | None
    patch_id: int | None
    replay_probe: ReplayProbe
    receipts: tuple[FetchReceipt, ...]
    teaching_status: str
    difference_codes: tuple[str, ...]


@dataclass(frozen=True)
class StudyDiscovery:
    status: str
    examples: tuple[SourcedStudyExample, ...]
    exclusions: tuple[tuple[int, tuple[str, ...]], ...]
    receipts: tuple[FetchReceipt, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = (
        "Подбор сравнивает наблюдаемый контекст; качество решений игроков не аттестовано.",
        "Роль по линиям и last hits — оценка, а не подтверждённая позиция команды.",
        "Provider patch ID не подтверждает актуальную механику предмета или способности.",)


def _match_validator(match_id):
    def validate(data):
        if not isinstance(data, dict) or type(data.get("match_id")) is not int or data["match_id"] != match_id:
            raise ValueError("OpenDota returned a different or missing match id")
        players = data.get("players")
        if not isinstance(players, list) or not players or any(not isinstance(p, dict) for p in players):
            raise ValueError("match player array missing")
        slots = set()
        for player in players:
            slot = player.get("player_slot")
            if type(slot) is not int or slot not in (*range(5), *range(128, 133)) or slot in slots:
                raise ValueError("invalid/duplicate OpenDota player slot")
            slots.add(slot)
            _positive(player.get("hero_id"), "hero_id")
            if player.get("account_id") is not None:
                _positive(player["account_id"], "account_id")
        if data.get("patch") is not None and (type(data["patch"]) is not int or data["patch"] < 0):
            raise ValueError("invalid provider patch id")
        if data.get("teamfights") is not None and not isinstance(data["teamfights"], list):
            raise ValueError("teamfight source must be an array")
        return data
    return validate


def _list_validator(field):
    def validate(data):
        if not isinstance(data, list):
            raise ValueError("OpenDota list endpoint returned a non-array")
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("invalid source row")
            _positive(row.get(field), field)
        return data
    return validate


def estimate_role(data: dict, player: dict, evidence_ref: str) -> RoleEstimate:
    lane, slot = player.get("lane_role"), player["player_slot"]
    lane = lane if type(lane) is int else None
    limits = ("Фактическая командная позиция и договорённости неизвестны.",
              "Статистика всего матча применяется только для описания учебного контекста.")
    if player.get("is_roaming") is True:
        return RoleEstimate("unknown", "unknown", "roaming_unsupported", (evidence_ref,), limits)
    if lane == 2:
        return RoleEstimate("position_2", "estimated", "opendota_lane_role", (evidence_ref + "/lane_role",), limits)
    if lane in (1, 3):
        group = [p for p in data["players"] if p.get("lane_role") == lane and (p["player_slot"] < 128) == (slot < 128)]
        lh = player.get("last_hits")
        if len(group) == 2 and type(lh) is int and lh >= 0 and all(type(p.get("last_hits")) is int and p["last_hits"] >= 0 for p in group):
            other = next(p for p in group if p["player_slot"] != slot)
            if lh != other["last_hits"]:
                core = lh > other["last_hits"]
                role = "position_1" if lane == 1 and core else "position_5" if lane == 1 else "position_3" if core else "position_4"
                return RoleEstimate(role, "estimated", "lane_pair_last_hits", (evidence_ref + "/lane_role", evidence_ref + "/last_hits"), limits)
    return RoleEstimate("unknown", "unknown", "insufficient_role_context", (evidence_ref,), limits)


def save_study_discovery(discovery: StudyDiscovery, path: str | Path) -> Path:
    """Atomically persist a captured source result; no external request is made."""
    if not isinstance(discovery, StudyDiscovery):
        raise TypeError("typed source discovery required")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".study-discovery-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(asdict(discovery)))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _tuple_strings(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{field} must be an array of strings")
    return tuple(value)


def _loaded_receipt(row):
    if not isinstance(row, dict) or set(row) != {"source_url", "checked_at", "content_sha256", "body_json", "schema_version", "from_cache"}:
        raise ValueError("invalid captured receipt fields")
    receipt = FetchReceipt(**row)
    if receipt.schema_version != SCHEMA or hashlib.sha256(receipt.body_json.encode()).hexdigest() != receipt.content_sha256 or _canonical(receipt.data) != receipt.body_json:
        raise ValueError("captured source digest/canonical schema mismatch")
    route = receipt.source_url.removeprefix(BASE)
    if re.fullmatch(r"/(proMatches|proPlayers|matches/[1-9]\d*|players/[1-9]\d*/matches)(\?hero_id=[1-9]\d*&limit=[1-9]\d*)?", route) is None:
        raise ValueError("captured receipt has an unsupported source route")
    if route.startswith("/matches/"):
        _match_validator(int(route.split("/")[-1]))(receipt.data)
    else:
        _list_validator("account_id" if route == "/proPlayers" else "match_id")(receipt.data)
    return receipt


def _loaded_example(row):
    fields = {"study", "account_id", "player_slot", "association_evidence_ref", "role_estimate", "expertise_class",
              "expertise_basis", "rank_tier", "patch_id", "replay_probe", "receipts", "teaching_status", "difference_codes"}
    if not isinstance(row, dict) or set(row) != fields or not isinstance(row["receipts"], list):
        raise ValueError("invalid captured example fields")
    receipts = tuple(_loaded_receipt(r) for r in row["receipts"])
    study_row = dict(row["study"])
    study_row["sources"] = tuple(MatchSource(**s) for s in study_row["sources"])
    for field in ("expertise_evidence_refs", "episode_refs", "transfer_limitations"):
        study_row[field] = _tuple_strings(study_row[field], field)
    study = StudyMatch(**study_row)
    matches = [r for r in receipts if r.source_url == BASE + f"/matches/{study.match_id}"]
    if len(matches) != 1:
        raise ValueError("one actual match receipt required")
    receipt = matches[0]
    data = receipt.data
    expected_source = MatchSource(study.match_id, f"https://www.opendota.com/matches/{study.match_id}", receipt.checked_at, receipt.content_sha256, "verified")
    if study.sources != (expected_source,) or study.dataset_kind != "real":
        raise ValueError("study source does not bind the captured match")
    association = row["association_evidence_ref"]
    prefix = receipt.receipt_id + "#/players/"
    if not isinstance(association, str) or not association.startswith(prefix) or not association[len(prefix):].isdigit():
        raise ValueError("player association pointer does not bind source receipt")
    ordinal = int(association[len(prefix):])
    if ordinal >= len(data["players"]):
        raise ValueError("player association points outside source roster")
    player = data["players"][ordinal]
    if type(row["player_slot"]) is not int or row["player_slot"] != player["player_slot"] or row["account_id"] != player.get("account_id") or study.hero_id != player["hero_id"]:
        raise ValueError("captured match/hero/account/slot association mismatch")
    if row["account_id"] is not None:
        _positive(row["account_id"], "captured account_id")
    role_row = dict(row["role_estimate"])
    role_row["evidence_refs"] = _tuple_strings(role_row["evidence_refs"], "role evidence")
    role_row["limitations"] = _tuple_strings(role_row["limitations"], "role limitations")
    role = RoleEstimate(**role_row)
    if role != estimate_role(data, player, association) or study.role != role.role:
        raise ValueError("captured role inference mismatch")
    patch_id = data.get("patch")
    if row["patch_id"] != patch_id or study.patch != (f"opendota_patch_id:{patch_id}" if patch_id is not None else "unknown"):
        raise ValueError("captured provider patch mismatch")
    rank = player.get("rank_tier")
    rank = rank if type(rank) is int and 10 <= rank <= 85 else None
    if row["rank_tier"] != rank:
        raise ValueError("captured rank tier mismatch")
    pro_refs = []
    for pro in receipts:
        if pro.source_url == BASE + "/proPlayers":
            pro_refs.extend(pro.receipt_id + f"#/{i}" for i, p in enumerate(pro.data) if row["account_id"] is not None and p["account_id"] == row["account_id"])
    professional = bool(pro_refs)
    expertise_class = "registered_pro" if professional else "high_rank" if rank is not None and rank >= 80 else "unknown"
    expertise_basis = "opendota_registered_pro_account" if professional else "match_rank_tier_proxy_not_numeric_mmr" if expertise_class == "high_rank" else "not_sourced"
    if row["expertise_class"] != expertise_class or row["expertise_basis"] != expertise_basis or study.expertise_status != ("pro" if professional else "unknown") or study.expertise_evidence_refs != ((pro_refs[0],) if professional else ()):
        raise ValueError("captured expertise not supported by source registry/rank")
    for episode in study.episode_refs:
        if episode.startswith(receipt.receipt_id + "#/teamfights/"):
            index = episode.split("/")[-1]
            if not index.isdigit() or int(index) >= len(data.get("teamfights") or []):
                raise ValueError("captured teamfight pointer is missing")
        elif episode.startswith(association + "/purchase_log/"):
            index = episode.split("/")[-1]
            if not index.isdigit() or int(index) >= len(player.get("purchase_log") or []):
                raise ValueError("captured purchase pointer is missing")
        else:
            raise ValueError("captured teaching episode does not bind source")
    probe_row = dict(row["replay_probe"])
    probe_row["reason_codes"] = _tuple_strings(probe_row["reason_codes"], "probe reasons")
    probe = ReplayProbe(**probe_row)
    if probe.status not in ("available", "unavailable", "unknown") or study.replay_availability != probe.status or probe.source_url != data.get("replay_url"):
        raise ValueError("captured replay probe does not match source")
    if datetime.fromisoformat(probe.checked_at).tzinfo is None:
        raise ValueError("captured probe timestamp needs timezone")
    if probe.status == "available" and (not isinstance(probe.prefix_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", probe.prefix_sha256) or "prefix_only_full_download_not_verified" not in probe.reason_codes):
        raise ValueError("captured availability lacks binary prefix receipt")
    expected_teaching = "source_backed_comparison" if study.episode_refs and probe.status == "available" else "metadata_only"
    if row["teaching_status"] != expected_teaching or bool(study.episode_refs) != bool(study.learning_task):
        raise ValueError("captured teaching availability mismatch")
    # Existing receipt describes what was checked then. Never claim a new GET or
    # current availability based on loading a file; no decision grant is issued.
    probe = ReplayProbe(probe.status, probe.source_url, probe.checked_at, probe.prefix_sha256,
                        tuple(dict.fromkeys(probe.reason_codes + ("captured_probe_not_rechecked_current_availability_unknown",))))
    study = StudyMatch(**(asdict(study) | {"sources": study.sources,
        "expertise_evidence_refs": study.expertise_evidence_refs, "episode_refs": study.episode_refs,
        "transfer_limitations": tuple(dict.fromkeys(study.transfer_limitations + ("Загружен сохранённый source receipt; текущая доступность реплея повторно не проверялась.",)))}))
    return SourcedStudyExample(study, row["account_id"], row["player_slot"], association, role,
                              expertise_class, expertise_basis, rank, patch_id, probe, receipts,
                              expected_teaching, _tuple_strings(row["difference_codes"], "difference codes"))


def load_study_discovery(path: str | Path) -> StudyDiscovery:
    """Reconstruct and cross-check a captured artifact, without network or grants.

    A coherent local receipt is not authenticated independent provenance. This
    loader verifies integrity/bindings, not server authenticity or decision skill.
    """
    row = _decode(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(row, dict) or set(row) != {"status", "examples", "exclusions", "receipts", "reason_codes", "limitations"}:
        raise ValueError("invalid captured discovery fields")
    if row["status"] not in ("sourced_examples", "unavailable") or not all(isinstance(row[k], list) for k in ("examples", "exclusions", "receipts")):
        raise ValueError("invalid captured discovery status/arrays")
    examples = tuple(_loaded_example(e) for e in row["examples"])
    if len({e.study.match_id for e in examples}) != len(examples) or (row["status"] == "sourced_examples") != bool(examples):
        raise ValueError("duplicate examples or captured discovery status mismatch")
    exclusions = []
    for value in row["exclusions"]:
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("invalid captured source exclusion")
        exclusions.append((_positive(value[0], "excluded match_id"), _tuple_strings(value[1], "exclusion reasons")))
    return StudyDiscovery(row["status"], examples, tuple(exclusions), tuple(_loaded_receipt(r) for r in row["receipts"]),
                          _tuple_strings(row["reason_codes"], "discovery reasons"),
                          tuple(dict.fromkeys(_tuple_strings(row["limitations"], "discovery limitations") +
                                ("Сохранённые source receipts проверены на целостность; сетевой запрос и независимая аттестация не повторялись.",))))


class OpenDotaStudySource:
    def __init__(self, cache_dir: Path = Path("cache/study-sources"), *, session=None,
                 ttl_seconds: float = 3600, min_interval: float = 1.1,
                 now: Callable[[], datetime] | None = None):
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or not math.isfinite(min_interval) or min_interval < 0:
            raise ValueError("finite positive cache TTL/nonnegative rate interval required")
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.ttl_seconds = ttl_seconds
        self.min_interval = min_interval
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._last_request = 0.

    def _stamp(self):
        stamp = self.now()
        if stamp.tzinfo is None:
            raise ValueError("timezone-aware source clock required")
        return stamp.astimezone(timezone.utc).isoformat()

    def _throttle(self):
        remaining = self.min_interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def _fetch(self, endpoint, validate, *, params=None):
        # Call sites provide only these fixed GET routes; arbitrary URLs are not accepted.
        if not re.fullmatch(r"/(proMatches|proPlayers|matches/[1-9]\d*|players/[1-9]\d*/matches)", endpoint):
            raise ValueError("unsupported read-only source endpoint")
        url = BASE + endpoint + ("?" + urlencode(sorted(params.items())) if params else "")
        path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        try:
            cached = _decode(path.read_text(encoding="utf-8"))
            if set(cached) != {"source_url", "checked_at", "content_sha256", "body_json", "schema_version", "from_cache"}:
                raise ValueError("invalid cache envelope")
            receipt = FetchReceipt(**cached)
            age = (self.now() - datetime.fromisoformat(receipt.checked_at)).total_seconds()
            if receipt.schema_version != SCHEMA or receipt.source_url != url or not 0 <= age < self.ttl_seconds:
                raise ValueError("expired or mismatched source cache")
            if hashlib.sha256(receipt.body_json.encode("utf-8")).hexdigest() != receipt.content_sha256:
                raise ValueError("source cache digest mismatch")
            validate(receipt.data)
            return FetchReceipt(receipt.source_url, receipt.checked_at, receipt.content_sha256,
                                receipt.body_json, from_cache=True)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self._throttle()
        response = self.session.get(url, timeout=30, allow_redirects=False)
        try:
            if response.status_code != 200:
                raise ValueError(f"OpenDota GET failed: HTTP {response.status_code}")
            if len(response.content) > 12_000_000:
                raise ValueError("OpenDota JSON exceeds source size limit")
            data = validate(_decode(response.content.decode("utf-8")))
            body = _canonical(data)
        finally:
            response.close()
        receipt = FetchReceipt(url, self._stamp(), hashlib.sha256(body.encode()).hexdigest(), body)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".source-", suffix=".json", dir=self.cache_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(_canonical(asdict(receipt)))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return receipt

    def probe_replay(self, url: str | None, match_id: int) -> ReplayProbe:
        stamp = self._stamp()
        if not isinstance(url, str):
            return ReplayProbe("unknown", None, stamp, None, ("replay_url_missing",))
        try:
            parsed = urlsplit(url)
            allowed = parsed.scheme in ("http", "https") and re.fullmatch(r"replay\d+\.valve\.net", parsed.hostname or "") and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.port in (None, 80, 443) and re.fullmatch(rf"/570/{match_id}_[1-9]\d*\.dem\.(bz2|zst)", parsed.path)
        except ValueError:
            allowed = False
        if not allowed:
            return ReplayProbe("unknown", None, stamp, None, ("replay_url_not_allowed_or_match_mismatch",))
        self._throttle()
        try:
            response = self.session.get(url, headers={"Range": "bytes=0-7"}, stream=True,
                                        timeout=20, allow_redirects=False)
            try:
                if response.status_code in (404, 410):
                    return ReplayProbe("unavailable", url, stamp, None, ("replay_source_not_found",))
                if response.status_code not in (200, 206):
                    return ReplayProbe("unknown", url, stamp, None, (f"replay_probe_http_{response.status_code}",))
                prefix = next(response.iter_content(chunk_size=8), b"")[:8]
                if not prefix.startswith((b"BZh", b"\x28\xb5\x2f\xfd", b"PBDEMS2")):
                    return ReplayProbe("unknown", url, stamp, None, ("replay_probe_not_binary_replay",))
                return ReplayProbe("available", url, stamp, hashlib.sha256(prefix).hexdigest(),
                                   ("prefix_only_full_download_not_verified",))
            finally:
                response.close()
        except requests.RequestException:
            return ReplayProbe("unknown", url, stamp, None, ("replay_probe_network_unavailable",))

    def fetch_match_source(self, match_id: int, hero_id: int, *, account_id: int | None = None,
                           probe_replay: bool = True, check_pro: bool = True) -> SourcedStudyExample:
        _positive(match_id, "match_id")
        _positive(hero_id, "hero_id")
        if account_id is not None:
            _positive(account_id, "account_id")
        receipt = self._fetch(f"/matches/{match_id}", _match_validator(match_id))
        data = receipt.data
        players = [(i, p) for i, p in enumerate(data["players"]) if p["hero_id"] == hero_id and (account_id is None or p.get("account_id") == account_id)]
        if len(players) != 1:
            raise ValueError("requested hero/account association not uniquely present")
        ordinal, player = players[0]
        association = receipt.receipt_id + f"#/players/{ordinal}"
        actor = player.get("account_id")
        receipts = [receipt]
        expertise, basis, refs = "unknown", "not_sourced", ()
        if check_pro and actor is not None:
            pros = self._fetch("/proPlayers", _list_validator("account_id"))
            receipts.append(pros)
            entries = [i for i, p in enumerate(pros.data) if p["account_id"] == actor]
            if entries:
                expertise, basis = "pro", "opendota_registered_pro_account"
                refs = (pros.receipt_id + f"#/{entries[0]}",)
        rank = player.get("rank_tier")
        rank = rank if type(rank) is int and 10 <= rank <= 85 else None
        expertise_class = "registered_pro" if expertise == "pro" else "high_rank" if rank is not None and rank >= 80 else "unknown"
        if expertise_class == "high_rank":
            basis = "match_rank_tier_proxy_not_numeric_mmr"
            # Never turn a medal tier into a sourced numeric high-MMR claim.
            refs = (association + "/rank_tier",)
        role = estimate_role(data, player, association)
        patch_id = data.get("patch")
        patch = f"opendota_patch_id:{patch_id}" if patch_id is not None else "unknown"
        replay = self.probe_replay(data.get("replay_url"), match_id) if probe_replay else ReplayProbe("unknown", data.get("replay_url"), self._stamp(), None, ("replay_not_probed",))
        episodes = []
        for i, tf in enumerate(data.get("teamfights") or []):
            if isinstance(tf, dict) and type(tf.get("start")) in (int, float) and math.isfinite(tf["start"]) and tf["start"] >= 0:
                episodes.append((tf["start"], receipt.receipt_id + f"#/teamfights/{i}"))
        episodes.sort()
        episode_refs = tuple(ref for _, ref in episodes[:3])
        if episode_refs:
            task = (f"Матч {match_id}, герой {hero_id}: останови реплей перед первым отмеченным эпизодом на {episodes[0][0]:g} с. "
                    "Запиши доступные игроку сведения и альтернативы, затем сравни выбранное действие. Итог драки рассматривай отдельно.")
        else:
            purchase = player.get("purchase_log") or []
            indices = [i for i, e in enumerate(purchase) if isinstance(e, dict) and isinstance(e.get("key"), str)]
            episode_refs = tuple(association + f"/purchase_log/{i}" for i in indices[:3])
            task = "Сравни первые отмеченные покупки, доступные альтернативы и различия контекста; не считай популярную покупку оптимальной." if episode_refs else ""
        limitations = ("Роль estimated по линии/last hits; фактическая позиция команды не подтверждена.",
                       "Патч обозначен идентификатором OpenDota, механика отдельно не проверена.",
                       "Экспертный статус источника не доказывает правильность каждого решения.",
                       "Rank tier описывает медаль источника и не является числовым MMR.",
                       "Teamfight aggregates задают места просмотра, а не доказанные границы выбора.")
        study = StudyMatch(match_id, hero_id, role.role, patch,
                           (MatchSource(match_id, f"https://www.opendota.com/matches/{match_id}", receipt.checked_at, receipt.content_sha256, "verified"),),
                           replay.status, expertise, refs if expertise == "pro" else (), episode_refs,
                           task, limitations, "real")
        teaching = "source_backed_comparison" if episode_refs and replay.status == "available" else "metadata_only"
        return SourcedStudyExample(study, actor, player["player_slot"], association, role,
                                   expertise_class, basis, rank, patch_id, replay, tuple(receipts),
                                   teaching, ("goals_opponents_and_team_plan_not_matched",))

    def discover(self, hero_id: int, *, account_id: int | None = None, role: str | None = None,
                 patch: str | None = None, limit: int = 3, max_fetches: int = 8,
                 probe_replay: bool = True, exclude_match_ids: tuple[int, ...] = ()) -> StudyDiscovery:
        _positive(hero_id, "hero_id")
        if type(limit) is not int or limit < 1 or type(max_fetches) is not int or not 1 <= max_fetches <= 30:
            raise ValueError("bounded positive discovery limits required")
        if not isinstance(exclude_match_ids, tuple) or len(set(exclude_match_ids)) != len(exclude_match_ids):
            raise ValueError("immutable unique excluded match IDs required")
        for excluded in exclude_match_ids:
            _positive(excluded, "excluded match id")
        if account_id is not None:
            _positive(account_id, "account_id")
            listing = self._fetch(f"/players/{account_id}/matches", _list_validator("match_id"),
                                  params={"hero_id": hero_id, "limit": max_fetches})
        else:
            listing = self._fetch("/proMatches", _list_validator("match_id"))
        examples, exclusions = [], []
        seen = set()
        for row in listing.data:
            match_id = row["match_id"]
            if match_id in seen:
                continue
            if match_id in exclude_match_ids:
                exclusions.append((match_id, ("target_or_excluded_match",)))
                continue
            if len(seen) >= max_fetches or len(examples) >= limit:
                break
            seen.add(match_id)
            try:
                example = self.fetch_match_source(match_id, hero_id, account_id=account_id, probe_replay=probe_replay)
                reasons = []
                if patch is not None and example.study.patch != patch:
                    reasons.append("patch_mismatch")
                if role is not None and example.role_estimate.role != role:
                    reasons.append("role_mismatch_or_unknown")
                if example.expertise_class == "unknown":
                    reasons.append("expertise_not_sourced")
                if not example.study.episode_refs:
                    reasons.append("teaching_episodes_unavailable")
                if reasons:
                    exclusions.append((match_id, tuple(reasons)))
                else:
                    examples.append(example)
            except (ValueError, requests.RequestException) as exc:
                # No fallback fabricated match, no hidden parse/refresh POST.
                exclusions.append((match_id, ("source_or_association_unavailable", type(exc).__name__)))
        return StudyDiscovery("sourced_examples" if examples else "unavailable", tuple(examples),
                              tuple(exclusions), (listing,),
                              () if examples else ("no_source_backed_suitable_examples_in_bounded_search",))
