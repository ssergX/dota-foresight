from __future__ import annotations

import argparse
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks
from dota_coach.coach.llm import make_llm
from dota_coach.coach.match_review import review_match
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.ingest.opendota import fetch_match, fetch_recent
from dota_coach.ingest.replay import ReplayUnavailable, parse_replay
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match
from dota_coach.report import render_coach_html, render_match_report, render_report
from dota_coach.scoring import score_events
from dota_coach.video.align import (
    compute_offset, crop_hud_clock, opencv_frame_at, sample_clock_reads, tesseract_clock_ocr,
    video_time_for,
)


def score_moments(match: Match, account_id: int | None, top_n: int):
    events = extract_events(match, account_id)
    benches = player_benchmarks(match, account_id)
    return score_events(events, benches, match, account_id, top_n=top_n)


def build_match_report(match: Match, account_id: int | None, video_filename: str | None,
                       offset: float, top_n: int = 10, moment_brief=None,
                       moment_image_b64=None) -> str:
    moments = score_moments(match, account_id, top_n)
    return render_report(match.match_id, moments, leaks=[],
                         video_filename=video_filename, offset=offset, moment_brief=moment_brief,
                         moment_image_b64=moment_image_b64)


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


def _grab_moment_frame(video_path: str, game_time: int, offset: float):
    """Реальный кадр записи в фокус-момент -> base64 PNG. Кадр необязателен: сбой -> None."""
    try:
        import base64

        from dota_coach.video.grab import frame_png_at

        png = frame_png_at(video_path, video_time_for(game_time, offset))
        return base64.b64encode(png).decode()
    except Exception as exc:  # noqa: BLE001 - кадр необязателен, разбор всё равно рендерим
        print(f"кадр из записи не получен: {exc}")
        return None


def _build_clips(args: argparse.Namespace, match: Match, review, parsed) -> dict:
    return {}   # Стадия B заполнит; сейчас без клипов


def _cmd_analyze(args: argparse.Namespace) -> int:
    match = normalize(fetch_match(args.match_id))

    # Новый путь: обзор всего матча по эпизодам (нужен реплей)
    if args.coach:
        try:
            print("тяну реплей (первый раз — до минуты)...")
            parsed = parse_replay(args.match_id)
        except ReplayUnavailable as exc:
            parsed = None
            print(f"реплей недоступен: {exc}")
        if parsed is not None:
            review = review_match(match, parsed, args.account_id,
                                  make_llm(args.provider), deep_n=args.deep_n)
            clips = _build_clips(args, match, review, parsed)
            render_match_report(match.match_id, review.cards, review.deep_briefs,
                                clips, args.out)
            print(f"обзор {len(review.cards)} эпизодов -> {args.out}/index.html")
            return 0
        print("нет реплея — одиночный фокус-разбор по данным")

    # Fallback: прежний одиночный отчёт (нет реплея или без --coach)
    offset = 0.0
    video_filename = None
    if args.video:
        video_filename = Path(args.video).name
        offset = args.video_offset if args.video_offset is not None else _video_offset(args.video, match.duration)

    moment_brief = None
    moment_image_b64 = None
    if args.coach:
        try:
            moments = score_moments(match, args.account_id, args.top_n)
            moment_brief = explain_moment(moments, make_llm(args.provider), info_state=None)
            if args.video:
                focus = select_focus_moment(moments)
                if focus is not None:
                    moment_image_b64 = _grab_moment_frame(args.video, focus.event.game_time, offset)
        except Exception as exc:  # noqa: BLE001 - LLM-разбор опционален, отчёт по данным всё равно рендерим
            print(f"LLM-разбор момента пропущен: {exc}")

    html = build_match_report(match, args.account_id, video_filename, offset, args.top_n,
                              moment_brief=moment_brief, moment_image_b64=moment_image_b64)
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
        from dota_coach.leaks.severity import rank

        brief = run_coach(matches, args.account_id, make_llm(args.provider))
        leaks = detect_leaks(matches, args.account_id)
        _focus, also = rank(list(leaks))
        html = render_coach_html(brief, leaks, also_visible=also)
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
    a.add_argument("--video", default=None, help="mp4-запись матча — из неё берётся реальный кадр момента")
    a.add_argument("--video-offset", type=float, default=None, dest="video_offset",
                   help="секунда записи, где игровое время = 0:00 (иначе OCR HUD-часов)")
    a.add_argument("--out", default="report.html")
    a.add_argument("--top-n", type=int, default=10, dest="top_n")
    a.add_argument("--coach", action="store_true", help="LLM-разбор фокус-момента")
    a.add_argument("--deep", type=int, default=1, dest="deep_n",
                   help="сколько эпизодов разобрать LLM вглубь (кап 2)")
    a.add_argument("--provider", default=None, help="claude|openai; по умолчанию claude")
    a.set_defaults(func=_cmd_analyze)

    l = sub.add_parser("leaks", help="системные лики по последним матчам")
    l.add_argument("--account-id", type=int, required=True, dest="account_id")
    l.add_argument("--n", type=int, default=50)
    l.add_argument("--out", default="leaks.html")
    l.set_defaults(func=_cmd_leaks)

    c = sub.add_parser("coach", help="системный ЛЛМ-разбор по серии матчей")
    c.add_argument("--account-id", type=int, required=True, dest="account_id")
    c.add_argument("--n", type=int, default=50)
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


if __name__ == "__main__":
    raise SystemExit(main())
