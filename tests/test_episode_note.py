from dota_coach.coach.episode_note import EpisodeNote, build_note_prompt, explain_note, parse_note
from dota_coach.coach.llm import FakeLLM
from dota_coach.episodes import Episode
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _episode():
    return Episode(moment=ScoredMoment(
        EventCandidate(EventType.DEATH, 600, True, "future, hidden", {}),
        5., Confidence.LOW, Verdict.NEUTRAL), severity=5.)


def test_parse_note():
    assert parse_note({"situation": "с", "takeaway": "т"}) == EpisodeNote("с", "т")


def test_unverified_legacy_episode_skips_llm_and_returns_review():
    llm = FakeLLM('{"situation":"Ты виноват","takeaway":"Купи предмет"}')
    note = explain_note(_episode(), None, llm)
    assert "Недостаточно данных" in note.situation
    assert "На записи проверь" in note.takeaway
    assert llm.calls == []


def test_summary_hidden_truth_future_outcome_do_not_change_prompt_or_note():
    ep, llm = _episode(), FakeLLM("{}")
    prompt, note = build_note_prompt(ep, "hidden positions"), explain_note(ep, None, llm)
    ep.moment.event.summary = "победа, пять убийств"
    ep.moment.event.data = {"my_gold_delta": 9000}
    assert build_note_prompt(ep, "другие скрытые позиции") == prompt
    assert explain_note(ep, None, llm) == note
