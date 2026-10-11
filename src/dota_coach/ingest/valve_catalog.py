"""Read-only Valve datafeed snapshots with explicit, unassigned patch scope.

Valve's live catalog is useful source material, but its retrieval date does not
identify the mechanics of a historical match. No response can grant validation.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests

from dota_coach.evidence.contracts import content_hash

BASE = "https://www.dota2.com/datafeed/"
PARSER_VERSION = "valve-catalog.v1"
MAX_RESPONSE_BYTES = 12_000_000


def primary_url(value: str) -> bool:
    parsed = urlparse(value)
    return (parsed.scheme == "https" and parsed.hostname in ("www.dota2.com", "dota2.com")
            and not parsed.username and parsed.port in (None, 443))


def _text(value) -> str:
    if not isinstance(value, str):
        raise ValueError("catalog text must be a string")
    # Datafeed uses markup and unexpanded %special_value% variables. Strip markup
    # rather than executing it; keep variables until the applicable mechanic is reviewed.
    value = re.sub(r"<(?:br|/h[1-6])\s*/?>", " ", value, flags=re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def _numbers(values) -> tuple[float, ...]:
    if not isinstance(values, list) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("finite numeric catalog array required")
    return tuple(values)


def _sha(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA-256 required")


@dataclass(frozen=True)
class FetchReceipt:
    source_url: str
    fetched_at: str
    payload_sha256: str
    payload_bytes: int
    status_code: int = 200
    retrieval_method: str = "network_read"
    headers: tuple[tuple[str, str], ...] = ()
    parser_version: str = PARSER_VERSION

    def __post_init__(self):
        if not primary_url(self.source_url) or not urlparse(self.source_url).path.startswith("/datafeed/"):
            raise ValueError("catalog receipt requires a Valve datafeed HTTPS URL")
        timestamp = datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("receipt time requires timezone")
        _sha(self.payload_sha256)
        if type(self.payload_bytes) is not int or not 0 < self.payload_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("invalid receipt byte count")
        if self.status_code != 200 or self.retrieval_method not in ("network_read", "manual_import"):
            raise ValueError("receipt requires successful read or declared import")
        if not isinstance(self.headers, tuple) or any(
                not isinstance(pair, tuple) or len(pair) != 2 or pair[0] not in ("etag", "last-modified", "date")
                or not isinstance(pair[1], str) for pair in self.headers):
            raise ValueError("only immutable non-sensitive response headers are retained")

    @property
    def receipt_hash(self):
        return content_hash(self)


@dataclass(frozen=True)
class SpecialValue:
    name: str
    values: tuple[float, ...]
    heading: str = ""
    is_percentage: bool = False
    required_facet: str = ""
    shard_values: tuple[float, ...] = ()
    scepter_values: tuple[float, ...] = ()

    def __post_init__(self):
        if not self.name or type(self.is_percentage) is not bool:
            raise ValueError("named special value required")
        for values in (self.values, self.shard_values, self.scepter_values):
            if not isinstance(values, tuple):
                raise ValueError("immutable special values required")
            _numbers(list(values))


@dataclass(frozen=True)
class MechanicDescriptor:
    ability_id: int
    internal_name: str
    label: str
    source_url: str
    receipt_hash: str
    description: str = ""
    notes: tuple[str, ...] = ()
    item_cost: int | None = None
    cooldowns: tuple[float, ...] = ()
    mana_costs: tuple[float, ...] = ()
    cast_ranges: tuple[float, ...] = ()
    special_values: tuple[SpecialValue, ...] = ()
    detail_status: str = "list_entry_only"

    def __post_init__(self):
        if type(self.ability_id) is not int or self.ability_id <= 0 or not self.internal_name or not self.label:
            raise ValueError("catalog ability identity required")
        if not primary_url(self.source_url):
            raise ValueError("primary Valve source required")
        _sha(self.receipt_hash)
        if self.item_cost is not None and (type(self.item_cost) is not int or self.item_cost < 0):
            raise ValueError("nonnegative cost or unknown required")
        if self.detail_status not in ("list_entry_only", "descriptor_available"):
            raise ValueError("invalid catalog detail status")
        for values in (self.cooldowns, self.mana_costs, self.cast_ranges):
            if not isinstance(values, tuple):
                raise ValueError("immutable descriptor arrays required")
            _numbers(list(values))
        if not isinstance(self.notes, tuple) or any(not isinstance(n, str) for n in self.notes):
            raise ValueError("immutable notes required")
        if not isinstance(self.special_values, tuple) or any(not isinstance(v, SpecialValue) for v in self.special_values):
            raise ValueError("typed special values required")
        if len({v.name for v in self.special_values}) != len(self.special_values):
            raise ValueError("duplicate special value")

    @property
    def descriptor_hash(self):
        return content_hash(self)


@dataclass(frozen=True)
class HeroDescriptor:
    hero_id: int
    internal_name: str
    label: str
    source_url: str
    receipt_hash: str
    primary_attribute: int | None = None
    abilities: tuple[MechanicDescriptor, ...] = ()

    def __post_init__(self):
        if type(self.hero_id) is not int or self.hero_id <= 0 or not self.internal_name or not self.label:
            raise ValueError("hero identity required")
        if not primary_url(self.source_url):
            raise ValueError("primary Valve source required")
        _sha(self.receipt_hash)
        if not isinstance(self.abilities, tuple) or any(not isinstance(a, MechanicDescriptor) for a in self.abilities):
            raise ValueError("immutable hero abilities required")
        if len({a.ability_id for a in self.abilities}) != len(self.abilities):
            raise ValueError("duplicate hero ability")


@dataclass(frozen=True)
class ValveCatalogSnapshot:
    receipts: tuple[FetchReceipt, ...]
    items: tuple[MechanicDescriptor, ...]
    heroes: tuple[HeroDescriptor, ...]
    language: str = "english"
    schema_version: str = "foresight.valve-catalog.v1"
    parser_version: str = PARSER_VERSION
    patch: None = None
    patch_applicability: str = "unassigned_live_feed"
    validation_status: str = "unverified"

    def __post_init__(self):
        if self.patch is not None or self.patch_applicability != "unassigned_live_feed" or self.validation_status != "unverified":
            raise ValueError("live Valve feed cannot assert historical patch compatibility or validation")
        if self.schema_version != "foresight.valve-catalog.v1" or self.parser_version != PARSER_VERSION:
            raise ValueError("unsupported catalog schema/parser")
        for values, cls in ((self.receipts, FetchReceipt), (self.items, MechanicDescriptor), (self.heroes, HeroDescriptor)):
            if not isinstance(values, tuple) or any(not isinstance(v, cls) for v in values):
                raise ValueError("typed immutable catalog snapshot required")
        if not self.receipts or not self.items or not self.heroes:
            raise ValueError("catalog requires receipts, items and heroes")
        if len({i.internal_name for i in self.items}) != len(self.items) or len({i.ability_id for i in self.items}) != len(self.items):
            raise ValueError("duplicate catalog item identity")
        if len({h.hero_id for h in self.heroes}) != len(self.heroes):
            raise ValueError("duplicate catalog hero identity")
        known = {receipt.receipt_hash for receipt in self.receipts}
        descriptors = list(self.items) + [a for hero in self.heroes for a in hero.abilities]
        if any(d.receipt_hash not in known for d in descriptors) or any(h.receipt_hash not in known for h in self.heroes):
            raise ValueError("descriptor receipt absent from snapshot")
        urls = {receipt.receipt_hash: receipt.source_url for receipt in self.receipts}
        if any(d.source_url != urls[d.receipt_hash] for d in descriptors) or any(
                h.source_url != urls[h.receipt_hash] for h in self.heroes):
            raise ValueError("descriptor source URL disagrees with its receipt")

    @property
    def snapshot_id(self):
        return content_hash(self)

    def item(self, name_or_id: str | int) -> MechanicDescriptor | None:
        name = "item_" + name_or_id if isinstance(name_or_id, str) and not name_or_id.startswith("item_") else name_or_id
        return next((item for item in self.items if item.internal_name == name or item.ability_id == name_or_id), None)


def _decode(body: bytes) -> dict:
    def unique(pairs):
        row = {}
        for key, value in pairs:
            if key in row:
                raise ValueError("duplicate catalog JSON key")
            row[key] = value
        return row
    data = json.loads(body, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite catalog JSON")))
    if not isinstance(data, dict):
        raise ValueError("catalog object required")
    return data


def _rows(body, key):
    result = _decode(body).get("result", {})
    # Valve lists currently omit status; detailed endpoints include status=1.
    # An explicit error status or missing expected data is always rejected.
    if ("status" in result and result["status"] != 1) or not isinstance(result.get("data"), dict):
        raise ValueError("Valve datafeed did not return successful data")
    rows = result["data"].get(key)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"Valve datafeed missing {key}")
    if any(type(row.get("id")) is not int or row["id"] <= 0 or not isinstance(row.get("name"), str)
           or not row["name"].strip() for row in rows):
        raise ValueError("catalog row requires a positive identity and internal name")
    if len({row["id"] for row in rows}) != len(rows) or len({row["name"] for row in rows}) != len(rows):
        raise ValueError("duplicate catalog row identity")
    return rows


def descriptor_from_row(row: dict, receipt: FetchReceipt, *, detailed: bool) -> MechanicDescriptor:
    specials = tuple(SpecialValue(v["name"], _numbers(v.get("values_float", [])),
                                  _text(v.get("heading_loc", "")), v.get("is_percentage", False),
                                  v.get("required_facet", ""), _numbers(v.get("values_shard", [])),
                                  _numbers(v.get("values_scepter", []))) for v in row.get("special_values", []))
    return MechanicDescriptor(row["id"], row["name"], _text(row.get("name_loc") or row["name"]),
                              receipt.source_url, receipt.receipt_hash, _text(row.get("desc_loc", "")),
                              tuple(_text(n) for n in row.get("notes_loc", [])), row.get("item_cost") if detailed else None,
                              _numbers(row.get("cooldowns", [])), _numbers(row.get("mana_costs", [])),
                              _numbers(row.get("cast_ranges", [])), specials,
                              "descriptor_available" if detailed else "list_entry_only")


def _store_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("immutable catalog artifact collision or tampering")


def fetch_valve_catalog(cache_dir: str | Path, *, item_ids: tuple[int, ...] = (),
                        hero_ids: tuple[int, ...] = (), language="english", session=None) -> ValveCatalogSnapshot:
    """GET lists and requested details; retain exact bytes and successful receipts."""
    if not isinstance(language, str) or re.fullmatch("[a-z_]+", language) is None:
        raise ValueError("invalid Valve language")
    if not isinstance(item_ids, tuple) or not isinstance(hero_ids, tuple) or len(item_ids) > 64 or len(hero_ids) > 16:
        raise ValueError("bounded immutable detail identifiers required")
    if any(type(i) is not int or i <= 0 for i in item_ids + hero_ids) or len(set(item_ids)) != len(item_ids) or len(set(hero_ids)) != len(hero_ids):
        raise ValueError("unique positive detail identifiers required")
    cache = Path(cache_dir)
    own_session = session is None
    client = session or requests.Session()
    receipts = []
    def fetch(endpoint, **params):
        url = BASE + endpoint + "?" + urlencode({"language": language, **params})
        response = client.get(url, timeout=(10, 30), allow_redirects=False, stream=True)
        try:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Valve catalog requires a successful 200 response; redirects are not followed")
            chunks, count = [], 0
            for chunk in response.iter_content(64 * 1024):
                count += len(chunk)
                if count > MAX_RESPONSE_BYTES:
                    raise ValueError("oversized Valve catalog response")
                chunks.append(chunk)
            body = b"".join(chunks)
            if not body:
                raise ValueError("empty Valve catalog response")
        finally:
            response.close()
        receipt = FetchReceipt(url, datetime.now(timezone.utc).isoformat(), hashlib.sha256(body).hexdigest(),
                               len(body), headers=tuple((key, response.headers[key]) for key in (
                                   "etag", "last-modified", "date") if key in response.headers))
        _store_immutable(cache / "raw" / f"{receipt.payload_sha256}.json", body)
        _store_immutable(cache / "receipts" / f"{receipt.receipt_hash}.json",
                         json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True).encode("utf-8"))
        receipts.append(receipt)
        return body, receipt
    try:
        body, receipt = fetch("itemlist")
        items = {d.ability_id: d for d in (descriptor_from_row(r, receipt, detailed=False)
                                         for r in _rows(body, "itemabilities"))}
        body, receipt = fetch("herolist")
        heroes = {r["id"]: HeroDescriptor(r["id"], r["name"], _text(r.get("name_loc") or r["name"]),
                                        receipt.source_url, receipt.receipt_hash, r.get("primary_attr"))
                  for r in _rows(body, "heroes")}
        if not set(item_ids) <= set(items) or not set(hero_ids) <= set(heroes):
            raise ValueError("requested detail identity absent from Valve list")
        for identity in item_ids:
            body, receipt = fetch("itemdata", item_id=identity)
            rows = _rows(body, "items")
            if len(rows) != 1 or rows[0].get("id") != identity or rows[0].get("name") != items[identity].internal_name:
                raise ValueError("Valve item detail identity mismatch")
            items[identity] = descriptor_from_row(rows[0], receipt, detailed=True)
        for identity in hero_ids:
            body, receipt = fetch("herodata", hero_id=identity)
            rows = _rows(body, "heroes")
            if len(rows) != 1 or rows[0].get("id") != identity or rows[0].get("name") != heroes[identity].internal_name:
                raise ValueError("Valve hero detail identity mismatch")
            row = rows[0]
            heroes[identity] = HeroDescriptor(identity, row["name"], _text(row.get("name_loc") or row["name"]),
                                              receipt.source_url, receipt.receipt_hash, row.get("primary_attr"),
                                              tuple(descriptor_from_row(a, receipt, detailed=True)
                                                    for a in row.get("abilities", [])))
        snapshot = ValveCatalogSnapshot(tuple(receipts), tuple(items[i] for i in sorted(items)),
                                         tuple(heroes[i] for i in sorted(heroes)), language)
        save_valve_snapshot(snapshot, cache / "snapshots" / snapshot.snapshot_id / "catalog.json")
        return snapshot
    finally:
        if own_session:
            client.close()


def save_valve_snapshot(snapshot: ValveCatalogSnapshot, path: str | Path) -> Path:
    target = Path(path)
    data = asdict(snapshot) | {"snapshot_id": snapshot.snapshot_id}
    _store_immutable(target, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
    return target


def load_valve_snapshot(path: str | Path, *, raw_dir: str | Path | None = None) -> ValveCatalogSnapshot:
    data = _decode(Path(path).read_bytes())
    expected_hash = data.pop("snapshot_id")
    data["receipts"] = tuple(FetchReceipt(**(r | {"headers": tuple(tuple(pair) for pair in r["headers"])}))
                              for r in data["receipts"])
    def descriptor(row):
        row = dict(row)
        for field in ("notes", "cooldowns", "mana_costs", "cast_ranges"):
            row[field] = tuple(row[field])
        row["special_values"] = tuple(SpecialValue(**(v | {field: tuple(v[field]) for field in (
            "values", "shard_values", "scepter_values")})) for v in row["special_values"])
        return MechanicDescriptor(**row)
    data["items"] = tuple(descriptor(row) for row in data["items"])
    data["heroes"] = tuple(HeroDescriptor(**(r | {"abilities": tuple(descriptor(a) for a in r["abilities"])}))
                            for r in data["heroes"])
    snapshot = ValveCatalogSnapshot(**data)
    if snapshot.snapshot_id != expected_hash:
        raise ValueError("catalog snapshot hash mismatch")
    if raw_dir is not None:
        for receipt in snapshot.receipts:
            body = (Path(raw_dir) / f"{receipt.payload_sha256}.json").read_bytes()
            if len(body) != receipt.payload_bytes or hashlib.sha256(body).hexdigest() != receipt.payload_sha256:
                raise ValueError("catalog raw receipt hash or byte count mismatch")
    return snapshot
