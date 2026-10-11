from __future__ import annotations

import html as _html
import os
import json
from dataclasses import asdict
from pathlib import Path

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.episode_card import EpisodeCard
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.progress import ProgressNote
from dota_coach.models import Leak, ScoredMoment
from dota_coach.video.align import video_time_for
from dota_coach.decisions.dossier import REASON_RU
from dota_coach.surface import context_sections, feedback_controls, feedback_script

_VERDICT_RU = {
    "mistake": "ошибка",
    "fine_variance": "норм, вария",
    "not_enough_info": "нужен ручной разбор",
    "neutral": "нейтрально",
}
_CONF_RU = {"high": "высокая уверенность", "low": "низкая уверенность"}


def _moment_row(m: ScoredMoment, video_filename: str | None, offset: float) -> str:
    summary = _html.escape(m.event.summary)
    verdict = _VERDICT_RU.get(m.verdict.value, m.verdict.value)
    conf = _CONF_RU.get(m.confidence.value, m.confidence.value)
    reasons = "; ".join(_html.escape(r) for r in m.reasons)
    meta = f"<span class='meta'>[{verdict} · {conf}]</span>"
    body = f"{summary} {meta}<div class='reasons'>{reasons}</div>"
    if video_filename:
        t = video_time_for(m.event.game_time, offset)
        return (f"<li><button onclick=\"seek({t:.3f})\">▶ {m.event.game_time}s</button> "
                f"{body}</li>")
    return f"<li>{m.event.game_time}s — {body}</li>"


def _fmt_time(sec: int) -> str:
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _moment_brief_section(brief: MomentBrief, video_filename: str | None, offset: float,
                          image_b64: str | None = None) -> str:
    ts = _fmt_time(brief.game_time)
    if video_filename:
        t = video_time_for(brief.game_time, offset)
        anchor = f"<button onclick=\"seek({t:.3f})\">▶ {ts}</button>"
    else:
        anchor = f"<b>{ts}</b>"
    verdict = _VERDICT_RU.get(brief.verdict, brief.verdict)
    checklist = "\n".join(f"<li>{_html.escape(c)}</li>" for c in brief.checklist)
    img = (f"<img src='data:image/png;base64,{image_b64}' width='720' "
           f"style='border-radius:8px;margin:6px 0;max-width:100%'>" if image_b64 else "")
    return (
        f"<h2>Разбор фокус-момента {anchor} <span class='meta'>[{verdict}]</span></h2>"
        f"{img}"
        f"<h3>{_html.escape(brief.headline)}</h3>"
        f"<p><b>Вероятно:</b> {_html.escape(brief.hypothesis)}</p>"
        f"<p><b>Спроси себя:</b> {_html.escape(brief.process_question)}</p>"
        f"<p><b>Проверь:</b></p><ul>{checklist}</ul>"
        f"<p class='reasons'>{_html.escape(brief.principle)}</p>"
    )


def _leak_row(l: Leak) -> str:
    ex = ", ".join(str(x) for x in l.example_matches)
    return (f"<li><b>Описательный сигнал: {_html.escape(l.metric or l.key)}</b>: {_html.escape(l.magnitude)}"
            f"<div class='reasons'>примеры матчей: {ex}</div></li>")


