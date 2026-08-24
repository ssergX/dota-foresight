from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

# типы, которые реально производят extract_events / build_episodes:
_PRODUCED = ["teamfight", "death", "objective", "networth_swing", "item_timing", "ward"]
_DEFAULT = "Разбирай процесс и решение по данным, не по исходу. Дай проверяемое действие."


def _m(etype):
    ev = EventCandidate(type=etype, game_time=600, involves_me=True, summary="", data={})
    return ScoredMoment(event=ev, score=1.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL, reasons=[])


def test_every_produced_type_has_section():
    missing = [t for t in _PRODUCED
               if principle_for_moment(_m(EventType(t))) == _DEFAULT]
    assert missing == [], f"нет секции принципа для типов момента: {missing}"


def test_unknown_type_falls_back_to_default():
    # тип момента без секции в md -> дефолтный принцип
    from types import SimpleNamespace
    fake = SimpleNamespace(event=SimpleNamespace(type=SimpleNamespace(value="nonexistent_type")))
    assert principle_for_moment(fake) == _DEFAULT
