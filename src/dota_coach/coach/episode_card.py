from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.info_state import InfoState, info_state_at, render_info_state
from dota_coach.episodes import Episode
from dota_coach.models import ParsedReplay, Verdict


@dataclass(frozen=True)
class EpisodeCard:
    game_time: int
    verdict: Verdict
    facts: str
    numbers: dict
    info: InfoState | None


def build_card(episode: Episode, parsed: ParsedReplay | None, my_slot: int) -> EpisodeCard:
    ev = episode.moment.event
    # разбор грунтим в ТОЧКЕ РЕШЕНИЯ; таймстамп карточки/клипа остаётся на ev.game_time
    t = episode.decision_time if episode.decision_time is not None else ev.game_time
    info = info_state_at(parsed, t, my_slot) if parsed is not None else None
    facts = render_info_state(info) if info is not None else ev.summary
    return EpisodeCard(game_time=ev.game_time, verdict=episode.moment.verdict,
                       facts=facts, numbers=dict(ev.data), info=info)
