from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.coach.episode_note import EpisodeNote, explain_note
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.episodes import Episode, build_episodes, select_deep, slot_index
from dota_coach.models import Match, ParsedReplay
from dota_coach.decisions.contracts import OpportunityLedger


@dataclass
class MatchReview:
    episodes: list[Episode]
    cards: list[EpisodeCard]
    notes: dict[str, EpisodeNote]
    deep_briefs: dict[str, MomentBrief]
    ledger: OpportunityLedger = OpportunityLedger()


def review_match(match: Match, parsed: ParsedReplay | None, account_id: int | None,
                 llm: CoachLLM | None = None, deep_n: int = 1) -> MatchReview:
    me = match.player_by_account(account_id)
    my_slot = slot_index(me.player_slot) if me else 0
    episodes = build_episodes(match, parsed, account_id)
    cards = [build_card(e, parsed, my_slot) for e in episodes]
    info_by_id = {c.episode_id: c.info for c in cards}
    deep_set = {e.episode_id for e in select_deep(episodes, min(deep_n, 2))}

    notes: dict[str, EpisodeNote] = {}
    deep_briefs: dict[str, MomentBrief] = {}
    for e in episodes:
        eid = e.episode_id
        info = info_by_id.get(eid)
        if eid in deep_set:
            deep_briefs[eid] = explain_scored(e.moment, llm, info)
        else:
            notes[eid] = explain_note(e, info, llm)
    return MatchReview(episodes=episodes, cards=cards, notes=notes, deep_briefs=deep_briefs)
