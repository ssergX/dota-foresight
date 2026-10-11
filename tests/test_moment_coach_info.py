from dota_coach.coach.info_state import EnemyInfo, InfoState
from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict
from dataclasses import replace


def _moment():
    return ScoredMoment(EventCandidate(EventType.DEATH, 845, True, "future", {}),
                        6.5, Confidence.HIGH, Verdict.MISTAKE)


def _info():
    return InfoState(time=845, my_slot=8, my_x=0., my_y=0., my_hp=300, my_max_hp=1000,
                     my_mana=200., my_level=7, my_alive=True,
                     enemies=[EnemyInfo(5, "Invoker", 0., 0., True, False, 72)],
                     unseen_enemies=1, max_missing_for=72)


def test_arbitrary_grounding_is_excluded_from_legacy_prompt():
    first = build_moment_prompt(_moment(), "principle", "known resources")
    assert build_moment_prompt(_moment(), "hidden truth", "future and hidden enemies") == first


def test_unvalidated_info_cannot_upgrade_legacy_explanation():
    llm = FakeLLM("{}")
    info = _info()
    first = explain_scored(_moment(), llm, info)
    info = replace(info, enemies_near=5, my_hp=9999)
    assert explain_scored(_moment(), llm, info) == first
    assert explain_scored(_moment(), llm, None) == first
    assert llm.calls == []
