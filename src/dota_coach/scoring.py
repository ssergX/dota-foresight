from __future__ import annotations

from dota_coach.models import (
    Confidence, EventCandidate, EventType, Match, MetricBenchmark, ScoredMoment, Verdict,
)

_DEDUP_WINDOW = 20  # seconds around a teamfight to drop minor events


def _impact(ev: EventCandidate) -> float:
    if ev.type == EventType.TEAMFIGHT:
        return abs(ev.data.get("my_gold_delta", 0)) / 100.0 + ev.data.get("deaths", 0)
    if ev.type == EventType.NETWORTH_SWING:
        return abs(ev.data.get("delta", 0)) / 100.0
    if ev.type == EventType.OBJECTIVE:
        return 3.0
    if ev.type == EventType.ITEM_TIMING:
        return 1.5
    if ev.type == EventType.DEATH:
        return 2.5
    return 0.5  # ward, misc


def _score_one(ev: EventCandidate, weak_count: int) -> ScoredMoment:
    score = _impact(ev)
    reasons: list[str] = []
    if ev.involves_me:
        score += 3.0
        reasons.append("ты вовлечён")

    verdict = Verdict.NEUTRAL
    confidence = Confidence.LOW

    if ev.type == EventType.NETWORTH_SWING:
        # просадка нетворса — это СЛЕДСТВИЕ, а не доказанное решение: без данных о цели
        # действия / созданном пространстве / альтернативах не клеймим ошибкой (как и слитую
        # драку ниже). Остаётся сигналом-маркером времени для ручного разбора.
        verdict = Verdict.NOT_ENOUGH_INFO
        reasons.append("измеримая просадка нетворса — следствие, нужен ручной разбор")
    elif ev.type == EventType.TEAMFIGHT and ev.data.get("my_gold_delta", 0) < 0:
        # lost fight, but no vision/positioning proof -> do NOT call it a mistake
        verdict = Verdict.NOT_ENOUGH_INFO
        reasons.append("слитая драка — нужен ручной разбор (нет данных о позиции/вижене)")
    elif ev.type == EventType.DEATH:
        reasons.append("твоя смерть")

    if weak_count and ev.type == EventType.ITEM_TIMING:
        reasons.append("на фоне слабых бенчмарков фарма")

    return ScoredMoment(event=ev, score=score, confidence=confidence,
                        verdict=verdict, reasons=reasons)


def _dedup(moments: list[ScoredMoment]) -> list[ScoredMoment]:
    tf_times = [m.event.game_time for m in moments if m.event.type == EventType.TEAMFIGHT]
    kept: list[ScoredMoment] = []
    for m in moments:
        if m.event.type == EventType.TEAMFIGHT:
            kept.append(m)
            continue
        near_tf = any(abs(m.event.game_time - t) <= _DEDUP_WINDOW for t in tf_times)
        if not near_tf:
            kept.append(m)
    return kept


def score_events(events: list[EventCandidate], benchmarks: list[MetricBenchmark],
                 match: Match, account_id: int | None, top_n: int = 10) -> list[ScoredMoment]:
    weak_count = sum(1 for b in benchmarks if b.pct < 0.4)
    scored = [_score_one(ev, weak_count) for ev in events]
    scored = _dedup(scored)
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_n]
