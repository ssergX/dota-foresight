from __future__ import annotations

import argparse
from pathlib import Path
import json
import requests
from dataclasses import replace
from dataclasses import asdict

from dota_coach.benchmarks import player_benchmarks
from dota_coach.coach.llm import make_llm
from dota_coach.coach.match_review import review_match
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.ingest.opendota import fetch_match, fetch_recent
from dota_coach.ingest.replay import ReplayUnavailable, parse_replay, parse_replay_jsonl
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match
from dota_coach.report import render_coach_html, render_match_report, render_report
from dota_coach.scoring import score_events
from dota_coach.video.align import (
    auto_offset, compute_offset, crop_hud_clock, load_clock_templates, opencv_frame_at,
    read_clock, sample_clock_reads, tesseract_clock_ocr, video_time_for,
)
from dota_coach.video.clip import extract as clip_extract
from dota_coach.video.steam_recording import find_session, stitch_window


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


def _ensure_video(args: argparse.Namespace, start_time, duration: int) -> str | None:
    """Путь к mp4: явный --video, либо авто-сшивка окна матча из записи Steam."""
    if args.video:
        return args.video
    if not args.gamerecordings or start_time is None:
        return None
    try:
        found = find_session(int(start_time), duration, args.gamerecordings)
        if found is None:
            print("запись матча в gamerecordings не найдена (буфер затёрт или другая сессия)")
            return None
        import imageio_ffmpeg
        session_dir, avail = found
        out_mp4 = str(Path(args.out) / "_match.mp4")
        Path(args.out).mkdir(parents=True, exist_ok=True)
        print("сшиваю окно матча из записи Steam...")
        stitch_window(session_dir, avail, int(start_time), int(start_time) + duration,
                      out_mp4, imageio_ffmpeg.get_ffmpeg_exe())
        return out_mp4
    except Exception as exc:  # noqa: BLE001 - видео необязательно, отчёт по данным всё равно рендерим
        print(f"авто-сшивка записи не удалась ({exc}); задай --video вручную")
        return None


def _resolve_offset(args: argparse.Namespace, video: str) -> float | None:
    """offset (video-сек, где игровое 0:00): ручной --video-offset или авто по HUD-часам."""
    if args.video_offset is not None:
        return float(args.video_offset)
    try:
        tmpls, meta = load_clock_templates()
        frame_at = opencv_frame_at(video)
        got = auto_offset(lambda t: read_clock(frame_at(t), tmpls, meta),
                          coarse_seed=0.0, span=900, step=60)
        if got is not None:
            print(f"авто-offset по HUD-часам: {got:.1f}s")
        else:
            print("авто-offset не удался (нет кворума чтений); задай --video-offset")
        return got
    except Exception as exc:  # noqa: BLE001 - клипы необязательны
        print(f"авто-выравнивание не удалось ({exc}); задай --video-offset")
        return None


def _build_clips(args: argparse.Namespace, review, start_time, duration: int) -> dict:
    import imageio_ffmpeg

    video = _ensure_video(args, start_time, duration)
    if video is None:
        return {}
    offset = _resolve_offset(args, video)
    if offset is None:
        return {}
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    (Path(args.out) / "clips").mkdir(parents=True, exist_ok=True)
    out: dict = {}
    for i, e in enumerate(review.episodes):
        gt = e.moment.event.game_time
        rel = f"clips/{i:02d}.mp4"
        dst = Path(args.out) / rel
        try:
            clip_extract(video, gt, offset, str(dst), ffmpeg=ffmpeg)
        except Exception as exc:  # noqa: BLE001 - клип необязателен
            print(f"клип {gt}s пропущен: {exc}")
            continue
        if dst.exists() and dst.stat().st_size > 0:   # не встраиваем ссылку на несозданный клип
            out[e.episode_id] = rel
        else:
            print(f"клип {gt}s не создан (ffmpeg не дал файла)")
    return out


def _cmd_analyze(args: argparse.Namespace) -> int:
    raw = fetch_match(args.match_id)
    match = normalize(raw)

    # Новый путь: обзор всего матча по эпизодам (нужен реплей)
    if args.coach:
        try:
            print("тяну реплей (первый раз — до минуты)...")
            parsed = parse_replay(args.match_id)
        except ReplayUnavailable as exc:
            parsed = None
            print(f"реплей недоступен: {exc}")
        if parsed is not None:
            review = review_match(match, parsed, args.account_id, deep_n=args.deep_n)
            start_time = raw.get("start_time") if isinstance(raw, dict) else None
            clips = _build_clips(args, review, start_time, match.duration)
            render_match_report(match.match_id, review.cards, review.notes,
                                review.deep_briefs, clips, args.out,
                                dataset_kind=parsed.manifest.dataset_kind if parsed.manifest else "unknown",
                                ledger=review.ledger, raw_match=raw, account_id=args.account_id,
                                parsed=parsed)
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
            moment_brief = explain_moment(moments, None, info_state=None)
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

        brief = run_coach(matches, args.account_id, None)
        leaks = detect_leaks(matches, args.account_id)
        _focus, also = rank(list(leaks))
        html = render_coach_html(brief, leaks, also_visible=also)
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"coach brief over {len(matches)} matches -> {args.out}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary: surface a clean message
        print(f"ошибка вызова ЛЛМ-тренера: {exc}")
        return 1


def _cmd_dossier(args: argparse.Namespace) -> int:
    try:
        raw_text = Path(args.match_json).read_text(encoding="utf-8-sig")
        from dota_coach.decisions.batch import strict_json
        raw = strict_json(raw_text)
        match = normalize(raw)
        if match.player_by_account(args.account_id) is None:
            raise ValueError("account-id не найден среди игроков этого матча")
        parsed = None
        replay_text = None
        if args.replay_jsonl:
            replay_text = Path(args.replay_jsonl).read_text(encoding="utf-8-sig")
            parsed = parse_replay_jsonl(replay_text.splitlines(), match.match_id)
            if args.synthetic:
                parsed = replace(parsed, manifest=replace(parsed.manifest, dataset_kind="synthetic"))
        review = review_match(match, parsed, args.account_id)
        out = Path(args.out)
        generated_paths = {out.resolve() / name for name in ("index.html", "analysis.json")}
        inputs = [Path(args.match_json)] + ([Path(args.replay_jsonl)] if args.replay_jsonl else [])
        catalog = ()
        if args.study_catalog:
            from dota_coach.learning.portfolio import load_study_catalog
            catalog = load_study_catalog(Path(args.study_catalog).read_text(encoding="utf-8-sig")).matches
            inputs.append(Path(args.study_catalog))
        if any(p.resolve() in generated_paths for p in inputs):
            raise ValueError("выходной отчёт не должен перезаписывать входной файл")
        out.mkdir(parents=True, exist_ok=True)
        (out / "source-match.json").write_text(raw_text, encoding="utf-8")
        if replay_text is not None:
            (out / "source-replay.jsonl").write_text(replay_text, encoding="utf-8")
        # Never overwrite input artifacts with the report's standard filenames.
        render_match_report(match.match_id, review.cards, review.notes, review.deep_briefs,
                            {}, str(out), dataset_kind="synthetic" if args.synthetic else "unknown",
                            ledger=review.ledger,
                            source_files=("source-match.json", "source-replay.jsonl") if replay_text is not None
                                         else ("source-match.json",),
                            raw_match=raw, account_id=args.account_id, parsed=parsed,
                            study_catalog=catalog)
        print(f"доказательный отчёт -> {out / 'index.html'}; оценщик пока недоступен")
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"не удалось создать доказательный отчёт: {exc}")
        return 1


