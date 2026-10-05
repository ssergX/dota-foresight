from __future__ import annotations

from dataclasses import dataclass

from dota_coach.benchmarks import player_benchmarks
from dota_coach.coach.info_state import info_state_at
from dota_coach.events import extract_events
from dota_coach.models import (
    EventCandidate, EventType, Match, ParsedReplay, ScoredMoment,
)
from dota_coach.coach.moment_focus import VERDICT_RANK
from dota_coach.scoring import score_events


def my_death_times(parsed: ParsedReplay, my_slot: int) -> list[int]:
    """Игровые секунды, где мой слот перешёл alive->dead (респавн игнор). Соло-смерти тоже."""
    times: list[int] = []
    prev_alive: bool | None = None
    for f in parsed.frames:
        u = f.units.get(my_slot)
        if u is None:
            continue
        if prev_alive is True and not u.alive:
            times.append(f.time)
        prev_alive = u.alive
    return times


@dataclass
class Episode:
    moment: ScoredMoment
    severity: float
    decision_time: int | None = None   # точка решения (для смерти — раньше момента смерти)


def slot_index(player_slot: int) -> int:
    return player_slot if player_slot < 128 else player_slot - 123


def _death_events(parsed: ParsedReplay, my_slot: int, teamfights) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for t in my_death_times(parsed, my_slot):
        if any(tf.start - 5 <= t <= tf.end + 5 for tf in teamfights):
            continue  # смерть внутри драки — свернётся в эпизод драки
        out.append(EventCandidate(
            type=EventType.DEATH, game_time=t, involves_me=True,
            summary=f"твоя смерть на {t // 60}:{t % 60:02d}", data={"solo": True}))
    return out


_DECISION_WINDOW = 30   # сек назад от смерти, где ищем точку решения
_SAFE_HP_FRAC = 0.85    # «ещё в безопасности» — доля HP выше этой


def _decision_time(parsed: ParsedReplay | None, my_slot: int, ev: EventCandidate) -> int:
    """Момент, когда у игрока ещё была осмысленная альтернатива.

    Для смерти это НЕ момент смерти (hp=0, уже поздно) и НЕ произвольные −5с, а последняя
    секунда перед финальным спадом HP — когда ты был ещё в безопасности и выбрал заход/позицию
    (альтернатива «не идти / TP» ещё существовала). Фолбэк — точка макс-HP в окне. Для прочих
    типов событий — время самого события.
    """
    if ev.type != EventType.DEATH or parsed is None:
        return ev.game_time
    death_t = ev.game_time
    lo = max(0, death_t - _DECISION_WINDOW)
    candidates: list[tuple[int, float]] = []
    for f in parsed.frames:
        if f.time < lo or f.time >= death_t:
            continue
        u = f.units.get(my_slot)
        if u is None or not u.alive or not u.max_hp:
            continue
        candidates.append((f.time, u.hp / u.max_hp))
    if not candidates:
        return death_t
    safe = [t for t, frac in candidates if frac >= _SAFE_HP_FRAC]
    if safe:
        return max(safe)
    return max(candidates, key=lambda c: c[1])[0]


def _severity(moment: ScoredMoment, parsed: ParsedReplay | None, my_slot: int,
              decision_time: int) -> float:
    sev = moment.score
    ev = moment.event
    if ev.type == EventType.DEATH and parsed is not None:
        # оцениваем состояние в ТОЧКЕ РЕШЕНИЯ (заход), не в момент смерти (там hp=0)
        info = info_state_at(parsed, decision_time, my_slot)
        if info and info.my_max_hp and info.my_hp / info.my_max_hp > 0.6 \
                and info.unseen_enemies >= 3:
            sev += 5.0  # зашёл на фулл-ХП вслепую — острый эпизод для deep-pick
    return sev


def build_episodes(match: Match, parsed: ParsedReplay | None,
                   account_id: int | None) -> list[Episode]:
    me = match.player_by_account(account_id)
    if me is None:
        return []
    my_slot = slot_index(me.player_slot)
    base = [e for e in extract_events(match, account_id)
            if e.type in (EventType.TEAMFIGHT, EventType.NETWORTH_SWING)]
    if parsed is not None:
        base += _death_events(parsed, my_slot, match.teamfights)
    benches = player_benchmarks(match, account_id)
    moments = score_events(base, benches, match, account_id, top_n=10_000)
    episodes = []
    for m in moments:
        dt = _decision_time(parsed, my_slot, m.event)
        episodes.append(Episode(moment=m, severity=_severity(m, parsed, my_slot, dt),
                                decision_time=dt))
    episodes.sort(key=lambda e: e.moment.event.game_time)
    return episodes


def select_deep(episodes: list[Episode], n: int = 1) -> list[Episode]:
    ranked = sorted(episodes, key=lambda e: (
        VERDICT_RANK.get(e.moment.verdict, 9), -e.severity, e.moment.event.game_time))
    return ranked[:max(0, n)]
