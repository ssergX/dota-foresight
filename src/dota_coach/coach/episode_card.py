from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.info_state import InfoState, info_state_at, render_info_state
from dota_coach.episodes import Episode
from dota_coach.models import ParsedReplay, Verdict
from dota_coach.decisions.dossier import DecisionDossier, build_dossier


@dataclass(frozen=True)
class EpisodeCard:
    game_time: float
    verdict: Verdict
    facts: str
    numbers: dict
    info: InfoState | None
    episode_id: str = ""
    dossier: DecisionDossier | None = None


def build_card(episode: Episode, parsed: ParsedReplay | None, my_slot: int) -> EpisodeCard:
    ev = episode.moment.event
    info = info_state_at(parsed, ev.game_time, my_slot) if parsed is not None else None
    dossier = build_dossier(episode.episode_id, parsed, ev.game_time, my_slot)
    facts = "Момент выбора не установлен. Ниже — срез в момент события, а не оценка решения.\n"
    if dossier.snapshot:
        values = {f.predicate: f.value for f in dossier.snapshot.facts}
        show = lambda key: "неизвестно" if values.get(key) is None else str(values[key])
        facts += (f"HP {show('self.hp')}/{show('self.max_hp')}; мана {show('self.mana')}; "
                  f"уровень {show('self.level')}.\n"
                  "Наблюдаемость противников неизвестна; экран и внимание игрока не установлены.")
        if all(values.get(k) is None for k in ("self.hp", "self.x", "self.alive")):
            facts += "\nСостояние недоступно или устарело."
    else:
        facts += "Состояние недоступно или устарело."
    return EpisodeCard(game_time=ev.game_time, verdict=Verdict.NOT_ENOUGH_INFO,
                       facts=facts, numbers=dict(ev.data), info=info,
                       episode_id=episode.episode_id, dossier=dossier)