def _guard_outputs(out_dir, names, inputs):
    outputs = {(Path(out_dir).resolve() / n).resolve() for n in names}
    for value in inputs:
        source = Path(value).resolve()
        if source in outputs or any(source.exists() and target.exists() and source.samefile(target) for target in outputs):
            raise ValueError("output must not overwrite an input artifact")


def _cmd_evaluate(args):
    from dota_coach.decisions.batch import read_batch, write_batch_report
    try:
        _guard_outputs(args.out, ("index.html", "evaluations.json", "decision-inputs.json"), (args.batch_json,))
        batch = read_batch(Path(args.batch_json).read_text(encoding="utf-8-sig"), args.experimental)
        result = write_batch_report(batch, args.out)
        print(f"experimental: {result['experimental_assessed']}; validated: 0; -> {Path(args.out) / 'index.html'}")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"evaluation failed: {exc}")
        return 1


def _cmd_review_export(args):
    from dota_coach.decisions.batch import read_batch
    from dota_coach.validation import load_dataset, export_blind_pack
    try:
        _guard_outputs(args.out, ("blind-cases.jsonl", "annotation-template.jsonl", "dataset.jsonl",
                                  "split-audit.json", "README.md"), (args.batch_json, args.dataset_jsonl))
        batch = read_batch(Path(args.batch_json).read_text(encoding="utf-8-sig"))
        result = export_blind_pack(batch.inputs, load_dataset(args.dataset_jsonl), args.out)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"review export failed: {exc}")
        return 1


def _cmd_review_quality(args):
    from dota_coach.validation import load_dataset, load_annotations, load_predictions, evaluate_predictions
    try:
        _guard_outputs(Path(args.out).parent, (Path(args.out).name,),
                       (args.dataset_jsonl, args.annotations_jsonl, args.predictions_jsonl))
        result = evaluate_predictions(load_predictions(args.predictions_jsonl),
            load_annotations(args.annotations_jsonl), load_dataset(args.dataset_jsonl), split=args.split)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"quality evidence (validation pending) -> {args.out}")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"quality review failed: {exc}")
        return 1


def _cmd_feedback(args):
    from dota_coach.feedback import import_feedback, store_feedback
    from dota_coach.decisions.batch import strict_json
    try:
        _guard_outputs(Path(args.store).parent, (Path(args.store).name,), (args.report_json, args.feedback_json))
        values = import_feedback(strict_json(Path(args.report_json).read_text(encoding="utf-8-sig")),
                                 strict_json(Path(args.feedback_json).read_text(encoding="utf-8-sig")))
        count = store_feedback(values, args.store)
        print(f"unreviewed feedback records: {count}; -> {args.store}")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"feedback import failed: {exc}")
        return 1


def _cmd_profile(args):
    from dota_coach.profile import describe_series
    from dota_coach.decisions.batch import strict_json
    import html
    try:
        _guard_outputs(args.out, ("index.html", "profile.json"), args.match_json)
        raw = [strict_json(Path(p).read_text(encoding="utf-8-sig")) for p in args.match_json]
        groups = describe_series(raw, args.account_id)
        payload = {"schema_version": "foresight.descriptive-profile.v1", "groups": [asdict(g) for g in groups],
                   "dataset_kind": "synthetic" if args.synthetic else "unknown",
                   "confirmed_habits": [], "training_status": "insufficient_evidence"}
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "profile.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        body = "".join(f"<article><h2>{html.escape(g.role)} · герой {g.hero_id} · {html.escape(g.patch)}</h2>"
             "<table><tr><th>Метрика</th><th>Медиана</th><th>Данные</th></tr>" + "".join(
             f"<tr><td>{m.metric}</td><td>{m.median_value if m.median_value is not None else 'неизвестно'}</td>"
             f"<td>{m.measured_matches} / {m.considered_matches}</td></tr>" for m in g.metrics) +
             f"</table><p>Матчи: {', '.join(map(str, g.match_ids))}</p></article>" for g in groups)
        page = ("<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Foresight — описательный профиль</title><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px;background:#141c25;color:#eef4fa}td,th{padding:8px;text-align:left}a{color:#9cf}article{border:1px solid #405064;padding:20px;margin:16px 0}</style>"
                "<h1>Описание серии матчей</h1>" + ("<p><b>СИНТЕТИЧЕСКАЯ FIXTURE — проверка программы.</b></p>" if args.synthetic else "<p>Происхождение локальных данных не подтверждено.</p>") +
                "<p>Метрики не доказывают ошибки или устойчивый стиль. Оценка роли приблизительная; уровень соперников и точность извлечения не подтверждены.</p>"
                "<p>План тренировки и прогресс недоступны без проверенных решений и сопоставимых периодов.</p><a href='profile.json'>Источники, знаменатели и JSON</a>" + body + "</html>")
        (out / "index.html").write_text(page, encoding="utf-8")
        print(f"descriptive profile -> {out / 'index.html'}")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"profile failed: {exc}")
        return 1


def _cmd_study(args):
    from dota_coach.ingest.study_sources import OpenDotaStudySource
    try:
        source=OpenDotaStudySource(args.cache)
        result=source.discover(args.hero_id, role=args.role, patch=args.patch,
            limit=args.limit, max_fetches=args.max_fetches)
        target=Path(args.out)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        print(f"source-backed examples: {len(result.examples)} -> {target}")
        return 0
    except (ValueError,TypeError,KeyError,OSError,requests.RequestException) as exc:
        print(f"study sourcing failed: {exc}")
        return 1


