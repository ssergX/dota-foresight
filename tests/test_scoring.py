import json
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.models import Confidence, EventType, Verdict
from dota_coach.scoring import score_events

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_scoring_returns_sorted_top_n():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=3)
    assert len(moments) <= 3
    scores = [mm.score for mm in moments]
    assert scores == sorted(scores, reverse=True)


def test_involving_teamfight_scores_above_neutral_ward():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=20)
    by_type = {}
    for mm in moments:
        by_type.setdefault(mm.event.type, mm.score)
    assert by_type[EventType.TEAMFIGHT] > by_type.get(EventType.WARD, 0)


def test_teamfight_death_without_vision_is_not_outcome_biased():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=20)
    tf = next(mm for mm in moments if mm.event.type == EventType.TEAMFIGHT)
    # lost fight (my_gold_delta<0) but no proof it was a misplay -> not a hard "mistake"
    assert tf.verdict in (Verdict.NOT_ENOUGH_INFO, Verdict.NEUTRAL)
    assert tf.confidence == Confidence.LOW
