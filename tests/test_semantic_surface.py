"""Regression checks for the source-local lifecycle report/API boundary."""
from copy import deepcopy
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.semantic_lifecycle import build_semantic_lifecycles
from dota_coach.semantic_surface import lifecycle_section, attach_semantic_submission
from dota_coach.server import Workbench
from tests.test_semantic_lifecycle import marker, report


@pytest.fixture
def semantic_workbench(tmp_path):
    raw = tmp_path / "match.json"
    raw.write_text(json.dumps({"match_id": 7, "players": [
        {"account_id": 1, "hero_id": 1, "player_slot": 0}]}), encoding="utf-8")
    work = Workbench(raw, tmp_path / "unused-extraction.json", tmp_path / "unused-catalog.json",
                     tmp_path / "jobs")
    ident = "a" * 24
    directory = work.out / ident
    directory.mkdir(parents=True)
    work.jobs[ident] = {"state": "complete"}
    source = report(marker(2), marker(4, "tp_modifier_removed"))
    path = directory / "semantic-events.json"

    def save():
        path.write_text(json.dumps(source), encoding="utf-8")

    save()
    try:
        yield work, ident, source, save
    finally:
        work.worker.shutdown()


def test_combined_prefix_hash_covers_timeline_and_lifecycle(semantic_workbench):
    work, ident, _, _ = semantic_workbench
    result = work.semantic_prefix(ident, "combat_names", 4)
    assert result["prefix_sha256"] == content_hash({k: v for k, v in result.items() if k != "prefix_sha256"})
    lifecycle = result["lifecycle_prefix"]
    assert lifecycle["prefix_sha256"] == content_hash({k: v for k, v in lifecycle.items() if k != "prefix_sha256"})
    assert lifecycle["dataset_kind"] == result["dataset_kind"] == "synthetic"
    assert result["training_eligible"] is lifecycle["training_eligible"] is False
    assert result["perspective"] == lifecycle["perspective"] == "retrospective_world_observation"
    interval, = lifecycle["lanes"]["combat_names"]["intervals"]
    assert interval["right_censored"] and interval["remove_ref"] is None
    changed = deepcopy(result)
    changed["lifecycle_prefix"]["lanes"]["combat_names"]["intervals"][0]["right_censored"] = False
    assert content_hash({k: v for k, v in changed.items() if k != "prefix_sha256"}) != result["prefix_sha256"]


def test_combined_prefix_excludes_hidden_metadata_and_full_file_hashes(semantic_workbench):
    work, ident, source, save = semantic_workbench
    first = work.semantic_prefix(ident, "combat_names", 4)
    before_event = source["lanes"]["combat_names"][0]
    before_event["source_trace_hash"] = "d" * 64
    before_event["postmatch_winner"] = True
    before_event["raw_details"]["enemy_hidden_inventory"] = ["item_rapier"]
    source["payload_sha256"] = "e" * 64
    source["source_sha256"] = "f" * 64
    source["lanes"]["provider"] = [{"winner": True}]
    save()
    assert work.semantic_prefix(ident, "combat_names", 4) == first


def test_combined_prefix_never_inspects_future_marker_payload(semantic_workbench):
    work, ident, source, save = semantic_workbench
    first = work.semantic_prefix(ident, "combat_names", 4)
    source["lanes"]["combat_names"][1] = {"source_record_index": 4, "source_domain": "provider",
        "validation": "invented", "raw_details": {"postmatch_winner": True}}
    save()
    assert work.semantic_prefix(ident, "combat_names", 4) == first


def test_prefix_provider_lane_is_not_admitted_to_either_projection(semantic_workbench):
    work, ident, _, _ = semantic_workbench
    with pytest.raises(ValueError, match="provider"):
        work.semantic_prefix(ident, "provider", 4)


def test_lifecycle_rendering_escapes_subjects_and_preserves_unknown_outcomes():
    name = "<script>fake_subject()</script>"
    result = build_semantic_lifecycles(report(marker(2, target=name),
        marker(4, "tp_modifier_removed", target=name)))
    page = lifecycle_section(result)
    assert "<script>fake_subject()" not in page and "&lt;script&gt;fake_subject()" in page
    assert "Снятие не устанавливает прибытие, прерывание TP или раскрытие smoke" in page
    assert "combat-names:7:record:2" in page and "combat-names:7:record:4" in page
    assert "semantic-lifecycles.json" in page


def test_lifecycle_rendering_preserves_missing_bounds_and_raw_clock_limit():
    result = build_semantic_lifecycles(report(marker(1, "tp_modifier_removed"),
        marker(2, target="hero_c"), marker(3, target="hero_d", raw_time=10),
        marker(4, "tp_modifier_removed", target="hero_d", raw_time=13)))
    page = lifecycle_section(result)
    assert "начало не наблюдалось" in page and "конец не наблюдался" in page
    assert "левая граница неизвестна" in page and "правая граница неизвестна" in page
    assert "3 с по сырому clock; не подтверждённая длительность эффекта" in page


def test_semantic_script_uses_text_content_and_cannot_close_script_from_configuration(tmp_path):
    path = tmp_path / "index.html"
    path.write_text("<html><body><p id='semantic-prefix-result'></p></body></html>", encoding="utf-8")
    attach_semantic_submission(path, job_id="</script><script>bad()</script>", token="</script>")
    page = path.read_text(encoding="utf-8")
    assert "</script><script>bad()" not in page
    assert "\\u003c/script>" in page
    assert "textContent" in page and "innerHTML" not in page
    assert "доступность игроку неизвестны" in page


def test_live_report_writes_same_source_bound_lifecycles_and_keeps_them_out_of_blind_case(tmp_path):
    from dota_coach.live_report import render_live_report
    from tests.test_contextual_builds import catalog
    from tests.test_live_report import sources
    from tests.test_semantic_events import sidecar, combat

    extraction, provider = sources()
    path = sidecar(tmp_path / "combat.jsonl", [combat(modifier="modifier_teleporting"),
        combat("DOTA_COMBATLOG_MODIFIER_REMOVE", modifier="modifier_teleporting")])
    directory = tmp_path / "report"
    payload = render_live_report(extraction, provider, account_id=7, catalog=catalog(),
                                out_dir=directory, combat_names_path=path)
    artifact = json.loads((directory / "semantic-lifecycles.json").read_text(encoding="utf-8"))
    assert artifact == payload["semantic_lifecycles"]
    assert artifact["match_id"] == 123 and artifact["replay_sha256"] == extraction.replay.manifest.replay_hash
    assert artifact["dataset_kind"] == extraction.replay.manifest.dataset_kind
    assert artifact["validation"] == "unverified" and artifact["training_eligible"] is False
    interval, = artifact["lanes"]["combat_names"]["intervals"]
    assert interval["subject"] == "hero_b" and interval["remove_ref"] == "combat-names:123:record:3"
    assert interval["arrival"] == interval["interruption"] == "unknown"
    page = (directory / "index.html").read_text(encoding="utf-8")
    assert "id='semantic-lifecycles'" in page and "href='semantic-lifecycles.json'" in page
    blind = directory / "independent-review" / "blinded" / "blind-cases.jsonl"
    cases = blind.read_text(encoding="utf-8").splitlines()
    assert cases
    for text in cases:
        assert "semantic_lifecycles" not in text and "combat-names:" not in text
