import json
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks, weak_metrics
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_player_benchmarks_reads_pct():
    benches = player_benchmarks(_match(), account_id=111)
    by_metric = {b.metric: b for b in benches}
    assert by_metric["gold_per_min"].pct == 0.32
    assert by_metric["gold_per_min"].raw == 420


def test_weak_metrics_below_threshold():
    benches = player_benchmarks(_match(), account_id=111)
    weak = {b.metric for b in weak_metrics(benches, threshold=0.4)}
    assert "gold_per_min" in weak          # 0.32 < 0.4
    assert "hero_damage_per_min" not in weak  # 0.4 not < 0.4


def test_missing_player_returns_empty():
    assert player_benchmarks(_match(), account_id=999) == []