def _cmd_catalog(args):
    from dota_coach.ingest.valve_catalog import fetch_valve_catalog,save_valve_snapshot
    try:
        snapshot=fetch_valve_catalog(args.cache,item_ids=tuple(args.item_id),hero_ids=tuple(args.hero_id))
        save_valve_snapshot(snapshot,args.out)
        print(f"Valve snapshot, historical patch applicability unassigned -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError,requests.RequestException) as exc:
        print(f"catalog sourcing failed: {exc}")
        return 1


def _cmd_replay_source(args):
    from dota_coach.ingest.trace import load_trace_result
    from dota_coach.evidence.contracts import content_hash
    try:
        inputs=[args.extraction_json,args.source_jsonl]
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),inputs)
        extraction=load_trace_result(args.extraction_json)
        if args.source_kind=='orders':
            from dota_coach.ingest.order_source import load_order_source
            result=load_order_source(args.source_jsonl,extraction=extraction)
            target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        elif args.source_kind=='command_binding':
            from dota_coach.ingest.command_binding import load_command_binding_source
            result=load_command_binding_source(args.source_jsonl,extraction=extraction,account_id=args.account_id)
            target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        elif args.source_kind=='command_stages':
            from dota_coach.ingest.command_stages import bridge_command_stages
            result=bridge_command_stages(args.source_jsonl,extraction=extraction,account_id=args.account_id,
                cutoff_record_index=args.cutoff_record_index).document
            target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        elif args.source_kind=='projectiles':
            from dota_coach.ingest.projectile_source import load_projectile_source
            result=load_projectile_source(args.source_jsonl,extraction=extraction,account_id=args.account_id,cutoff_record_index=args.cutoff_record_index)
            target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        elif args.source_kind=='unit_control':
            from dota_coach.ingest.unit_control import build_unit_control_source
            result=build_unit_control_source(args.source_jsonl,extraction=extraction,account_id=args.account_id,
                cutoff_record_indices=tuple(args.cutoff_record_index or ()))
            target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        elif args.source_kind=='constraints':
            from dota_coach.ingest.constraint_source import write_constraint_source
            result=write_constraint_source(args.source_jsonl,extraction,args.out,
                resource_slot=args.resource_slot,actor=args.actor,expected_account_id=args.account_id)
        else:
            from dota_coach.ingest.event_visibility import extract_event_visibility
            result=extract_event_visibility(args.source_jsonl,extraction,args.out,
                expected_replay_sha256=args.replay_sha256,expected_source_sha256=args.source_sha256,
                expected_extraction_sha256=content_hash(asdict(extraction)))
        print(f'{args.source_kind}: raw source observations; validation pending -> {args.out}')
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'replay source extraction failed: {exc}');return 1


def _cmd_mechanics_source(args):
    from dota_coach.ingest.trace import load_trace_result
    from dota_coach.decisions.mechanics_adapter import summarize_constraint_mechanics
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),(args.source_jsonl,args.extraction_json))
        result=summarize_constraint_mechanics(args.source_jsonl,extraction=load_trace_result(args.extraction_json),
            account_id=args.account_id,item_id=args.item_id)
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"mechanical operand projections: {result['counts']['projected_samples']}; historical validation pending -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'mechanical source failed: {exc}');return 1


def _cmd_movement_review(args):
    from dota_coach.decisions.movement import load_movement_input,evaluate_movement
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),(args.input_json,))
        result=evaluate_movement(**load_movement_input(args.input_json))
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"movement model: {result['status']}; actual arrival/safety not established -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'movement review failed: {exc}');return 1


def _cmd_defensive_impact_review(args):
    from dota_coach.decisions.defensive_impact import load_defensive_impact_input,evaluate_defensive_impact
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),(args.input_json,))
        if args.html:
            page_path=Path(args.html)
            if page_path.resolve().parent!=Path(args.out).resolve().parent or page_path.resolve()==Path(args.out).resolve():
                raise ValueError('HTML and JSON must have distinct names in the same output directory')
            _guard_outputs(page_path.parent,(page_path.name,),(args.input_json,))
        result=evaluate_defensive_impact(**load_defensive_impact_input(args.input_json))
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if args.html:
            import html
            from dota_coach.analytics_surface import defensive_impact_section
            section=defensive_impact_section(result).replace('href="defensive-impact.json"','href="'+html.escape(target.name,quote=True)+'"')
            origin={'synthetic':'Синтетический сценарий','replay':'Предложенный сценарий replay','unknown':'Происхождение не установлено'}[result['scope']['dataset_kind']]
            page=("<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<link rel='icon' href='data:,'><title>Foresight · условное сравнение</title>"
                "<style>body{font:17px system-ui;background:#101922;color:#e7eff8;max-width:950px;margin:32px auto;padding:0 20px;overflow-wrap:anywhere}"
                "a{color:#a0d3ff}table{border-collapse:collapse}th,td{padding:12px;border:1px solid #496176;text-align:left}.table-scroll{overflow:auto}details{margin-top:24px}</style>"
                '<h1>'+origin+'</h1><p>Исследовательское сравнение двух действий. Реальный игровой вердикт не допускается этим файлом.</p>'+section+'</html>')
            page_path.write_text(page,encoding='utf-8')
        print(f"defensive impact: {result['verdict']}; conditional scenario only -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'defensive impact review failed: {exc}');return 1


def _proposal_outputs(args):
    inputs=(args.input_json,)
    outputs=(Path(args.out),) + ((Path(args.html),) if getattr(args,'html',None) else ())
    if len(outputs)>1 and (outputs[0].resolve()==outputs[1].resolve() or outputs[0].resolve().parent!=outputs[1].resolve().parent):
        raise ValueError('JSON and HTML must be distinct outputs in one directory')
    _guard_outputs(Path(args.out).parent,tuple(path.name for path in outputs),inputs)
    return outputs


def _cmd_terrain_review(args):
    from dota_coach.decisions.terrain import load_terrain_input,evaluate_terrain
    from dota_coach.analytical_bundle import terrain_section,write_proposal_page
    try:
        _proposal_outputs(args)
        result=evaluate_terrain(**load_terrain_input(args.input_json))
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if args.html:
            write_proposal_page(args.html,terrain_section(result),title='Условный расчёт обзора и маршрутов',artifact_name=target.name)
        print(f"terrain review: {result['status']} -> {args.out}");return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'terrain review failed: {exc}');return 1


def _cmd_impact_prefix_review(args):
    from dota_coach.ingest.impact_prefix import load_impact_prefix_input
    from dota_coach.analytical_workflow import evaluate_prefix_workflow
    try:
        _proposal_outputs(args)
        result=evaluate_prefix_workflow(load_impact_prefix_input(args.input_json)).document()
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"impact prefix: {result['prefix']['status']}; portable review authority unavailable -> {args.out}");return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'impact prefix review failed: {exc}');return 1


def _cmd_case_review(args):
    from dota_coach.analytical_workflow import evaluate_case_proposal
    from dota_coach.analytical_bundle import case_section,write_proposal_page
    try:
        _proposal_outputs(args)
        result=evaluate_case_proposal(args.input_json).document()
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if args.html:
            write_proposal_page(args.html,case_section(result['case_assessment']),title='Оценка конкретного выбора',artifact_name=target.name)
        print(f"case review: {result['case_assessment']['verdict']} -> {args.out}");return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'case review failed: {exc}');return 1


def _cmd_verified_history_review(args):
    from dota_coach.learning.verified_history import load_verified_history_input,build_verified_history,history_document
    from dota_coach.analytical_bundle import history_section,write_proposal_page
    try:
        _proposal_outputs(args)
        result=history_document(build_verified_history(**load_verified_history_input(args.input_json)))
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if args.html:
            write_proposal_page(args.html,history_section(result),title='Проверенная история решений',artifact_name=target.name)
        print(f"verified history: {result['status']} -> {args.out}");return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'verified history review failed: {exc}');return 1


