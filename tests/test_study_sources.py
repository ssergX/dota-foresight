"""Synthetic HTTP/schema checks; live sourcing has its own persisted receipt."""
from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from dota_coach.ingest.study_sources import (OpenDotaStudySource, BASE, estimate_role,
    load_study_discovery, save_study_discovery)


def match(mid=1001):
    return {"match_id": mid, "patch": 60,
            "replay_url": f"http://replay273.valve.net/570/{mid}_123.dem.bz2",
            "players": [
                {"account_id": 111, "player_slot": 0, "hero_id": 145, "lane_role": 1, "last_hits": 300, "rank_tier": 80},
                {"account_id": 222, "player_slot": 1, "hero_id": 112, "lane_role": 1, "last_hits": 20}],
            "teamfights": [{"start": 413}, {"start": 900}]}


class Response:
    def __init__(self, data=None, *, status=200, binary=None):
        self.content = binary if binary is not None else json.dumps(data).encode()
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size=8):
        yield self.content[:chunk_size]


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return value


def source(tmp_path, *, raw=None, pros=None, replay_status=206, replay_binary=b"BZh9abc", clock=None):
    data = raw or match()
    routes = {
        BASE + "/matches/1001": Response(data),
        BASE + "/proPlayers": Response([{"account_id": 111}] if pros is None else pros),
        data["replay_url"]: Response(status=replay_status, binary=replay_binary),
        BASE + "/proMatches": Response([{"match_id": 1001}]),
    }
    session = Session(routes)
    s = OpenDotaStudySource(tmp_path, session=session, min_interval=0,
                           now=clock or (lambda: datetime(2026, 10, 5, tzinfo=timezone.utc)))
    return s, session


def test_checked_real_source_association_pro_identity_and_role_estimate(tmp_path):
    s, session = source(tmp_path)
    result = s.fetch_match_source(1001, 145, account_id=111)
    assert result.study.match_id == 1001 and result.study.sources[0].status == "verified"
    assert result.expertise_class == "registered_pro" and result.study.expertise_status == "pro"
    assert result.account_id == 111 and result.role_estimate.role == "position_1"
    assert result.role_estimate.confidence == "estimated"
    assert result.study.patch == "opendota_patch_id:60" and result.patch_id == 60
    assert result.study.replay_availability == "available" and result.study.episode_refs
    assert "413" in result.study.learning_task and "Итог драки" in result.study.learning_task
    assert all(kwargs["allow_redirects"] is False for _, kwargs in session.calls)
    assert all(r.closed for r in session.routes.values() if r is not session.routes[BASE + "/proMatches"])


def test_source_receipt_is_immutable_and_returned_data_cannot_mutate_cache(tmp_path):
    s, _ = source(tmp_path)
    result = s.fetch_match_source(1001, 145, probe_replay=False)
    receipt = result.receipts[0]
    data = receipt.data
    data["players"][0]["hero_id"] = 1
    assert receipt.data["players"][0]["hero_id"] == 145
    assert receipt.content_sha256 == result.study.sources[0].content_sha256


def test_cache_reuses_checked_at_with_no_network_and_expires(tmp_path):
    clock = [datetime(2026, 10, 5, tzinfo=timezone.utc)]
    s, session = source(tmp_path, clock=lambda: clock[0])
    first = s.fetch_match_source(1001, 145, probe_replay=False)
    calls = len(session.calls)
    second = s.fetch_match_source(1001, 145, probe_replay=False)
    assert len(session.calls) == calls and all(r.from_cache for r in second.receipts)
    assert first.receipts[0].checked_at == second.receipts[0].checked_at
    clock[0] += timedelta(hours=2)
    third = s.fetch_match_source(1001, 145, probe_replay=False)
    assert len(session.calls) == calls + 2 and third.receipts[0].checked_at != first.receipts[0].checked_at


