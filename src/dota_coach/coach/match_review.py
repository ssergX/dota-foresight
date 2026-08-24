from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.episodes import Episode, build_episodes, select_deep, slot_index
from dota_coach.models import Match, ParsedReplay


@dataclass
class MatchReview:
    episodes: list[Episode]
    cards: list[EpisodeCard]
    deep_briefs: dict[int, MomentBrief]


def review_match(match: Match, parsed: ParsedReplay | None, account_id: int | None,
                 llm: CoachLLM, deep_n: int = 1) -> MatchReview:
    me = match.player_by_account(account_id)
    my_slot = slot_index(me.player_slot) if me else 0
    episodes = build_episodes(match, parsed, account_id)
    cards = [build_card(e, parsed, my_slot) for e in episodes]
    deep_briefs: dict[int, MomentBrief] = {}
    for e in select_deep(episodes, min(deep_n, 2)):
        info = build_card(e, parsed, my_slot).info
        deep_briefs[e.moment.event.game_time] = explain_scored(e.moment, llm, info)
    return MatchReview(episodes=episodes, cards=cards, deep_briefs=deep_briefs)
