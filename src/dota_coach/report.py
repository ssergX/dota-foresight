from __future__ import annotations

import html as _html

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.progress import ProgressNote
from dota_coach.models import Leak, ScoredMoment
from dota_coach.video.align import video_time_for

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
    return f"{sec // 60}:{sec % 60:02d}"


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
    return (f"<li><b>{_html.escape(l.title)}</b>: {_html.escape(l.magnitude)}"
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
    return f"<li><b>{_html.escape(leak.title)}</b>: {_html.escape(leak.magnitude)}{cov}</li>"


def render_coach_html(brief: CoachBrief, leaks: list[Leak], progress: ProgressNote | None = None,
                      also_visible: list[Leak] | None = None) -> str:
    headline = _html.escape(brief.headline)
    if not brief.focus_leak_key:
        body = f"<h1>{headline}</h1>"
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
            f"<h2>Диагноз</h2><p>{diagnosis}</p>"
            f"<h2>Почему это топит</h2><p>{why}</p>"
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