def _cmd_criterion_gate_review(args):
    from dataclasses import fields
    from dota_coach.decisions.batch import strict_json
    from dota_coach.evidence.contracts import SourceRef
    from dota_coach.validation.criterion_gate import (CriterionIdentity,ReleasePolicy,GateCohort,
        FactRequirement,ExplanationBinding,evaluate_gate)
    from dota_coach.validation.pipeline import load_dataset,load_predictions,load_annotations
    try:
        inputs=(args.input_json,args.dataset_jsonl,args.predictions_jsonl,args.annotations_jsonl)
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),inputs)
        for path in inputs:
            if Path(path).stat().st_size>16*1024*1024:
                raise ValueError('bounded review inputs required: maximum 16 MiB per file')
        data=strict_json(Path(args.input_json).read_text(encoding='utf-8-sig'))
        if (not isinstance(data,dict) or set(data)!={'schema_version','identity','policy','cohort','fact_requirements','explanation_bindings'}
                or data['schema_version']!='foresight.criterion-gate-input.v1'):
            raise ValueError('exact gate proposal required; registry/admission is not portable')
        def dto(cls,obj):
            if not isinstance(obj,dict) or set(obj)!={f.name for f in fields(cls)}:
                raise ValueError('exact typed gate fields required')
            values=dict(obj)
            for key in ('source_refs','seal_source_refs'):
                if key in values:
                    if not isinstance(values[key],list) or len(values[key])>32:
                        raise ValueError('bounded source receipt list required')
                    values[key]=tuple(dto(SourceRef,r) for r in values[key])
            for key in ('training_match_ids','retrieval_match_ids','training_player_ids','retrieval_player_ids','fact_ids'):
                if key in values:
                    if not isinstance(values[key],list):
                        raise ValueError('portable immutable list required')
                    values[key]=tuple(values[key])
            return cls(**values)
        for key in ('fact_requirements','explanation_bindings'):
            if not isinstance(data[key],list) or len(data[key])>1024:
                raise ValueError('bounded case review inventory required')
        result=evaluate_gate(dto(CriterionIdentity,data['identity']),dto(ReleasePolicy,data['policy']),
            tuple(load_dataset(args.dataset_jsonl)),tuple(load_predictions(args.predictions_jsonl)),
            tuple(load_annotations(args.annotations_jsonl)),cohort=dto(GateCohort,data['cohort']),
            fact_requirements=tuple(dto(FactRequirement,r) for r in data['fact_requirements']),
            explanation_bindings=tuple(dto(ExplanationBinding,r) for r in data['explanation_bindings']))
        target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"criterion gate: {result['status']}; no portable release grant -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'criterion gate review failed: {exc}');return 1


def _cmd_trace_review(args):
    from dota_coach.ingest.trace import parse_trace,load_trace_result,save_trace_result
    from dota_coach.ingest.valve_catalog import load_valve_snapshot
    from dota_coach.decisions.batch import strict_json
    from dota_coach.live_report import render_live_report
    from dota_coach.video.trace_clips import validate_video_options
    try:
        validate_video_options(args.video,args.video_offset)
        inputs=[args.match_json,args.catalog_json,args.extraction_json or args.trace_jsonl]+[p for p in
            (args.video,args.study_json,args.action_states_json,args.combat_names_jsonl,args.orders_jsonl,args.constraint_source_jsonl,args.event_visibility_jsonl,args.command_binding_jsonl,args.projectiles_jsonl,args.unit_control_trace,args.movement_input_json,args.defensive_impact_json,args.impact_prefix_json,args.terrain_input_json,args.history_input_json) if p]
        generated=("clip-navigation.json","index.html","analysis.json","source-match.json","trace-audit.json",
            "observed-actions.json","activation-notebook.json","study-sources.json","build-context.json","profile.json","action-states.json","semantic-events.json",
            "semantic-lifecycles.json","resource-opportunities.json","ward-observations.json","objective-state.json","choice-windows.json","ward-analysis.json","unit-control.json","replay-sources.json","mechanics.json","movement-support.json","defensive-impact.json","impact-prefix.json","case-assessment.json","terrain-support.json","verified-history.json",
            "independent-review/dataset.jsonl","independent-review/quality.json","independent-review/README.md",
            "independent-review/blinded/blind-cases.jsonl","independent-review/blinded/annotation-template.jsonl","independent-review/blinded/index.html",
            "independent-review/system/predictions.jsonl")+(("extraction.json",) if not args.extraction_json else ())
        _guard_outputs(args.out,generated,inputs)
        raw=strict_json(Path(args.match_json).read_text(encoding="utf-8-sig"))
        result=load_trace_result(args.extraction_json) if args.extraction_json else parse_trace(
            args.trace_jsonl,raw["match_id"],expected_replay_sha256=args.replay_sha256)
        if args.replay_sha256 is not None and result.replay.manifest.replay_hash!=args.replay_sha256:
            raise ValueError('cached extraction and independently supplied replay hash disagree')
        if not args.extraction_json:
            save_trace_result(result,Path(args.out)/"extraction.json")
        catalog=load_valve_snapshot(args.catalog_json,raw_dir=args.catalog_raw_dir)
        discovery=None
        if args.study_json:
            from dota_coach.ingest.study_sources import load_study_discovery
            discovery=load_study_discovery(args.study_json)
        elif args.study:
            from dota_coach.ingest.study_sources import OpenDotaStudySource
            player=next(p for p in raw["players"] if p.get("account_id")==args.account_id)
            discovery=OpenDotaStudySource(args.study_cache).discover(player["hero_id"],
                patch=f"opendota_patch_id:{raw['patch']}" if raw.get("patch") is not None else None,
                limit=3,max_fetches=20,exclude_match_ids=(raw['match_id'],))
        states=None
        if args.action_states_json:
            from dota_coach.ingest.action_state import load_action_states
            states=load_action_states(args.action_states_json,extraction=result)
        payload=render_live_report(result,raw,account_id=args.account_id,catalog=catalog,
            out_dir=args.out,discovery=discovery,action_states=states,combat_names_path=args.combat_names_jsonl,
            orders_path=args.orders_jsonl,constraint_source_path=args.constraint_source_jsonl,event_visibility_path=args.event_visibility_jsonl,
            command_binding_path=args.command_binding_jsonl,projectiles_path=args.projectiles_jsonl,unit_control_trace_path=args.unit_control_trace,movement_input_path=args.movement_input_json,
            defensive_impact_path=args.defensive_impact_json,impact_prefix_path=args.impact_prefix_json,terrain_input_path=args.terrain_input_json,history_input_path=args.history_input_json,video_path=args.video,video_offset=args.video_offset,ffmpeg=args.ffmpeg)
        print(f"real replay activation observations: {payload['notebook']['activation_candidates']}; validated: 0 -> {Path(args.out)/'index.html'}")
        return 0
    except (ValueError,TypeError,KeyError,OSError,StopIteration,requests.RequestException) as exc:
        print(f"trace review failed: {exc}")
        return 1


