from __future__ import annotations

from statistics import mean, median

from dota_coach.benchmarks import player_benchmarks
from dota_coach.models import Confidence, Leak, Match

_FARM_PCT = 0.4
_DEATHS_MAX = 8.0
_OBS_MIN = 4.0


def _gpm_pct(match: Match, account_id: int | None) -> float | None:
    for b in player_benchmarks(match, account_id):
        if b.metric == "gold_per_min":
            return b.pct
    return None


def detect_leaks(matches: list[Match], account_id: int | None) -> list[Leak]:
    rows = []
    for m in matches:
        me = m.player_by_account(account_id)
        if me is None:
            continue
        rows.append({
            "match_id": m.match_id,
            "gpm_pct": _gpm_pct(m, account_id),
            "deaths": me.deaths,
            "obs": len(me.obs_log),
        })
    if not rows:
        return []

    leaks: list[Leak] = []

    gpms = [r["gpm_pct"] for r in rows if r["gpm_pct"] is not None]
    if gpms and median(gpms) < _FARM_PCT:
        worst = sorted((r for r in rows if r["gpm_pct"] is not None),
                       key=lambda r: r["gpm_pct"])[:3]
        leaks.append(Leak(
            key="farm_below_bracket",
            title="Фарм ниже бракета",
            magnitude=f"медиана GPM в p{int(median(gpms) * 100)}",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    avg_deaths = mean(r["deaths"] for r in rows)
    if avg_deaths > _DEATHS_MAX:
        worst = sorted(rows, key=lambda r: r["deaths"], reverse=True)[:3]
        leaks.append(Leak(
            key="feeding",
            title="Слишком много смертей",
            magnitude=f"в среднем {avg_deaths:.1f} смертей за игру (порог {_DEATHS_MAX:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    avg_obs = mean(r["obs"] for r in rows)
    if avg_obs < _OBS_MIN:
        worst = sorted(rows, key=lambda r: r["obs"])[:3]
        leaks.append(Leak(
            key="low_warding",
            title="Мало вардов",
            magnitude=f"в среднем {avg_obs:.1f} обс-вардов за игру (порог {_OBS_MIN:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    return leaks