def test_corrupted_cache_refetched_atomically(tmp_path):
    s, session = source(tmp_path)
    s.fetch_match_source(1001, 145, probe_replay=False)
    for p in tmp_path.glob("*.json"):
        payload = json.loads(p.read_text())
        payload["content_sha256"] = "f" * 64
        p.write_text(json.dumps(payload))
    previous = len(session.calls)
    s.fetch_match_source(1001, 145, probe_replay=False)
    assert len(session.calls) == previous + 2
    assert not list(tmp_path.glob(".source-*"))


@pytest.mark.parametrize("raw", [
    {**match(), "match_id": 1002}, {**match(), "players": []},
    {**match(), "players": match()["players"] * 2}, {**match(), "patch": True},
    {**match(), "players": [{**match()["players"][0], "hero_id": True}]},
])
def test_bad_source_schema_never_receives_verified_receipt(tmp_path, raw):
    s, _ = source(tmp_path, raw=raw)
    with pytest.raises(ValueError):
        s.fetch_match_source(1001, 145)
    assert not list(tmp_path.glob("*.json"))


def test_requested_hero_account_must_match_actual_player_row(tmp_path):
    s, _ = source(tmp_path)
    for hero, account in ((145, 222), (112, 111), (1, None)):
        with pytest.raises(ValueError, match="association"):
            s.fetch_match_source(1001, hero, account_id=account)


def test_rank_tier_is_high_rank_proxy_not_claimed_numeric_high_mmr(tmp_path):
    s, _ = source(tmp_path, pros=[])
    result = s.fetch_match_source(1001, 145, probe_replay=False)
    assert result.expertise_class == "high_rank" and result.study.expertise_status == "unknown"
    assert result.expertise_basis == "match_rank_tier_proxy_not_numeric_mmr"
    assert result.rank_tier == 80


@pytest.mark.parametrize("status,binary,expected", [(404, b"", "unavailable"), (410, b"", "unavailable"),
                                                  (403, b"", "unknown"), (200, b"<html>", "unknown"),
                                                  (206, b"BZh9test", "available")])
def test_replay_url_presence_is_not_availability(tmp_path, status, binary, expected):
    s, _ = source(tmp_path, replay_status=status, replay_binary=binary)
    result = s.fetch_match_source(1001, 145)
    assert result.study.replay_availability == expected
    if expected == "available":
        assert "prefix_only_full_download_not_verified" in result.replay_probe.reason_codes


def test_replay_probe_network_failure_is_unknown(tmp_path):
    s, session = source(tmp_path)
    session.routes[match()["replay_url"]] = requests.ConnectionError("test failure")
    assert s.fetch_match_source(1001, 145).replay_probe.status == "unknown"


@pytest.mark.parametrize("url", ["http://127.0.0.1/570/1001_123.dem.bz2",
                                "http://replay273.valve.net/570/1002_123.dem.bz2",
                                "http://user:secret@replay273.valve.net/570/1001_123.dem.bz2",
                                "http://replay273.valve.net:bad/570/1001_123.dem.bz2"])
def test_untrusted_replay_url_cannot_issue_arbitrary_network_request(tmp_path, url):
    s, session = source(tmp_path)
    assert s.probe_replay(url, 1001).status == "unknown"
    assert not session.calls


def test_bounded_discovery_has_real_ids_task_and_differences(tmp_path):
    s, _ = source(tmp_path)
    result = s.discover(145, role="position_1", patch="opendota_patch_id:60", max_fetches=1)
    assert result.status == "sourced_examples" and result.examples[0].study.match_id == 1001
    assert result.examples[0].difference_codes and result.limitations
    result = s.discover(145, patch="other", probe_replay=False, max_fetches=1)
    assert result.status == "unavailable" and "patch_mismatch" in result.exclusions[0][1]


def test_account_discovery_uses_only_get_filtered_history(tmp_path):
    s, session = source(tmp_path)
    url = BASE + "/players/111/matches?hero_id=145&limit=2"
    session.routes[url] = Response([{"match_id": 1001}])
    result = s.discover(145, account_id=111, max_fetches=2, probe_replay=False)
    assert result.examples[0].account_id == 111 and session.calls[0][0] == url


