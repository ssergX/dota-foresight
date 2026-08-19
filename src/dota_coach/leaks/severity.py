from __future__ import annotations

from dota_coach.models import Leak


def _impacts() -> dict[str, float]:
    from dota_coach.leaks.registry import DETECTORS
    return {d.key: d.impact for d in DETECTORS}


def _normalized_excess(leak: Leak) -> float:
    if leak.source == "bench":
        return max(0.0, leak.threshold - leak.value)         # перцентильный зазор
    if not leak.threshold:
        return min(1.0, abs(leak.value))
    return min(1.0, abs(leak.value - leak.threshold) / abs(leak.threshold))


def _sample_confidence(sample_size: int) -> float:
    if sample_size < 5:
        return 0.0
    return min(1.0, (sample_size - 4) / 8.0)


def score(leak: Leak) -> float:
    impact = _impacts().get(leak.key, 0.5)
    return _normalized_excess(leak) * impact * _sample_confidence(leak.sample_size)


def rank(leaks: list[Leak]) -> tuple[Leak | None, list[Leak]]:
    for l in leaks:
        l.severity = score(l)
    ordered = sorted(leaks, key=lambda l: (-l.severity, l.key))
    ordered = [l for l in ordered if l.severity > 0]
    if not ordered:
        return None, []
    focus = ordered[0]
    also: list[Leak] = []
    seen_families = {focus.family}
    for l in ordered[1:]:
        if l.family in seen_families:
            continue
        seen_families.add(l.family)
        also.append(l)
    return focus, also
