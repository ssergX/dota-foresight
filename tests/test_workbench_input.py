import json

import pytest

from dota_coach.server import Workbench


def raw():
    return {"match_id": 123, "players": [{"account_id": 7, "hero_id": 1, "player_slot": 0,
                                         "personaname": "<script>untrusted()</script>"}]}


def workbench(tmp_path, value):
    source = tmp_path / "match.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    return Workbench(source, tmp_path / "extract.json", tmp_path / "catalog.json", tmp_path / "reports")


@pytest.mark.parametrize("field,value", [("hero_id", "<img src=x onerror=alert(1)>"),
                                       ("hero_id", True), ("hero_id", 0),
                                       ("account_id", True), ("account_id", "7"),
                                       ("player_slot", 10), ("player_slot", False),
                                       ("personaname", {"html": "untrusted"})])
def test_workbench_rejects_malformed_landing_page_source_before_worker(tmp_path, field, value):
    source = raw()
    source["players"][0][field] = value
    with pytest.raises(ValueError):
        workbench(tmp_path, source)


@pytest.mark.parametrize("value", [True, 0, "<script>untrusted()</script>", None])
def test_workbench_requires_numeric_positive_match_id(tmp_path, value):
    source = raw() | {"match_id": value}
    with pytest.raises(ValueError, match="match_id"):
        workbench(tmp_path, source)


def test_workbench_rejects_ambiguous_accounts_and_slots(tmp_path):
    source = raw()
    source["players"].append(source["players"][0] | {"player_slot": 1})
    with pytest.raises(ValueError, match="однозначно"):
        workbench(tmp_path, source)
    source["players"][1]["account_id"] = 8
    source["players"][1]["player_slot"] = 0
    with pytest.raises(ValueError, match="player_slot"):
        workbench(tmp_path, source)


def test_workbench_escapes_persona_and_allows_anonymous_teammates(tmp_path):
    source = raw()
    source["players"].append({"account_id": None, "hero_id": 2, "player_slot": 1})
    work = workbench(tmp_path, source)
    try:
        assert "<script>untrusted()" not in work.page()
        assert "&lt;script&gt;" in work.page()
        assert work.accounts == {7}
    finally:
        work.worker.shutdown(wait=True)