def _cmd_serve(args):
    from dota_coach.server import Workbench,serve_workbench
    try:
        serve_workbench(Workbench(args.match_json,args.extraction_json,args.catalog_json,args.out,
            study_json=args.study_json,catalog_raw_dir=args.catalog_raw_dir,action_states_json=args.action_states_json,combat_names_jsonl=args.combat_names_jsonl,
            orders_jsonl=args.orders_jsonl,constraint_source_jsonl=args.constraint_source_jsonl,event_visibility_jsonl=args.event_visibility_jsonl,
            command_binding_jsonl=args.command_binding_jsonl,projectiles_jsonl=args.projectiles_jsonl,unit_control_trace=args.unit_control_trace,movement_input_json=args.movement_input_json,
            defensive_impact_json=args.defensive_impact_json,impact_prefix_json=args.impact_prefix_json,terrain_input_json=args.terrain_input_json,history_input_json=args.history_input_json,video_path=args.video,video_offset=args.video_offset,ffmpeg=args.ffmpeg),args.port)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f"workbench failed: {exc}")
        return 1


def _cmd_training(args):
    from dota_coach.learning.training import (load_training_goal,load_training_scope,load_training_period,
        assign_exercise,match_study_to_goal,write_training_report)
    from dota_coach.decisions.batch import strict_json
    try:
        paths=[p for p in (args.goal_json,args.scope_json,args.baseline_json,args.followup_json,args.match_json,args.study_json) if p]
        _guard_outputs(args.out,('index.html','training.json'),paths)
        read=lambda p:Path(p).read_text(encoding='utf-8-sig')
        goal=load_training_goal(read(args.goal_json));scope=load_training_scope(read(args.scope_json))
        assignment=assign_exercise(goal,scope,review_match_count=args.review_matches)
        baseline=load_training_period(read(args.baseline_json)) if args.baseline_json else None
        followup=load_training_period(read(args.followup_json)) if args.followup_json else None
        selection=None
        if args.study_json or args.match_json or args.account_id:
            if not all((args.study_json,args.match_json,args.account_id)):
                raise ValueError('study selection requires match-json, study-json and account-id')
            from dota_coach.ingest.study_sources import load_study_discovery
            raw=strict_json(read(args.match_json))
            player=next((p for p in raw['players'] if p.get('account_id')==args.account_id),None)
            if player is None or scope.subject_ref!=f'account:{args.account_id}' or scope.hero_id!=player.get('hero_id') or (
                    scope.patch!=f"opendota_patch_id:{raw.get('patch')}"):
                raise ValueError('training scope does not bind supplied source account, hero and patch')
            selection=match_study_to_goal(goal,raw,account_id=args.account_id,discovery=load_study_discovery(args.study_json))
        payload=write_training_report(assignment,args.out,baseline=baseline,followup=followup,selection=selection)
        print(f"training cycle: {assignment.status}; progress: {payload['progress']['status'] if payload['progress'] else 'not_measured'} -> {Path(args.out)/'index.html'}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'training cycle failed: {exc}')
        return 1


def _cmd_action_states(args):
    from dota_coach.ingest.trace import load_trace_result
    from dota_coach.ingest.action_state import build_action_states,save_action_states
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),(args.trace_jsonl,args.extraction_json))
        result=load_trace_result(args.extraction_json)
        states=build_action_states(args.trace_jsonl,result,resource_slot=args.resource_slot,actor=args.actor)
        save_action_states(states,args.out)
        print(f"own raw prefixes: {len(states['snapshots'])}; client validation pending -> {args.out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'action states failed: {exc}')
        return 1


def _cmd_reserve_review(args):
    from dota_coach.decisions.mana_reserve import read_mana_reserve,evaluate_mana_reserve,resolve_reviewed_facts
    try:
        inputs=[p for p in (args.input_json,args.dataset_jsonl,args.annotations_jsonl) if p]
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),inputs)
        value=read_mana_reserve(Path(args.input_json).read_text(encoding='utf-8-sig'))
        admission={'admitted_patch':None,'verified_fact_ids':frozenset(),'annotation_hashes':(),
            'reviewed_boundary':False,'reviewed_goal':False,'reviewed_action_bindings':False,
            'status':'independent_fact_review_absent'}
        if args.dataset_jsonl or args.annotations_jsonl:
            if not args.dataset_jsonl or not args.annotations_jsonl:
                raise ValueError('both dataset-jsonl and annotations-jsonl required')
            from dota_coach.validation.pipeline import load_dataset,load_annotations
            admission=resolve_reviewed_facts(value,load_dataset(args.dataset_jsonl),load_annotations(args.annotations_jsonl))
        review=evaluate_mana_reserve(value,admitted_patch=admission['admitted_patch'],verified_fact_ids=admission['verified_fact_ids'],
            reviewed_boundary=admission['reviewed_boundary'],reviewed_goal=admission['reviewed_goal'],reviewed_action_bindings=admission['reviewed_action_bindings'])
        out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'schema_version':'foresight.mana-reserve-review.v1','review':asdict(review),
            'admission':admission|{'verified_fact_ids':sorted(admission['verified_fact_ids'])}},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f'mana constraint research: {review.verdict}; strategic quality not established -> {out}')
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'mana reserve review failed: {exc}')
        return 1


def _cmd_choice_review(args):
    from dota_coach.decisions.choice_window import (load_choice_evidence,resolve_resource_choice_windows,
        resolve_choice_windows,resolve_reviewed_choice_admission)
    from dota_coach.ingest.trace import load_trace_result
    from dota_coach.ingest.action_state import load_action_states
    try:
        paths=[p for p in (args.input_json,args.extraction_json,args.action_states_json,
            args.dataset_jsonl,args.annotations_jsonl) if p]
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),paths)
        loaded=load_choice_evidence(args.input_json) if args.input_json else None
        reviewed=bool(args.dataset_jsonl or args.annotations_jsonl)
        if reviewed and (not args.dataset_jsonl or not args.annotations_jsonl):
            raise ValueError('both dataset and annotations are required')
        if loaded and 'samples' in loaded:
            if args.extraction_json or args.action_states_json:
                raise ValueError('typed samples and raw source streams are distinct inputs')
            registry=None
            if reviewed:
                if not args.replay_sha256:raise ValueError('independent replay hash required for reviewed samples')
                from dota_coach.validation.pipeline import load_dataset,load_annotations
                registry=resolve_reviewed_choice_admission(**loaded,replay_sha256=args.replay_sha256,
                    records=load_dataset(args.dataset_jsonl),annotations=load_annotations(args.annotations_jsonl))
            result=resolve_choice_windows(**loaded,admission=registry)
        else:
            if not args.extraction_json or not args.action_states_json:
                raise ValueError('raw choice review requires both extraction and own action states')
            if reviewed:raise ValueError('client-reviewed samples must be supplied as typed choice evidence')
            extraction=load_trace_result(args.extraction_json)
            if args.replay_sha256 and extraction.replay.manifest.replay_hash!=args.replay_sha256:
                raise ValueError('independent replay hash disagrees with extraction')
            states=load_action_states(args.action_states_json,extraction=extraction)
            result=resolve_resource_choice_windows(states,extraction,item_id=args.item_id,**(loaded or {}))
        out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"choice research: {result['sample_count']} samples, {result['supported_choice_count']} supported, {result['unknown_count']} unknown -> {out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'choice review failed: {exc}');return 1


