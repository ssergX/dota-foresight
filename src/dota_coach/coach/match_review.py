from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.coach.episode_note import EpisodeNote, explain_note
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.episodes import Episode, build_episodes, select_deep, slot_index
from dota_coach.models import Match, ParsedReplay


@dataclass
class MatchReview:
    episodes: list[Episode]
    cards: list[EpisodeCard]
    notes: dict[int, EpisodeNote]        # game_time -> короткий тренерский комментарий
    deep_briefs: dict[int, MomentBrief]  # game_time -> полный разбор (1-2 острых)


def _try_llm(fn, *args):
    """Ответ claude -p бывает кривым JSON (стохастичность, неэкранированные кавычки).
    Один ретрай, затем мягко пропускаем эпизод — один плохой ответ не должен ронять
    весь разбор матча (карточка+клип эпизода остаются, просто без текста)."""
    for _ in range(2):
        try:
            return fn(*args)
        except Exception:   # noqa: BLE001 - резилиентность: плохой ответ не валит прогон
            continue
    return None


def review_match(match: Match, parsed: ParsedReplay | None, account_id: int | None,
                 llm: CoachLLM, deep_n: int = 1) -> MatchReview:
    me = match.player_by_account(account_id)
    my_slot = slot_index(me.player_slot) if me else 0
    episodes = build_episodes(match, parsed, account_id)
    cards = [build_card(e, parsed, my_slot) for e in episodes]
    info_by_time = {c.game_time: c.info for c in cards}
    deep_set = {e.moment.event.game_time for e in select_deep(episodes, min(deep_n, 2))}

    notes: dict[int, EpisodeNote] = {}
    deep_briefs: dict[int, MomentBrief] = {}
    for e in episodes:
        gt = e.moment.event.game_time
        info = info_by_time.get(gt)
        if gt in deep_set:
            brief = _try_llm(explain_scored, e.moment, llm, info)   # полный разбор
            if brief is not None:
                deep_briefs[gt] = brief
        else:
            note = _try_llm(explain_note, e, info, llm)             # короткий комментарий
            if note is not None:
                notes[gt] = note
    return MatchReview(episodes=episodes, cards=cards, notes=notes, deep_briefs=deep_briefs)
