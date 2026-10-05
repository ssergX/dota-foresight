import json
from dataclasses import asdict

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.match_review import review_match
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.episodes import build_episodes
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)

_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_cards_carry_no_outcome():
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    review = review_match(_match(), _replay(), 7, FakeLLM(canned), deep_n=2)
    for card in review.cards:
        blob = (card.facts + str(card.numbers)).lower()
        assert not any(t in blob for t in _BANNED_TOKENS)
        assert not any(w in blob for w in _BANNED_WORDS)


def test_every_note_prompt_carries_no_outcome():
    # короткий комментарий гоняется на КАЖДЫЙ эпизод -> сканируем все его промпты
    from dota_coach.coach.episode_card import build_card
    from dota_coach.coach.episode_note import build_note_prompt
    from dota_coach.coach.info_state import render_knowable
    from dota_coach.episodes import slot_index

    match, replay = _match(), _replay()
    my_slot = slot_index(match.player_by_account(7).player_slot)
    for e in build_episodes(match, replay, 7):
        info = build_card(e, replay, my_slot).info
        grounding = render_knowable(info) if info is not None else ""
        msgs = build_note_prompt(e, grounding)
        whole = "".join(m["content"] for m in msgs).lower()
        assert not any(t in whole for t in _BANNED_TOKENS)
        user = msgs[1]["content"].lower()
        assert not any(w in user for w in _BANNED_WORDS)


def test_every_deep_prompt_carries_no_outcome():
    # banned-ТОКЕНЫ (radiant_win и т.п.) — нигде; banned-СЛОВА — только в user-сообщении
    # (system легитимно несёт анти-результат-ИНСТРУКЦИЮ «не рассуждай о победах/поражениях»),
    # как в test_anti_resultism_moment.py. Сканируем ИМЕННО тот промпт, что уходит в LLM —
    # с инфо-блоком реплея (render_info_state), т.к. это единственный динамический текст.
    from dota_coach.coach.episode_card import build_card
    from dota_coach.coach.info_state import render_knowable
    from dota_coach.episodes import slot_index

    match, replay = _match(), _replay()
    my_slot = slot_index(match.player_by_account(7).player_slot)
    episodes = build_episodes(match, replay, 7)
    for e in episodes:
        info = build_card(e, replay, my_slot).info
        info_block = render_knowable(info) if info is not None else ""
        msgs = build_moment_prompt(e.moment, principle_for_moment(e.moment), info_block)
        whole = "".join(m["content"] for m in msgs).lower()
        assert not any(t in whole for t in _BANNED_TOKENS)
        user = msgs[1]["content"].lower()
        assert not any(w in user for w in _BANNED_WORDS)
