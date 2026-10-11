"""Retrospective ward observations. Coordinates never establish actual vision."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
import math

from dota_coach.models import ParsedReplay, WardEvent


@dataclass(frozen=True)
class WardInstance:
    entity_id: int
    generation: int
    placed_at: float | None
    removed_at: float | None
    kind: str
    team: int | None
    x: float | None
    y: float | None
    status: str
    source_refs: tuple[str, ...]

    @property
    def observed_lifetime(self) -> float | None:
        if self.placed_at is None or self.removed_at is None or self.status != "removal_observed":
            return None
        return self.removed_at - self.placed_at


def ward_instances(parsed: ParsedReplay, cutoff: float) -> tuple[WardInstance, ...]:
    """Fold only the prefix, preserving repeated indices and unknown removal."""
    if not math.isfinite(cutoff):
        raise ValueError("finite cutoff required")
    records: dict[tuple[int, int], WardInstance] = {}
    events = sorted(enumerate(parsed.wards), key=lambda v: (
        v[1].time, v[1].sequence if v[1].sequence is not None else v[0]))
    for ordinal, e in events:
        if e.time > cutoff:
            break
        key = (e.id, e.generation)
        ref = f"ward_event:{ordinal}@{e.time}"
        prior = records.get(key)
        if e.op == "placed":
            if prior is not None:
                records[key] = WardInstance(e.id, e.generation, prior.placed_at,
                    prior.removed_at, prior.kind, prior.team, prior.x, prior.y,
                    "conflicting_lifecycle", prior.source_refs + (ref,))
            else:
                records[key] = WardInstance(e.id, e.generation, e.time, None,
                    e.kind, e.team, e.x, e.y, "right_censored", (ref,))
        elif e.op == "gone":
            if prior is None:
                records[key] = WardInstance(e.id, e.generation, None, e.time,
                    e.kind, e.team, None, None, "placement_unobserved", (ref,))
            elif prior.removed_at is not None:
                records[key] = WardInstance(e.id, e.generation, prior.placed_at,
                    prior.removed_at, prior.kind, prior.team, prior.x, prior.y,
                    "conflicting_lifecycle", prior.source_refs + (ref,))
            else:
                records[key] = WardInstance(e.id, e.generation, prior.placed_at,
                    e.time, prior.kind, prior.team, prior.x, prior.y,
                    "conflicting_lifecycle" if prior.status == "conflicting_lifecycle" else "removal_observed",
                    prior.source_refs + (ref,))
    return tuple(records.values())


def active_wards(parsed: ParsedReplay, cutoff: float) -> tuple[WardInstance, ...]:
    return tuple(w for w in ward_instances(parsed, cutoff)
                 if w.placed_at is not None and w.removed_at is None
                 and w.status == "right_censored")


def render_ward_map(parsed: ParsedReplay | None) -> str:
    if parsed is None or not parsed.wards:
        return "<section id='wards'><h2>Варды</h2><p>События установки и удаления недоступны.</p></section>"
    times = [e.time for e in parsed.wards] + [f.time for f in parsed.frames]
    lo, hi = min(times), max(times)
    end = ward_instances(parsed, hi)
    rows = "".join(f"<tr><td>{w.entity_id}:{w.generation}</td><td>{html.escape(w.kind)}</td>"
                   f"<td>{w.placed_at if w.placed_at is not None else 'неизвестно'}</td>"
                   f"<td>{w.removed_at if w.removed_at is not None else 'не наблюдалось'}</td>"
                   f"<td>{w.observed_lifetime if w.observed_lifetime is not None else 'неизвестна'}</td>"
                   f"<td>{html.escape(w.status)}</td></tr>" for w in end)
    # Serialize projected lifecycle; no executable strings or HTML from inputs.
    projected_frames = [{"time": f.time, "units": [
        {"slot": u.slot, "x": u.x, "y": u.y} for u in f.units.values()]}
        for f in parsed.frames]
    ordered_events = sorted(enumerate(parsed.wards), key=lambda v: (
        v[1].time, v[1].sequence if v[1].sequence is not None else v[0]))
    data = json.dumps({"events": [asdict(e) for _, e in ordered_events], "frames": projected_frames},
                      ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    return f"""<section id='wards'><h2>Варды — ретроспективная схема</h2>