def test_provider_lane_role_and_roaming_do_not_claim_verified_position():
    data = match()
    own = data["players"][0]
    assert estimate_role(data, {**own, "lane_role": True}, "test-ref").confidence == "unknown"
    assert estimate_role(data, {**own, "is_roaming": True}, "test-ref").role == "unknown"
    assert estimate_role(data, {**own, "lane_role": 2}, "test-ref").confidence == "estimated"


def test_http_error_redirect_and_duplicate_json_do_not_cache(tmp_path):
    for response in (Response(status=429), Response(status=302), Response(binary=b'{"match_id":1001,"match_id":1002}')):
        s, session = source(tmp_path)
        session.routes[BASE + "/matches/1001"] = response
        with pytest.raises(ValueError):
            s.fetch_match_source(1001, 145)
        assert response.closed and not list(tmp_path.glob("*.json"))


def test_target_match_cannot_recommend_itself_or_consume_candidate_fetch_limit(tmp_path):
    s, session = source(tmp_path)
    result = s.discover(145, exclude_match_ids=(1001,), max_fetches=1)
    assert result.examples == () and result.exclusions == ((1001, ("target_or_excluded_match",)),)
    assert [url for url, _ in session.calls] == [BASE + "/proMatches"]


def test_saved_discovery_loads_without_network_and_marks_captured_probe(tmp_path):
    s, session = source(tmp_path / "cache")
    result = s.discover(145, max_fetches=1)
    target = save_study_discovery(result, tmp_path / "discovery.json")
    previous_calls = len(session.calls)
    loaded = load_study_discovery(target)
    assert len(session.calls) == previous_calls
    assert loaded.examples[0].account_id == 111
    assert loaded.examples[0].receipts[0].content_sha256 == result.examples[0].receipts[0].content_sha256
    assert loaded.examples[0].study.sources[0].checked_at == result.examples[0].study.sources[0].checked_at
    assert "captured_probe_not_rechecked_current_availability_unknown" in loaded.examples[0].replay_probe.reason_codes
    assert loaded.examples[0].role_estimate.confidence == "estimated"


@pytest.mark.parametrize("mutation", [
    lambda row: row["examples"][0].update(account_id=222),
    lambda row: row["examples"][0].update(player_slot=1),
    lambda row: row["examples"][0]["study"].update(hero_id=112),
    lambda row: row["examples"][0].update(rank_tier=85),
    lambda row: row["examples"][0]["role_estimate"].update(confidence="verified"),
    lambda row: row["examples"][0]["study"].update(patch="7.xx"),
    lambda row: row["examples"][0]["receipts"][0].update(content_sha256="f" * 64),
    lambda row: row["examples"][0]["study"].update(episode_refs=["source:fake#/teamfights/99"]),
    lambda row: row["examples"][0]["replay_probe"].update(prefix_sha256=None),
])
def test_discovery_load_rejects_mismatched_captured_evidence(tmp_path, mutation):
    s, _ = source(tmp_path / "cache")
    target = save_study_discovery(s.discover(145, max_fetches=1), tmp_path / "discovery.json")
    row = json.loads(target.read_text(encoding="utf-8"))
    mutation(row)
    target.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError):
        load_study_discovery(target)


def test_discovery_load_rejects_pro_claim_without_registry_match(tmp_path):
    s, _ = source(tmp_path / "cache", pros=[])
    target = save_study_discovery(s.discover(145, max_fetches=1), tmp_path / "discovery.json")
    row = json.loads(target.read_text(encoding="utf-8"))
    row["examples"][0]["study"]["expertise_status"] = "pro"
    row["examples"][0]["study"]["expertise_evidence_refs"] = ["fake-pro-registry"]
    target.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="expertise"):
        load_study_discovery(target)
