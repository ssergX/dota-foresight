import json
from pathlib import Path

from dota_coach.cli import build_match_report
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def test_build_match_report_end_to_end():
    match = normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))
    html = build_match_report(match, account_id=111, video_filename=None,
                              offset=0.0, top_n=5)
    assert "Разбор матча 8001" in html
    assert "Ключевые моменты" in html
