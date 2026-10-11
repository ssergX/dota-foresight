from dataclasses import asdict, replace
import hashlib
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.valve_catalog import (FetchReceipt, HeroDescriptor, MechanicDescriptor,
                                            ValveCatalogSnapshot, fetch_valve_catalog,
                                            load_valve_snapshot, save_valve_snapshot)


def fake_payload(endpoint, *, identity=116):
    item = {"id": identity, "name": "item_fixture", "name_loc": "Fixture item"}
    hero = {"id": 1, "name": "npc_dota_hero_fixture", "name_loc": "Fixture hero", "primary_attr": 0}
    if endpoint == "itemlist":
        return {"result": {"data": {"itemabilities": [item]}}}
    if endpoint == "herolist":
        return {"result": {"data": {"heroes": [hero]}}}
    if endpoint == "itemdata":
        return {"result": {"status": 1, "data": {"items": [item | {
            "desc_loc": "<h1>Active:</h1> Fixture magic resistance %resistance%%%.",
            "notes_loc": ["Fixture limitation."], "item_cost": 2000,
            "mana_costs": [25], "cooldowns": [20], "cast_ranges": [500],
            "special_values": [{"name": "resistance", "values_float": [15],
                                "heading_loc": "RESISTANCE:", "is_percentage": True}]}]}}}
    return {"result": {"status": 1, "data": {"heroes": [hero | {"abilities": [{
        "id": 5000, "name": "fixture_ability", "name_loc": "Fixture ability", "desc_loc": "Fixture ability description."}]}]}}}


class Response:
    def __init__(self, payload, *, status=200):
        self.content = json.dumps(payload, ensure_ascii=False).encode()
        self.headers = {"etag": "fixture-etag", "set-cookie": "must-not-be-stored"}
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("fixture HTTP error")
    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]
    def close(self):
        pass


class Session:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate
    def get(self, url, **kwargs):
        from urllib.parse import urlparse
        endpoint = urlparse(url).path.rsplit("/", 1)[-1]
        self.calls.append((url, kwargs))
        payload = fake_payload(endpoint)
        if self.mutate:
            payload = self.mutate(endpoint, payload)
        return Response(payload)


def test_read_only_adapter_retains_receipts_raw_hashes_and_unknown_patch(tmp_path):
    session = Session()
    snapshot = fetch_valve_catalog(tmp_path, item_ids=(116,), hero_ids=(1,), session=session)
    assert len(session.calls) == 4
    assert all(kwargs == {"timeout": (10, 30), "allow_redirects": False, "stream": True} for _, kwargs in session.calls)
    assert snapshot.patch is None and snapshot.validation_status == "unverified"
    assert snapshot.item(116).item_cost == 2000
    assert snapshot.item("fixture").description == "Active: Fixture magic resistance %resistance%%%."
    assert snapshot.heroes[0].abilities[0].label == "Fixture ability"
    assert all("set-cookie" not in dict(r.headers) for r in snapshot.receipts)
    for receipt in snapshot.receipts:
        body = (tmp_path / "raw" / f"{receipt.payload_sha256}.json").read_bytes()
        assert hashlib.sha256(body).hexdigest() == receipt.payload_sha256
    path = tmp_path / "snapshots" / snapshot.snapshot_id / "catalog.json"
    assert load_valve_snapshot(path, raw_dir=tmp_path / "raw") == snapshot


def test_snapshot_hash_and_raw_receipts_detect_tampering(tmp_path):
    snapshot = fetch_valve_catalog(tmp_path, session=Session())
    path = tmp_path / "snapshots" / snapshot.snapshot_id / "catalog.json"
    row = json.loads(path.read_text())
    row["items"][0]["label"] = "Tampered"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_valve_snapshot(changed)
    raw = tmp_path / "raw" / f"{snapshot.receipts[0].payload_sha256}.json"
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="receipt hash"):
        load_valve_snapshot(path, raw_dir=tmp_path / "raw")


def test_live_snapshot_cannot_claim_patch_or_validation(tmp_path):
    snapshot = fetch_valve_catalog(tmp_path, session=Session())
    for changes in ({"patch": "fixture-patch"}, {"validation_status": "validated"},
                    {"patch_applicability": "matching"}):
        with pytest.raises(ValueError, match="cannot assert"):
            replace(snapshot, **changes)
    with pytest.raises(ValueError, match="receipt absent"):
        replace(snapshot, items=(replace(snapshot.items[0], receipt_hash=content_hash("missing")),))


def test_error_status_and_wrong_details_are_rejected_and_unknown_ids_not_fetched(tmp_path):
    def error(endpoint, payload):
        return {"result": {"status": 8}} if endpoint == "itemlist" else payload
    with pytest.raises(ValueError, match="successful data"):
        fetch_valve_catalog(tmp_path / "error", session=Session(error))
    def wrong(endpoint, payload):
        return fake_payload(endpoint, identity=117) if endpoint == "itemdata" else payload
    with pytest.raises(ValueError, match="identity mismatch"):
        fetch_valve_catalog(tmp_path / "wrong", item_ids=(116,), session=Session(wrong))
    unknown = Session()
    with pytest.raises(ValueError, match="absent from Valve list"):
        fetch_valve_catalog(tmp_path / "unknown", item_ids=(99999,), session=unknown)
    assert len(unknown.calls) == 2


def test_snapshot_artifacts_are_immutable(tmp_path):
    snapshot = fetch_valve_catalog(tmp_path / "cache", session=Session())
    path = tmp_path / "copy.json"
    save_valve_snapshot(snapshot, path)
    save_valve_snapshot(snapshot, path)
    with pytest.raises(ValueError, match="immutable"):
        save_valve_snapshot(replace(snapshot, language="russian"), path)


@pytest.mark.parametrize("item_ids,hero_ids,language", [([116], (), "english"), ((True,), (), "english"),
    ((116, 116), (), "english"), ((), tuple(range(1, 18)), "english"), ((), (), "english&malicious=true")])
def test_invalid_fetch_parameters_do_not_make_requests(tmp_path, item_ids, hero_ids, language):
    session = Session()
    with pytest.raises(ValueError):
        fetch_valve_catalog(tmp_path, item_ids=item_ids, hero_ids=hero_ids, language=language, session=session)
    assert session.calls == []


def test_oversized_stream_stops_before_consuming_the_rest_and_closes_response(tmp_path, monkeypatch):
    import dota_coach.ingest.valve_catalog as valve
    monkeypatch.setattr(valve, "MAX_RESPONSE_BYTES", 100)
    class OversizedResponse:
        status_code = 200
        headers = {}
        closed = False
        consumed_rest = False
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield b"x" * 101
            self.consumed_rest = True
            yield b"more data"
        def close(self):
            self.closed = True
    response = OversizedResponse()
    class StreamSession:
        def get(self, *args, **kwargs):
            return response
    with pytest.raises(ValueError, match="oversized"):
        fetch_valve_catalog(tmp_path, session=StreamSession())
    assert response.closed and not response.consumed_rest
    assert not (tmp_path / "snapshots").exists()