<p>Показаны наблюдения координат в replay. Геометрия карты, обзор, причина удаления и полезность не подтверждены.
Отсутствие удаления означает неизвестную длительность, а не живой вард после конца записи.</p>
<label for='ward-time'>Время, секунды</label> <output id='ward-clock'>{lo}</output>
<p><label><input type='checkbox' id='ward-show-world'> Показать позиции героев из полного replay (не видимость игрока)</label></p>
<input id='ward-time' type='range' min='{lo}' max='{hi}' value='{lo}' step='0.1' style='width:100%'>
<svg id='ward-map' viewBox='0 0 600 600' role='img' aria-label='Схема наблюдаемых координат вардов'
 style='max-width:600px;width:100%;background:#18242b;border:1px solid #435a68'>
<path d='M0 300H600M300 0V600' stroke='#435a68'/><g id='ward-points'></g><g id='hero-points'></g></svg>
<p id='ward-count' aria-live='polite'></p>
<details><summary>Lifecycle и цензурирование</summary><div style='overflow-x:auto'><table>
<thead><tr><th>Entity:generation</th><th>Тип</th><th>Установка</th><th>Удаление</th><th>Длительность</th><th>Статус</th></tr></thead><tbody>{rows}</tbody></table></div></details>
<script type='application/json' id='ward-data'>{data}</script>
<script>(()=>{{const payload=JSON.parse(document.getElementById('ward-data').textContent),
 slider=document.getElementById('ward-time'),points=document.getElementById('ward-points'),
 heroes=document.getElementById('hero-points'),world=document.getElementById('ward-show-world');
 const extent=16384; // Fixed schematic coordinate scale: future objects cannot shift the past.
 function draw(){{const t=Number(slider.value); document.getElementById('ward-clock').textContent=t.toFixed(1);
 points.replaceChildren();heroes.replaceChildren();const instances=new Map();
 for(const e of payload.events){{if(e.time>t)break;const key=e.id+':'+e.generation,prior=instances.get(key);
 if(e.op==='placed')instances.set(key,prior?{{...prior,conflict:true}}:{{...e,placed_at:e.time,removed:false,conflict:false}});
 else if(e.op==='gone')instances.set(key,prior?{{...prior,removed:true}}:{{...e,placed_at:null,removed:true,conflict:false}});}}
 const active=[...instances.values()].filter(w=>w.placed_at!==null&&!w.removed&&!w.conflict);
 for(const w of active){{if(!Number.isFinite(w.x)||!Number.isFinite(w.y))continue;
 const c=document.createElementNS('http://www.w3.org/2000/svg','circle');
 c.setAttribute('cx',300+w.x/extent*280); c.setAttribute('cy',300-w.y/extent*280);
 c.setAttribute('r',w.kind==='obs'?7:4);c.setAttribute('fill',w.team===2?'#71dab3':w.team===3?'#fa9986':'#c6c6c6');
 const title=document.createElementNS('http://www.w3.org/2000/svg','title');
 title.textContent=w.id+':'+w.generation+' '+w.kind+' @ '+w.placed_at+'s';c.appendChild(title);
 c.setAttribute('tabindex','0');c.setAttribute('role','button');c.setAttribute('aria-label','Разобрать задачу варда '+w.id+':'+w.generation);
 const select=()=>document.dispatchEvent(new CustomEvent('foresight:ward-selected',{{detail:{{entity_id:w.id,generation:w.generation}}}}));
 c.addEventListener('click',select);c.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();select();}}}});points.appendChild(c);}}
 if(world.checked){{const frame=payload.frames.filter(f=>f.time<=t).at(-1);
 if(frame&&t-frame.time<=1)for(const u of frame.units){{if(!Number.isFinite(u.x)||!Number.isFinite(u.y))continue;
 const label=document.createElementNS('http://www.w3.org/2000/svg','text');
 label.setAttribute('x',300+u.x/extent*280);label.setAttribute('y',300-u.y/extent*280);
 label.setAttribute('fill','#dae9ff');label.setAttribute('font-size','12');label.textContent=String(u.slot);heroes.appendChild(label);}}}}
 document.getElementById('ward-count').textContent='Наблюдаемых установок без удаления к этому времени: '+active.length;
 }} slider.addEventListener('input',draw);world.addEventListener('change',draw);draw();}})();</script></section>"""
