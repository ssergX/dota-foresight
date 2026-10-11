from __future__ import annotations

from dataclasses import dataclass

from dota_coach.benchmarks import player_benchmarks
from dota_coach.events import extract_events
from dota_coach.models import (
    EventCandidate, EventType, Match, ParsedReplay, PlayerMatch, ScoredMoment,
)
from dota_coach.scoring import score_events


def my_death_times(parsed: ParsedReplay, my_slot: int) -> list[int]:
    """Игровые секунды, где мой слот перешёл alive->dead (респавн игнор). Соло-смерти тоже."""
    times: list[int] = []
    prev_alive: bool | None = None
    for f in parsed.frames:
        u = f.units.get(my_slot)
        if u is None or u.alive is None:
            prev_alive = None
            continue
        if prev_alive is True and not u.alive:
            times.append(f.time)
        prev_alive = u.alive
    return times


@dataclass
class Episode:
    moment: ScoredMoment
    severity: float
    episode_id: str = ""

    def __post_init__(self):
        if not self.episode_id:
            ev = self.moment.event
            self.episode_id = f"incident:{ev.type.value}:{ev.game_time}"


def slot_index(player_slot: int) -> int:
    return player_slot if player_slot < 128 else player_slot - 123


def _death_events(parsed: ParsedReplay, my_slot: int, teamfights) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for t in my_death_times(parsed, my_slot):
        if any(tf.start - 5 <= t <= tf.end + 5 for tf in teamfights):
            continue  # смерть внутри драки — свернётся в эпизод драки
        out.append(EventCandidate(
            type=EventType.DEATH, game_time=t, involves_me=True,
            summary=f"переход alive→dead в срезе {int(t) // 60}:{int(t) % 60:02d}",
            data={"unmatched_teamfight": True, "timing_quality": "sampled_transition"}))
    return out


def _pickoff_events(me: PlayerMatch, teamfights) -> list[EventCandidate]:
    """Discover provider-recorded kills outside teamfights for retrospective review."""
    out: list[EventCandidate] = []
    for kill in me.kills_log:
        t = kill.get("time")
        if t is None or any(tf.start - 5 <= t <= tf.end + 5 for tf in teamfights):
            continue
        victim = (kill.get("key", "") or "").replace("npc_dota_hero_", "").replace("_", " ")
        out.append(EventCandidate(
            type=EventType.PICKOFF, game_time=t, involves_me=True,
            summary=f"убийство ({victim}) в журнале {int(t) // 60}:{int(t) % 60:02d}",
            data={"victim": victim, "timing_quality": "provider_event",
                  "decision_quality": "unassessed"}))
    return out


_MAX_EPISODES = 25  # Navigation limit only; not an assessment of player choices.


def _severity(moment: ScoredMoment, parsed: ParsedReplay | None, my_slot: int) -> float:
    # Retrospective navigation priority only; no inferred choice time or blame.
    return moment.score


def build_episodes(match: Match, parsed: ParsedReplay | None,
                   account_id: int | None) -> list[Episode]:
    me = match.player_by_account(account_id)
    if me is None:
        return []
    my_slot = slot_index(me.player_slot)
    base = [e for e in extract_events(match, account_id)
            if e.type in (EventType.TEAMFIGHT, EventType.NETWORTH_SWING)
            or (e.type == EventType.OBJECTIVE and e.involves_me
                and e.data.get("objective_type") == "building_kill")]
    base += _pickoff_events(me, match.teamfights)
    if parsed is not None:
        base += _death_events(parsed, my_slot, match.teamfights)
    benches = player_benchmarks(match, account_id)
    moments = score_events(base, benches, match, account_id, top_n=10_000)
    ordinals: dict[tuple, int] = {}
    episodes = []
    for m in moments:
        key = (m.event.type.value, m.event.game_time)
        ordinal = ordinals.get(key, 0)
        ordinals[key] = ordinal + 1
        eid = f"incident:{match.match_id}:{my_slot}:{key[0]}:{key[1]}:{ordinal}"
        episodes.append(Episode(m, _severity(m, parsed, my_slot), eid))
    episodes.sort(key=lambda e: (-e.severity, e.moment.event.game_time, e.episode_id))
    episodes = episodes[:_MAX_EPISODES]
    episodes.sort(key=lambda e: e.moment.event.game_time)
    return episodes


def select_deep(episodes: list[Episode], n: int = 1) -> list[Episode]:
    ranked = sorted(episodes, key=lambda e: (-e.severity, e.moment.event.game_time, e.episode_id))
    return ranked[:max(0, n)]