def _cmd_stream_review(args):
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),
            [p for p in (args.input_json,args.dataset_jsonl,args.annotations_jsonl,args.manifest_json) if p])
        if args.manifest_json:
            _guard_outputs(Path(args.manifest_json).parent,(Path(args.manifest_json).name,),
                [p for p in (args.input_json,args.dataset_jsonl,args.annotations_jsonl,args.out) if p])
            if not args.replay_sha256:raise ValueError('independent replay hash required for review manifest')
        if args.stream_kind=='commands':
            from dota_coach.decisions.command_census import load_command_input,census_commands,resolve_reviewed_command_registry,command_input_record
            loaded=load_command_input(args.input_json)
            resolve=resolve_reviewed_command_registry
            manifest=command_input_record
            evaluate=lambda registry:census_commands(**loaded,registry=registry)
        else:
            from dota_coach.decisions.choice_monitor import load_monitor_input,monitor_choice_stream,resolve_reviewed_continuity,monitor_input_record
            loaded=load_monitor_input(args.input_json)
            resolve=resolve_reviewed_continuity
            manifest=monitor_input_record
            evaluate=lambda registry:monitor_choice_stream(**loaded,admission=registry)
        registry=None
        if args.dataset_jsonl or args.annotations_jsonl:
            if not args.dataset_jsonl or not args.annotations_jsonl or not args.replay_sha256:
                raise ValueError('dataset, annotations and independent replay hash required together')
            from dota_coach.validation.pipeline import load_dataset,load_annotations
            registry=resolve(loaded,replay_sha256=args.replay_sha256,
                records=load_dataset(args.dataset_jsonl),annotations=load_annotations(args.annotations_jsonl))
        output=evaluate(registry)
        record=manifest(loaded,replay_sha256=args.replay_sha256) if args.manifest_json else None
        if record is not None:
            file=Path(args.manifest_json);file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(json.dumps(asdict(record),ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
        out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f'{args.stream_kind} stream research; strategic quality not established -> {out}')
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'stream review failed: {exc}');return 1


def _cmd_ward_review(args):
    from dota_coach.decisions.batch import strict_json
    from dota_coach.learning.ward_analysis import analyze_ward_prefix,analyze_ward_task
    try:
        paths=[p for p in (args.source_json,args.goal_json,args.evidence_json,args.dataset_jsonl,args.annotations_jsonl) if p]
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),paths)
        read=lambda path:strict_json(Path(path).read_text(encoding='utf-8-sig'))
        source=read(args.source_json)
        if not args.goal_json:
            if args.evidence_json or args.dataset_jsonl or args.annotations_jsonl:
                raise ValueError('task evidence requires an explicit confirmed task')
            result=analyze_ward_prefix(source,args.ward_id,cutoff_record_index=args.cutoff_record_index)
        else:
            records=annotations=()
            if args.dataset_jsonl or args.annotations_jsonl:
                if not args.dataset_jsonl or not args.annotations_jsonl or not args.evidence_json:
                    raise ValueError('evidence, dataset and annotations are required together')
                from dota_coach.validation.pipeline import load_dataset,load_annotations
                records=load_dataset(args.dataset_jsonl);annotations=load_annotations(args.annotations_jsonl)
            result=analyze_ward_task(source,args.ward_id,read(args.goal_json),
                evidence=read(args.evidence_json) if args.evidence_json else None,
                records=records,annotations=annotations,cutoff_record_index=args.cutoff_record_index)
        out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f"ward source analysis: {result['callback_analysis']['callback_count']} prefix records; utility not established -> {out}")
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'ward review failed: {exc}');return 1


