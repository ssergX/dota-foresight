from __future__ import annotations

import html as _html

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


def _leak_row(l: Leak) -> str:
    ex = ", ".join(str(x) for x in l.example_matches)
    return (f"<li><b>{_html.escape(l.title)}</b>: {_html.escape(l.magnitude)}"
            f"<div class='reasons'>примеры матчей: {ex}</div></li>")


def render_report(match_id: int, moments: list[ScoredMoment], leaks: list[Leak],
                  video_filename: str | None, offset: float) -> str:
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
<h2>Ключевые моменты</h2>
<ul>{moment_items}</ul>
{leaks_section}
{script}
</body></html>"""
