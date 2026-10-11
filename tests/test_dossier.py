from dataclasses import replace
import json
from pathlib import Path

from dota_coach.coach.episode_card import build_card
from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.match_review import review_match
from dota_coach.decisions.dossier import build_dossier
from dota_coach.episodes import Episode
from dota_coach.models import (
    Confidence, EventCandidate, EventType, Match, ParsedReplay, PlayerMatch,
    ReplayFrame, ScoredMoment, Teamfight, UnitState, Verdict,
)
from dota_coach.report import render_match_report


def match():
    me = PlayerMatch(7, 0, 1, True, 0, 1, 0, 0, 0, 0)
    return Match(1, 200, True, [me], [Teamfight(10, 15, 3), Teamfight(10, 17, 2)])


def replay():
    me = UnitState(0, 0., 0., 100, 100, 20., 1, 0, True)
    return ParsedReplay(1, 0., {0: "Own"}, [ReplayFrame(10, {0: me})], {0: 2})


def test_same_second_incidents_are_preserved_by_identity():
    llm = FakeLLM('{"headline":"Ты ошибся"}')
    review = review_match(match(), replay(), 7, llm)
    ids = [c.episode_id for c in review.cards]
    assert len(ids) == len(set(ids)) == 2
    assert set(review.notes) | set(review.deep_briefs) == set(ids)
    assert review.ledger.scope_status == "discovery_unavailable"
    assert review.ledger.assessed_count == 0 and not llm.calls


def test_death_state_never_substitutes_for_a_decision_boundary():
    moment = ScoredMoment(EventCandidate(EventType.DEATH, 10, True, "death"),
                          1., Confidence.HIGH, Verdict.MISTAKE)
    card = build_card(Episode(moment, 1.), replay(), 0)
    assert card.verdict == Verdict.NOT_ENOUGH_INFO
    assert card.dossier.boundary.anchor is None
    assert card.dossier.boundary.status == "unresolved"
    assert "Момент выбора не установлен" in card.facts


def test_outcome_changes_do_not_change_abstention_or_boundary():
    a = build_dossier("incident:1", replay(), 10, 0)
    b = build_dossier("incident:1", replace(replay(), frames=replay().frames + [
        ReplayFrame(99, {0: replace(replay().frames[0].units[0], hp=0, alive=False)})]), 10, 0)
    assert a.boundary == b.boundary
    assert a.assessment.assessment_hash == b.assessment.assessment_hash
    assert a.snapshot.input_hash == b.snapshot.input_hash


def test_render_abstention_ignores_accusing_llm_and_exports_evidence(tmp_path):
    review = review_match(match(), replay(), 7)
    fake = type("BadBrief", (), {"headline": "Ты ошибся на 92%"})()
    render_match_report(1, review.cards, {}, {review.cards[0].episode_id: fake}, {},
                        str(tmp_path), "synthetic", review.ledger)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert "92%" not in html and "СИНТЕТИЧЕСКАЯ FIXTURE" in html
    assert "Момент выбора не установлен" in html and "self.hp" in html
    assert payload["opportunity_coverage"] is None and payload["assessed_decisions"] == 0
    assert all(c["dossier"]["assessment"]["verdict"] == "insufficient_evidence"
               for c in payload["cards"])


def test_cli_offline_dossier_is_explicitly_synthetic(tmp_path):
    from dota_coach.cli import main
    root = Path(__file__).parent / "fixtures"
    raw = json.loads((root / "opendota_match_sample.json").read_text(encoding="utf-8"))
    account = raw["players"][0]["account_id"]
    rc = main(["dossier", "--match-json", str(root / "opendota_match_sample.json"),
               "--replay-jsonl", str(root / "replay_sample.jsonl"),
               "--account-id", str(account), "--synthetic", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "source-replay.jsonl").exists()
    assert "СИНТЕТИЧЕСКАЯ FIXTURE" in (tmp_path / "index.html").read_text(encoding="utf-8")