def _cmd_knowledge_review(args):
    from dota_coach.decisions.batch import strict_json,read_fact,read_time,_keys
    from dota_coach.evidence.temporal import TemporalKnowledgePolicy,project_temporal_knowledge
    from dota_coach.evidence.contracts import EntityRef
    try:
        _guard_outputs(Path(args.out).parent,(Path(args.out).name,),(args.input_json,))
        payload=strict_json(Path(args.input_json).read_text(encoding='utf-8-sig'))
        _keys(payload,('schema_version','subject_player','cutoff','policy','facts','dataset_kind'),('entity_bindings','queries'))
        if payload['schema_version']!='foresight.temporal-input.v1':raise ValueError('temporal input schema required')
        policy=payload['policy'];_keys(policy,('version','predicate_max_age_ms'))
        bindings=[]
        for row in payload.get('entity_bindings',[]):
            _keys(row,('fact_id','entity'));bindings.append((row['fact_id'],EntityRef(**row['entity'])))
        result=project_temporal_knowledge(tuple(read_fact(f) for f in payload['facts']),
            subject_player=payload['subject_player'],cutoff=read_time(payload['cutoff']),
            policy=TemporalKnowledgePolicy(policy['version'],tuple(tuple(row) for row in policy['predicate_max_age_ms'])),
            dataset_kind=payload['dataset_kind'],entity_bindings=tuple(bindings),
            queries=tuple(tuple(row) for row in payload.get('queries',[])))
        output=asdict(result)|{'input_hash':result.input_hash,'snapshot_id':result.snapshot_id,'validation':'unverified'}
        out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(f'temporal knowledge: {len(result.states)} queried states; source validation pending -> {out}')
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print(f'knowledge review failed: {exc}');return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dota-coach")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command,kind in (('orders-source','orders'),('constraint-source','constraints'),('event-visibility-source','visibility'),('commands-source','command_binding'),('command-stages-source','command_stages'),('projectiles-source','projectiles'),('unit-control-source','unit_control')):
        source=sub.add_parser(command,help='извлечение наблюдений replay с точными ссылками на источник')
        source.add_argument('--source-jsonl',required=True);source.add_argument('--extraction-json',required=True)
        source.add_argument('--out',required=True)
        if kind=='constraints':
            source.add_argument('--resource-slot',type=int,required=True);source.add_argument('--actor',required=True)
            source.add_argument('--account-id',type=int)
        if kind in ('command_binding','command_stages','projectiles','unit_control'):
            source.add_argument('--account-id',type=int,required=True)
        if kind=='command_stages':source.add_argument('--cutoff-record-index',type=int,required=True)
        if kind=='projectiles':source.add_argument('--cutoff-record-index',type=int)
        if kind=='unit_control':source.add_argument('--cutoff-record-index',type=int,action='append')
        if kind=='visibility':
            source.add_argument('--source-sha256',required=True);source.add_argument('--replay-sha256',required=True)
        source.set_defaults(func=_cmd_replay_source,source_kind=kind)
    mechanics=sub.add_parser('mechanics-source',help='связать сырые переходы собственных полей с ограниченной моделью условий')
    mechanics.add_argument('--source-jsonl',required=True);mechanics.add_argument('--extraction-json',required=True)
    mechanics.add_argument('--account-id',type=int,required=True);mechanics.add_argument('--item-id',default='item_black_king_bar')
    mechanics.add_argument('--out',required=True);mechanics.set_defaults(func=_cmd_mechanics_source)
    movement=sub.add_parser('movement-review',help='проверить условия модели маршрута и подключения союзника')
    movement.add_argument('--input-json',required=True);movement.add_argument('--out',default='out/movement-review.json')
    movement.set_defaults(func=_cmd_movement_review)

    impact=sub.add_parser('defensive-impact-review',help='вычислить HP и ману альтернатив для одной известной угрозы')
    impact.add_argument('--input-json',required=True);impact.add_argument('--out',default='out/defensive-impact.json')
    impact.add_argument('--html',help='создать HTML сценария рядом с выходным JSON')
    impact.set_defaults(func=_cmd_defensive_impact_review)

    history=sub.add_parser('verified-history-review',help='полный учёт истории, допуск привычки и проверка источников')
    history.add_argument('--input-json',required=True);history.add_argument('--out',default='out/verified-history.json')
    history.add_argument('--html');history.set_defaults(func=_cmd_verified_history_review)
    prefix=sub.add_parser('impact-prefix-review',help='собрать условный прогноз одной угрозы из известного до выбора среза')
    prefix.add_argument('--input-json',required=True);prefix.add_argument('--out',default='out/impact-prefix.json')
    prefix.set_defaults(func=_cmd_impact_prefix_review)
    case=sub.add_parser('case-review',help='сквозной расчёт и отдельная проверка допуска конкретного выбора')
    case.add_argument('--input-json',required=True);case.add_argument('--out',default='out/case-assessment.json')
    case.add_argument('--html');case.set_defaults(func=_cmd_case_review)
    terrain=sub.add_parser('terrain-review',help='условный расчёт обзора и маршрутов по исторической сетке')
    terrain.add_argument('--input-json',required=True);terrain.add_argument('--out',default='out/terrain-support.json')
    terrain.add_argument('--html');terrain.set_defaults(func=_cmd_terrain_review)
    gate=sub.add_parser('criterion-gate-review',help='пересчитать качество и проверить предложенные условия допуска критерия')
    gate.add_argument('--input-json',required=True);gate.add_argument('--dataset-jsonl',required=True)
    gate.add_argument('--predictions-jsonl',required=True);gate.add_argument('--annotations-jsonl',required=True)
    gate.add_argument('--out',default='out/criterion-gate.json');gate.set_defaults(func=_cmd_criterion_gate_review)
    choices=sub.add_parser('choice-review',help='расчёт собственного окна выбора и условий применения из операндов')
    choices.add_argument('--input-json');choices.add_argument('--extraction-json');choices.add_argument('--action-states-json')
    choices.add_argument('--replay-sha256');choices.add_argument('--item-id',default='item_black_king_bar')
    choices.add_argument('--dataset-jsonl');choices.add_argument('--annotations-jsonl')
    choices.add_argument('--out',default='out/choice-review.json');choices.set_defaults(func=_cmd_choice_review)
    for command,kind in (('choice-monitor','constraints'),('command-review','commands')):
        stream=sub.add_parser(command,help='проверка потока изменений условий или попыток действия')
        stream.add_argument('--input-json',required=True);stream.add_argument('--dataset-jsonl')
        stream.add_argument('--annotations-jsonl');stream.add_argument('--replay-sha256')
        stream.add_argument('--manifest-json',help='exact DatasetRecord JSONL для независимой разметки')
        stream.add_argument('--out',default=f'out/{command}.json')
        stream.set_defaults(func=_cmd_stream_review,stream_kind=kind)
    ward=sub.add_parser('ward-review',help='временной контекст постановки и анализ проверенных сведений варда')
    ward.add_argument('--source-json',required=True);ward.add_argument('--ward-id',required=True)
    ward.add_argument('--goal-json');ward.add_argument('--evidence-json');ward.add_argument('--dataset-jsonl')
    ward.add_argument('--annotations-jsonl');ward.add_argument('--cutoff-record-index',type=int)
    ward.add_argument('--out',default='out/ward-review.json');ward.set_defaults(func=_cmd_ward_review)
    knowledge=sub.add_parser('knowledge-review',help='доступные и устаревшие сведения до временной границы')
    knowledge.add_argument('--input-json',required=True);knowledge.add_argument('--out',default='out/knowledge-review.json')
    knowledge.set_defaults(func=_cmd_knowledge_review)
    state=sub.add_parser('action-states',help='собственные предметы/способности/ресурсы до наблюдаемой активации')
    state.add_argument('--trace-jsonl',required=True)
    state.add_argument('--extraction-json',required=True)
    state.add_argument('--resource-slot',type=int,required=True)
    state.add_argument('--actor',required=True)
    state.add_argument('--out',default='out/action-states.json')
    state.set_defaults(func=_cmd_action_states)
    training=sub.add_parser('training',help='подтверждённая цель, упражнение, журналы и сравнимый прогресс')
    training.add_argument('--goal-json',required=True)
    training.add_argument('--scope-json',required=True)
    training.add_argument('--baseline-json')
    training.add_argument('--followup-json')
    training.add_argument('--match-json')
    training.add_argument('--study-json')
    training.add_argument('--account-id',type=int)
    training.add_argument('--review-matches',type=int,default=3)
    training.add_argument('--out',default='out/training')
    training.set_defaults(func=_cmd_training)
    reserve=sub.add_parser('reserve-review',help='расчёт заявленного запаса маны из собственных фактов, без оценки исхода')
    reserve.add_argument('--input-json',required=True)
    reserve.add_argument('--dataset-jsonl')
    reserve.add_argument('--annotations-jsonl')
    reserve.add_argument('--out',default='out/mana-reserve-review.json')
    reserve.set_defaults(func=_cmd_reserve_review)
    t=sub.add_parser("trace-review",help="сквозной отчёт по настоящему v3 trace")
    t.add_argument("--match-json",required=True)
    choice=t.add_mutually_exclusive_group(required=True)
    choice.add_argument("--trace-jsonl")
    choice.add_argument("--extraction-json")
    t.add_argument("--replay-sha256",help="независимо вычисленный SHA исходного .dem")
    t.add_argument("--account-id",type=int,required=True)
    t.add_argument("--catalog-json",required=True)
    t.add_argument("--catalog-raw-dir")
    t.add_argument("--out",default="out/real-review")
    t.add_argument("--study",action="store_true",help="read-only поиск доступных учебных матчей")
    t.add_argument("--study-json",help="сохранённые примеры с проверкой hash/binding receipts")
    t.add_argument('--action-states-json',help='собственный prefix artifact, привязанный к этому extraction и аккаунту')
    t.add_argument('--combat-names-jsonl',help='полный combat names sidecar; прямые TP/smoke/modifier markers')
    t.add_argument('--orders-jsonl',help='сырой spectator orders sidecar; стадии команд неизвестны')
    t.add_argument('--constraint-source-jsonl',help='сырой поток изменений собственных операндов')
    t.add_argument('--event-visibility-jsonl',help='сырые optional флаги видимости боевых событий')
    t.add_argument('--unit-control-trace',help='полный исходный replay-trace.v3 для поколений и связей единиц')
    t.add_argument('--projectiles-jsonl',help='сообщения снарядов и контекст сущностей в момент callback')
    t.add_argument('--command-binding-jsonl',help='приказы с entity/handle контекстом в том же callback')
    t.add_argument('--movement-input-json',help='предложение модели маршрута из доступного игроку контекста')
    t.add_argument('--defensive-impact-json',help='условный сценарий одной известной до выбора угрозы')
    t.add_argument('--impact-prefix-json');t.add_argument('--terrain-input-json');t.add_argument('--history-input-json')
    t.add_argument("--study-cache",default="out/study-cache")
    t.set_defaults(func=_cmd_trace_review)

    w=sub.add_parser("serve",help="локальная рабочая область с очередью и статусом анализа")
    w.add_argument("--match-json",required=True)
    w.add_argument("--extraction-json",required=True)
    w.add_argument("--catalog-json",required=True)
    w.add_argument("--catalog-raw-dir")
    w.add_argument("--study-json")
    w.add_argument('--action-states-json')
    w.add_argument('--combat-names-jsonl')
    w.add_argument('--orders-jsonl');w.add_argument('--constraint-source-jsonl');w.add_argument('--event-visibility-jsonl')
    w.add_argument('--unit-control-trace');w.add_argument('--projectiles-jsonl');w.add_argument('--command-binding-jsonl');w.add_argument('--movement-input-json')
    w.add_argument('--defensive-impact-json')
    w.add_argument('--impact-prefix-json');w.add_argument('--terrain-input-json');w.add_argument('--history-input-json')
    w.add_argument("--out",default="out/workbench")
    w.add_argument("--port",type=int,default=8765)
    for command in (t,w):
        command.add_argument('--video',help='локальная запись для коротких клипов наблюдаемых активаций')
        command.add_argument('--video-offset',type=float,help='явное смещение: video seconds = source game seconds + offset; соответствие не проверено')
        command.add_argument('--ffmpeg',help='путь к исполняемому FFmpeg; иначе imageio-ffmpeg или PATH')
    w.set_defaults(func=_cmd_serve)

    s=sub.add_parser("study",help="проверить источники существующих учебных матчей")
    s.add_argument("--hero-id",type=int,required=True)
    s.add_argument("--role")
    s.add_argument("--patch")
    s.add_argument("--limit",type=int,default=3)
    s.add_argument("--max-fetches",type=int,default=8)
    s.add_argument("--cache",default="out/study-cache")
    s.add_argument("--out",default="out/study-sources.json")
    s.set_defaults(func=_cmd_study)

    v=sub.add_parser("catalog",help="сохранить источник механик Valve без ложной привязки к патчу")
    v.add_argument("--item-id",type=int,action="append",default=[])
    v.add_argument("--hero-id",type=int,action="append",default=[])
    v.add_argument("--cache",default="out/valve-cache")
    v.add_argument("--out",default="out/valve-catalog.json")
    v.set_defaults(func=_cmd_catalog)
    d = sub.add_parser("dossier", help="локальный доказательный отчёт без сети и LLM")
    d.add_argument("--match-json", required=True)
    d.add_argument("--replay-jsonl", default=None)
    d.add_argument("--account-id", type=int, required=True)
    d.add_argument("--out", default="out/dossier")
    d.add_argument("--synthetic", action="store_true", help="явно пометить fixture как синтетическую")
    d.add_argument("--study-catalog", default=None, help="локальные кандидаты; импорт не подтверждает источники")
    d.set_defaults(func=_cmd_dossier)

    e = sub.add_parser("evaluate", help="offline экспериментальная рубрика; допуск по умолчанию закрыт")
    e.add_argument("--batch-json", required=True)
    e.add_argument("--experimental", action="store_true", help="сравнить переданные диапазоны, без игровой валидации")
    e.add_argument("--out", default="out/evaluation")
    e.set_defaults(func=_cmd_evaluate)

    r = sub.add_parser("review-export", help="экспортировать слепой пакет независимой разметки")
    r.add_argument("--batch-json", required=True)
    r.add_argument("--dataset-jsonl", required=True)
    r.add_argument("--out", default="out/blind-review")
    r.set_defaults(func=_cmd_review_export)

    q = sub.add_parser("review-quality", help="метрики качества на независимой разметке")
    q.add_argument("--dataset-jsonl", required=True)
    q.add_argument("--annotations-jsonl", required=True)
    q.add_argument("--predictions-jsonl", required=True)
    q.add_argument("--split", default="holdout")
    q.add_argument("--out", default="out/quality.json")
    q.set_defaults(func=_cmd_review_quality)

    f = sub.add_parser("feedback", help="проверить привязку и сохранить обратную связь для ревью")
    f.add_argument("--report-json", required=True)
    f.add_argument("--feedback-json", required=True)
    f.add_argument("--store", default="out/feedback.json")
    f.set_defaults(func=_cmd_feedback)

    p = sub.add_parser("profile", help="описать локальную серию с явными знаменателями")
    p.add_argument("--match-json", required=True, nargs="+")
    p.add_argument("--account-id", required=True, type=int)
    p.add_argument("--out", default="out/profile")
    p.add_argument("--synthetic", action="store_true")
    p.set_defaults(func=_cmd_profile)

    a = sub.add_parser("analyze", help="разбор одного матча")
    a.add_argument("--match-id", type=int, required=True, dest="match_id")
    a.add_argument("--account-id", type=int, required=True, dest="account_id")
    a.add_argument("--video", default=None, help="mp4-запись матча — из неё берётся реальный кадр момента")
    a.add_argument("--video-offset", type=float, default=None, dest="video_offset",
                   help="секунда записи, где игровое время = 0:00 (иначе авто по HUD-часам)")
    a.add_argument("--gamerecordings", default=None,
                   help="папка Steam gamerecordings — авто-поиск и сшивка записи матча")
    a.add_argument("--out", default="report.html")
    a.add_argument("--top-n", type=int, default=10, dest="top_n")
    a.add_argument("--coach", action="store_true", help="доказательный обзор эпизодов без недоказанных вердиктов")
    a.add_argument("--deep", type=int, default=1, dest="deep_n",
                   help="сколько эпизодов раскрыть подробно (кап 2)")
    a.add_argument("--provider", default=None, help="claude|openai; по умолчанию claude")
    a.set_defaults(func=_cmd_analyze)

    l = sub.add_parser("leaks", help="системные лики по последним матчам")
    l.add_argument("--account-id", type=int, required=True, dest="account_id")
    l.add_argument("--n", type=int, default=50)
    l.add_argument("--out", default="leaks.html")
    l.set_defaults(func=_cmd_leaks)

    c = sub.add_parser("coach", help="описательные сигналы по серии матчей")
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