def render_report(match_id: int, moments: list[ScoredMoment], leaks: list[Leak],
                  video_filename: str | None, offset: float,
                  moment_brief: MomentBrief | None = None,
                  moment_image_b64: str | None = None) -> str:
    video_block = ""
    script = ""
    if video_filename:
        src = _html.escape(video_filename)
        video_block = f"<video id='vid' src='{src}' controls width='900'></video>"
        script = ("<script>function seek(t){var v=document.getElementById('vid');"
                  "v.currentTime=t;v.play();}</script>")

    moment_items = "\n".join(_moment_row(m, video_filename, offset) for m in moments)
    leak_items = "\n".join(_leak_row(l) for l in leaks)
    leaks_section = (f"<h2>Системные лики</h2><ul>{leak_items}</ul>" if leaks else "")
    brief_section = (_moment_brief_section(moment_brief, video_filename, offset, moment_image_b64)
                     if moment_brief else "")

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Dota Coach — матч {match_id}</title>
<style>
  body{{font-family:sans-serif;max-width:960px;margin:24px auto;color:#eee;background:#1b1b1f}}
  button{{cursor:pointer;background:#2d6cdf;color:#fff;border:0;border-radius:4px;padding:4px 8px}}
  .meta{{color:#9ab}} .reasons{{color:#9a9;font-size:13px;margin:2px 0 10px}}
  li{{margin:8px 0}}
</style></head><body>
<h1>Разбор матча {match_id}</h1>
{video_block}
{brief_section}
<h2>Ключевые моменты</h2>
<ul>{moment_items}</ul>
{leaks_section}
{script}
</body></html>"""


def _coach_drill_row(text: str, metric_ref: str) -> str:
    ref = f" <span class='meta'>[{_html.escape(metric_ref)}]</span>" if metric_ref else ""
    return f"<li>{_html.escape(text)}{ref}</li>"


def _coach_leak_row(leak: Leak) -> str:
    cov = (f" <span class='meta'>(данных: {leak.sample_size} из {leak.considered} матчей)</span>"
           if leak.considered else "")
    return f"<li><b>{_html.escape(leak.metric or leak.key)}</b>: {_html.escape(leak.magnitude)}{cov}</li>"


def render_coach_html(brief: CoachBrief, leaks: list[Leak], progress: ProgressNote | None = None,
                      also_visible: list[Leak] | None = None) -> str:
    headline = _html.escape(brief.headline)
    if not brief.focus_leak_key:
        body = f"<h1>{headline}</h1><p>{_html.escape(brief.diagnosis)}</p>"
    else:
        diagnosis = _html.escape(brief.diagnosis)
        why = _html.escape(brief.why_it_costs)
        drills = "\n".join(_coach_drill_row(d.text, d.metric_ref) for d in brief.drills)
        note = brief.progress_note or (progress.text if progress else None)
        progress_block = (f"<h2>Прогресс</h2><p class='progress'>{_html.escape(note)}</p>"
                          if note else "")
        also = also_visible or []
        also_block = ("<h2>Тоже видно</h2><ul>"
                      + "\n".join(_coach_leak_row(l) for l in also) + "</ul>") if also else ""
        leaks_block = "\n".join(_coach_leak_row(l) for l in leaks)
        body = (
            f"<h1>{headline}</h1>"
            f"<h2>Что измерено</h2><p>{diagnosis}</p>"
            f"<h2>Ограничения</h2><p>{why}</p>"
            f"<h2>Дриллы на следующие игры</h2><ul>{drills}</ul>"
            f"{progress_block}"
            f"{also_block}"
            f"<h2>Все системные лики</h2><ul>{leaks_block}</ul>"
        )

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Dota Coach — системный разбор</title>
<style>
  body{{font-family:sans-serif;max-width:820px;margin:24px auto;color:#eee;background:#1b1b1f}}
  h1{{color:#fff}} h2{{color:#9ab;margin-top:22px}}
  .meta{{color:#9ab;font-size:12px}} .progress{{color:#9d9}}
  li{{margin:6px 0}}
</style></head><body>
{body}
</body></html>"""


def _episode_card_html(card: EpisodeCard, note, brief, clip: str | None) -> str:
    ts = _fmt_time(card.game_time)
    verdict = _VERDICT_RU.get(card.verdict.value, card.verdict.value)
    video = (f"<video src='{_html.escape(clip)}' controls width='720' "
             f"style='border-radius:8px;margin:6px 0;max-width:100%'></video>"
             if clip else "")
    if card.dossier is not None:
        # No evaluated criterion in S0-S2. Arbitrary LLM prose cannot replace the
        # deterministic abstention, even when a caller supplies a brief/note.
        insight = ("<p>Оценка решения недоступна. Событие помогает найти момент для просмотра; "
                   "само по себе оно не доказывает ошибку.</p>")
    elif brief is not None:   # legacy presentation
        checklist = "\n".join(f"<li>{_html.escape(c)}</li>" for c in brief.checklist)
        insight = (
            f"<h4>{_html.escape(brief.headline)}</h4>"
            f"<p><b>Вероятно:</b> {_html.escape(brief.hypothesis)}</p>"
            f"<p><b>Спроси себя:</b> {_html.escape(brief.process_question)}</p>"
            f"<p><b>Проверь:</b></p><ul>{checklist}</ul>"
            f"<p class='reasons'>{_html.escape(brief.principle)}</p>")
    elif note is not None:  # короткий тренерский комментарий
        insight = (
            f"<p>{_html.escape(note.situation)}</p>"
            f"<p><b>Вывод:</b> {_html.escape(note.takeaway)}</p>")
    else:
        insight = ""
    facts = f"<details><summary>Открыть доказательства, альтернативы и ограничения</summary><p class='facts'>{_html.escape(card.facts)}</p>"
    if card.dossier is not None:
        d = card.dossier
        reasons = "".join(f"<li>{_html.escape(REASON_RU.get(r, r))}</li>"
                          for r in d.assessment.reason_codes)
        facts += f"<p><b>Почему отказ от оценки</b></p><ul>{reasons}</ul>"
        facts += "<p>Ниже — собственное состояние в срезе события. Момент выбора не установлен.</p>"
        if d.snapshot:
            for i, fact in enumerate(d.snapshot.facts):
                value = "неизвестно" if fact.value is None else str(fact.value)
                locator = "<br>".join(_html.escape(s.locator + " · " + s.provider)
                                       for s in fact.source_refs) or _html.escape(fact.unknown_reason or "нет источника")
                facts += (f"<details class='evidence'><summary>{_html.escape(fact.predicate)}: "
                          f"{_html.escape(value)}</summary><p>Статус: {_html.escape(fact.status)}; "
                          f"перспектива: {_html.escape(fact.perspective)}; "
                          f"время среза: {fact.valid_at.game_time_ms} ms</p>"
                          f"<p>Источник: {locator}</p><code>{_html.escape(fact.fact_id)}</code></details>")
        if d.manifest:
            facts += f"<p>Схема: {_html.escape(d.manifest.schema_version)}; парсер: {_html.escape(d.manifest.extractor_version)}.</p>"
            facts += "<p>Capabilities:</p><ul>" + "".join(
                f"<li>{_html.escape(c.capability_id)}: {_html.escape(c.implementation)} / {_html.escape(c.validation)}</li>"
                for c in d.manifest.capabilities) + "</ul>"
            facts += f"<p>Хеш исходного артефакта: <code>{_html.escape(d.raw_artifact_hash or 'неизвестен')}</code></p>"
        alternatives = "".join(f"<li>{_html.escape(a.description)} — выполнимость не установлена.</li>"
                               for a in d.alternatives)
        facts += ("<p><b>Альтернативы для проверки</b> (не рекомендации для этого события):</p>"
                  f"<ul>{alternatives}</ul>")
    facts += "</details>"
    outcome = ("<details><summary>Что зафиксировано по событию отдельно от оценки</summary>"
               f"<pre>{_html.escape(json.dumps(card.numbers, ensure_ascii=False, indent=2))}</pre>"
               "<p>Это ретроспективные данные. Они не используются для оценки выбора.</p></details>")
    clip_status = "" if clip else "<p class='meta'>Клип недоступен.</p>"
    return (
        f"<div class='card' id='{_html.escape(card.episode_id or str(card.game_time), quote=True)}'>"
        f"<h3>{ts} <span class='meta'>[{verdict}]</span></h3>"
        f"{video}{clip_status}{insight}{facts}{outcome}{feedback_controls(card)}"
        f"</div>")


def render_match_report(match_id: int, cards: list[EpisodeCard], notes: dict,
                        deep_briefs: dict, clips: dict, out_dir: str,
                        dataset_kind: str = "unknown", ledger=None, source_files: tuple[str, ...] = (),
                        raw_match: dict | None = None, account_id: int | None = None,
                        parsed=None, study_catalog=()) -> None:
    os.makedirs(os.path.join(out_dir, "clips"), exist_ok=True)
    body = "\n".join(
        _episode_card_html(c, notes.get(c.episode_id or c.game_time),
                           deep_briefs.get(c.episode_id or c.game_time),
                           clips.get(c.episode_id or c.game_time))
        for c in cards)
    if dataset_kind == "synthetic":
        data_label = "СИНТЕТИЧЕСКАЯ FIXTURE — проверка интерфейса и контрактов, не разбор реального игрока."
    elif dataset_kind == "replay":
        data_label = "Данные replay. Точность извлечения и оценки пока не подтверждена."
    else:
        data_label = "Происхождение данных не подтверждено. Аналитика экспериментальная."
    timeline = " · ".join(f"<a href='#{_html.escape(c.episode_id or str(c.game_time), quote=True)}'>{_fmt_time(c.game_time)}</a>"
                          for c in cards)
    source_links = " · ".join(f"<a href='{name}'>{label}</a>" for name, label in (
        ("source-match.json", "Исходные данные матча"), ("source-replay.jsonl", "Исходный JSONL replay"))
        if name in source_files and (Path(out_dir) / name).exists())
    extensions, extension_payload = context_sections(raw_match, account_id, parsed, study_catalog)
    payload = {"schema_version": "foresight.dossier-report.v1", "match_id": match_id,
               "dataset_kind": dataset_kind, "assessment_status": "unavailable",
               "assessed_decisions": 0, "opportunity_coverage": None,
               "ledger": asdict(ledger) if ledger is not None else None,
               "cards": [asdict(c) for c in cards], "extensions": extension_payload}
    Path(out_dir, "analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                                       allow_nan=False), encoding="utf-8")
    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>Dota Coach — разбор матча {match_id}</title>
<style>
  body{{font-family:system-ui,sans-serif;max-width:1080px;margin:32px auto;padding:0 20px;color:#e2ebf5;background:#131b25;line-height:1.55}}
  .card{{border:1px solid #344454;border-radius:12px;padding:18px 20px;margin:18px 0;background:#1b2836;scroll-margin-top:80px}}
  h1{{color:#fff}} h3{{color:#cde;margin:0 0 6px}} h4{{color:#fff;margin:8px 0 4px}}
  .meta{{color:#9ab;font-size:13px}} .reasons{{color:#9a9;font-size:13px}}
  .facts{{white-space:pre-line}} details{{margin:12px 0}} summary{{cursor:pointer;color:#abc}}
  .evidence{{padding:8px;border-left:2px solid #40536b}} a{{color:#9ac8ff}} pre,code{{overflow-wrap:anywhere;white-space:pre-wrap}}
  .coverage{{background:#2b2635;padding:16px;border-radius:8px}}
  section{{margin:24px 0;border-top:1px solid #344454;padding:16px 0}} nav{{padding:16px 0;position:sticky;top:0;background:#131b25;z-index:2}}
  h2{{font-size:22px;color:#bdd9f5}} button{{cursor:pointer;border:1px solid #59758d;background:#273b4e;color:#e7f2ff;padding:8px 12px;border-radius:8px;margin:4px 0}}
  textarea{{display:block;box-sizing:border-box;width:100%;background:#152330;color:#edf4fa;border:1px solid #52677b;border-radius:8px;padding:10px;margin:8px 0}}
  table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{text-align:left;padding:8px;border-bottom:1px solid #344454}} label{{display:block}} .feedback{{border-top:1px solid #344454;margin-top:16px;padding-top:8px}}
  @media(max-width:600px){{body{{margin:16px auto;padding:0 12px}}.card{{padding:12px}}nav{{position:static}}table{{font-size:12px}}}}
</style></head><body>
<h1>Разбор матча {match_id}</h1><p class='meta'>Эпизодов для просмотра: {len(cards)}</p>
<section class='coverage'><p><b>{_html.escape(data_label)}</b></p>
<p>Оценено решений: 0. Поиск возможностей выбора ещё недоступен; охват не определён.
Это отличается от «ошибок не найдено».</p>
<p>Открывайте доказательства в карточках. Отдельно показаны доступные наблюдения вардов и журнал покупок. Можно оставить обратную связь.
Подтверждённые привычки и рекомендации требуют независимой проверки.</p>
<p><a href='analysis.json'>Скачать доказательный отчёт JSON</a> · {source_links}</p></section>
<nav><a href='#episodes'>Эпизоды</a> · <a href='#wards'>Варды</a> · <a href='#builds'>Предметы</a> · <a href='#study'>Учебные матчи</a> · <a href='#habits'>Привычки</a></nav>
<h2 id='episodes'>Таймлайн эпизодов</h2><p>{timeline}</p>
{'<p>Эпизоды в доступных данных не обнаружены; это не оценка качества игры.</p>' if not cards else ''}
{body}
{extensions}
{feedback_script(match_id, cards)}
</body></html>"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
