from __future__ import annotations

import argparse
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.ingest.opendota import fetch_match, fetch_recent
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match
from dota_coach.report import render_coach_html, render_report
from dota_coach.scoring import score_events
from dota_coach.video.align import (
    compute_offset, crop_hud_clock, opencv_frame_at, sample_clock_reads, tesseract_clock_ocr,
)


def build_match_report(match: Match, account_id: int | None, video_filename: str | None,
                       offset: float, top_n: int = 10) -> str:
    events = extract_events(match, account_id)
    benches = player_benchmarks(match, account_id)
    moments = score_events(events, benches, match, account_id, top_n=top_n)
    return render_report(match.match_id, moments, leaks=[],
                         video_filename=video_filename, offset=offset)


def _video_offset(video_path: str, duration: int) -> float:
    # sample the HUD clock at a few evenly-spread points
    sample_times = [duration * f for f in (0.15, 0.4, 0.65, 0.9)]
    reads = sample_clock_reads(
        sample_times,
        frame_at=opencv_frame_at(video_path),
        ocr=tesseract_clock_ocr,
        crop=crop_hud_clock,
    )
    if not reads:
        print("warning: не удалось считать игровые часы с HUD — видео не синхронизировано "
              "(подстрой crop_hud_clock box под своё разрешение); offset=0")
        return 0.0
    return compute_offset(reads)


def _cmd_analyze(args: argparse.Namespace) -> int:
    match = normalize(fetch_match(args.match_id))
    offset = 0.0
    video_filename = None
    if args.video:
        video_filename = Path(args.video).name
        offset = _video_offset(args.video, match.duration)
    html = build_match_report(match, args.account_id, video_filename, offset, args.top_n)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"report -> {args.out}")
    return 0


def _cmd_leaks(args: argparse.Namespace) -> int:
    ids = fetch_recent(args.account_id, args.n)
    matches = [normalize(fetch_match(mid)) for mid in ids]
    leaks = detect_leaks(matches, args.account_id)
    html = render_report(match_id=0, moments=[], leaks=leaks,
                         video_filename=None, offset=0.0)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"leaks over {len(matches)} matches -> {args.out}")
    return 0


def _cmd_coach(args: argparse.Namespace) -> int:
    ids = fetch_recent(args.account_id, args.n)
    matches = [normalize(fetch_match(mid)) for mid in ids]

    if args.dry_run:
        from dota_coach.coach.coach import _select_focus
        from dota_coach.coach.history import latest_brief
        from dota_coach.coach.principles import principles_for
        from dota_coach.coach.progress import compare_focus
        from dota_coach.coach.prompt import build_coach_prompt

        leaks = detect_leaks(matches, args.account_id)
        focus = _select_focus(leaks)
        if focus is None:
            print("Системных ликов по этой серии не найдено — ЛЛМ не нужен.")
            return 0
        prior = latest_brief(args.account_id)
        progress = compare_focus(prior, leaks)
        messages = build_coach_prompt(leaks, progress, principles_for(focus.key), prior, focus.key)
        for msg in messages:
            print(f"--- {msg['role']} ---\n{msg['content']}\n")
        return 0

    try:
        from dota_coach.coach.coach import run_coach
        from dota_coach.coach.llm import make_llm

        brief = run_coach(matches, args.account_id, make_llm(args.provider))
        leaks = detect_leaks(matches, args.account_id)
        html = render_coach_html(brief, leaks)
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"coach brief over {len(matches)} matches -> {args.out}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary: surface a clean message
        print(f"ошибка вызова ЛЛМ-тренера: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dota-coach")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="разбор одного матча")
    a.add_argument("--match-id", type=int, required=True, dest="match_id")
    a.add_argument("--account-id", type=int, required=True, dest="account_id")
    a.add_argument("--video", default=None)
    a.add_argument("--out", default="report.html")
    a.add_argument("--top-n", type=int, default=10, dest="top_n")
    a.set_defaults(func=_cmd_analyze)

    l = sub.add_parser("leaks", help="системные лики по последним матчам")
    l.add_argument("--account-id", type=int, required=True, dest="account_id")
    l.add_argument("--n", type=int, default=20)
    l.add_argument("--out", default="leaks.html")
    l.set_defaults(func=_cmd_leaks)

    c = sub.add_parser("coach", help="системный ЛЛМ-разбор по серии матчей")
    c.add_argument("--account-id", type=int, required=True, dest="account_id")
    c.add_argument("--n", type=int, default=20)
    c.add_argument("--out", default="coach.html")
    c.add_argument("--dry-run", action="store_true", dest="dry_run")
    c.add_argument(
        "--provider", default=None,
        help="claude|openai; по умолчанию claude (env DOTA_COACH_LLM_PROVIDER)",
    )
    c.set_defaults(func=_cmd_coach)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
