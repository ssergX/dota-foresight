from __future__ import annotations

from dataclasses import dataclass

_BENCH_FLOOR = 0.4  # bench-детекторы срабатывают ниже перцентиля 0.4

# Ручные константы. Значения — стартовые инженерные оценки, калибруются на живом
# прогоне (Task 13). Ключ = metric-имя детектора; вложенно — переопределение по роли,
# "*" — дефолт для всех ролей детектора.
_MANUAL: dict[str, dict] = {
    "deaths_per_game":         {"*": 8.0},
    "time_dead_frac":          {"*": 0.13},   # доля игры мёртвым
    "repeat_victim_kills":     {"*": 2.5},    # в среднем один герой убивает ≥ N раз ЗА ИГРУ (scale-invariant)
    "cs_at_10":                {1: 45.0, 2: 45.0, 3: 35.0},  # ластхиты к 10 мин
    "denies_per_game":         {"*": 8.0},
    "lane_efficiency_pct":     {"*": 40.0},   # ниже — провален лейн
    "neutral_kills_per_game":  {1: 20.0, 2: 15.0, 3: 15.0},
    "camps_stacked_per_game":  {4: 2.0, 5: 2.0},
    "rune_pickups_per_game":   {2: 3.0},
    "obs_per_game":            {4: 4.0, 5: 6.0},
    "sen_per_game":            {4: 3.0, 5: 4.0},
    "obs_lifetime_s":          {4: 180.0, 5: 180.0},  # средняя жизнь варда
    "dewards_per_game":        {4: 1.0, 5: 1.0},
    "teamfight_participation": {3: 0.55, 4: 0.55, 5: 0.55},
}


@dataclass(frozen=True)
class Thresholds:
    def bench_floor(self) -> float:
        return _BENCH_FLOOR

    def manual(self, metric: str, role: int) -> float | None:
        table = _MANUAL.get(metric)
        if table is None:
            return None
        if role in table:
            return float(table[role])
        if "*" in table:
            return float(table["*"])
        return None
