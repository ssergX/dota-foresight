"""Explicit user build hypotheses over report-bound episode anchors.

The current Valve catalog supplies descriptions, never historical affordability.
An offline report retains its form but cannot submit to a different server.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

from dota_coach.ingest.valve_catalog import ValveCatalogSnapshot
from dota_coach.learning.contextual import GOALS, GOAL_TEXT, THREATS


THREAT_TEXT = {
    "spell_damage": "Наблюдал урон заклинаний", "physical_attacks": "Наблюдал атаки",
    "control": "Наблюдал контроль", "gap_close": "Наблюдал сближение",
    "resource_pressure": "Наблюдал нехватку ресурса", "unknown": "Не указана",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")


def render_build_plan_form(report: dict, catalog: ValveCatalogSnapshot) -> str:
    """Render an empty form, retaining only identities from this report/catalog."""
    if not isinstance(report, dict) or not isinstance(catalog, ValveCatalogSnapshot):
        raise ValueError("typed report and Valve catalog required")
    from dota_coach.learning.build_planner import build_source_context
    notebook = report.get("notebook")
    if not isinstance(notebook, dict):
        raise ValueError("report notebook object required")
    rows = notebook.get("entries", [])
    if not isinstance(rows, list):
        raise ValueError("report entries must be a list")
    episodes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident, time = row.get("decision_id"), row.get("observation_time")
        if not isinstance(ident, str) or not ident or any(e["decision_id"] == ident for e in episodes):
            continue
        label = (f"{time / 60:.1f} мин" if type(time) in (int, float) and math.isfinite(time)
                 else "Время неизвестно")
        try:
            context = build_source_context(report, ident)
        except ValueError:
            # Legacy/noncanonical source anchors remain viewable in the report,
            # but cannot bind a new user planning declaration.
            continue
        episodes.append({"decision_id": ident, "label": label + " · " + ident,
                         "source_context_hash": context["source_context_hash"]})
    items = [{"item_id": item.internal_name, "label": item.label,
              "catalog_cost": item.item_cost, "description": item.description}
             for item in catalog.items if item.detail_status == "descriptor_available"]
    options = "<option value=''>Выберите эпизод отчёта</option>" + "".join(
        f"<option value='{html.escape(e['decision_id'], quote=True)}'>{html.escape(e['label'])}</option>"
        for e in episodes)
    goals = "<option value=''>Выберите собственную цель</option>" + "".join(
        f"<option value='{kind}'>{html.escape(GOAL_TEXT[kind])}</option>" for kind in sorted(GOALS - {"unknown"}))
    threats = "<option value='unknown'>Не указана</option>" + "".join(
        f"<option value='{kind}'>{THREAT_TEXT[kind]}</option>" for kind in sorted(THREATS - {"unknown"}))
    origin = ("Синтетический пример: эта форма не является историей пользователя."
              if report.get("dataset_kind") == "synthetic" else
              "Эпизоды публичного источника не устанавливают вашу личную цель или замеченную угрозу.")
    empty = "" if episodes else "<p>Нет эпизодов для привязки: сравнение недоступно.</p>"
    data = _json({"items": items, "episodes": episodes,
                  "episode_ids": [e["decision_id"] for e in episodes]})
    return f"""<section id='build-plan' class='card'><h2>Контекстный план покупки</h2>
<p>{origin} Сформулируйте план для следующего матча или ретроспективный вопрос. Он не доказывает намерение игрока в прошлом.</p>
<p>Каталог описывает текущие предметы Valve. Полная цена из каталога не равна оставшейся цене покупки и не устанавливает механику исторического патча.</p>{empty}
<form id='build-plan-form'><label>Эпизод <select name='decision_id' required>{options}</select></label>
<label>Цель <select name='goal_kind' required>{goals}</select></label>
<label>Что вы хотите обеспечить <textarea name='goal_description' maxlength='2000' required></textarea></label>
<label>Замеченная вами угроза (необязательно) <select name='threat_kind'>{threats}</select></label>
<label>Ваше наблюдение <textarea name='threat_description' maxlength='2000'></textarea></label>
<label>Доступное золото, если вы его знаете <input name='available_gold' type='number' min='0' step='any' inputmode='decimal'></label>
<label>Найти предмет <input id='build-item-search' type='search' placeholder='Название из каталога'></label>
<p>Выберите до шести предметов. Оставшуюся цену укажите только если она известна; пустое поле означает «неизвестно».</p>
<div id='build-item-list'></div><p id='build-selection-count' role='status'></p>
<div class='build-fields'><label>Свободный слот <select name='free_inventory_slot'><option value='unknown'>Неизвестно</option><option value='yes'>Есть</option><option value='no'>Нет</option></select></label>
<label>Доступ к покупке выбранных предметов <select name='purchase_available'><option value='unknown'>Неизвестно</option><option value='yes'>Есть</option><option value='no'>Нет</option></select></label></div>
<label><input name='confirmed' type='checkbox'> Это моя сформулированная цель и мои сведения; они ещё не проверены независимо</label>
<button type='submit' id='build-submit'>Сравнить условия покупки</button> <button type='button' id='build-download' disabled>Скачать результат JSON</button>
<p id='build-plan-status' role='status' aria-live='polite'></p></form><div id='build-plan-result' aria-live='polite'></div></section>
<style>#build-plan{{overflow-wrap:anywhere}}#build-plan label{{display:block;margin:12px 0}}#build-plan input,#build-plan select,#build-plan textarea{{font:inherit;max-width:100%;box-sizing:border-box}}#build-plan select,#build-plan textarea{{width:100%}}#build-plan textarea{{min-height:80px}}#build-item-list{{max-height:360px;overflow:auto}}.build-item{{border:1px solid #496176;border-radius:8px;padding:10px;margin:8px 0}}.build-fields{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:16px}}.build-option{{border-left:3px solid #94c9ff;padding:12px;margin:16px 0}}#build-plan button{{white-space:normal;max-width:100%;margin:6px 0}}</style>
<script type='application/json' id='build-plan-data'>{data}</script>""" + _SCRIPT


def attach_build_plan_submission(path: Path, job_id: str, token: str) -> None:
    """Bind a generated report to its local backend; no arbitrary endpoint URL."""
    if not isinstance(job_id, str) or not job_id.strip() or not isinstance(token, str) or not token.strip():
        raise ValueError("nonempty local job identity and token required")
    path = Path(path)
    page = path.read_text(encoding="utf-8")
    if "id='build-plan-form'" not in page or "</body>" not in page:
        raise ValueError("build form in a complete report required")
    if "id='build-plan-context'" in page:
        raise ValueError("build submission already attached")
    context = "<script type='application/json' id='build-plan-context'>" + _json({"job_id": job_id, "token": token}) + "</script>"
    path.write_text(page.replace("</body>", context + "</body>"), encoding="utf-8")


_SCRIPT = r"""<script>(()=>{function start(){
const form=document.getElementById('build-plan-form');if(!form)return;
const data=JSON.parse(document.getElementById('build-plan-data').textContent),context=document.getElementById('build-plan-context');
const ctx=context?JSON.parse(context.textContent):null,status=document.getElementById('build-plan-status'),resultBox=document.getElementById('build-plan-result'),list=document.getElementById('build-item-list');
const submit=document.getElementById('build-submit'),download=document.getElementById('build-download'),selected=new Map();let previousPlanId=null,lastResult=null,submitting=false,hydrated=false;
const supported=!!ctx&&location.protocol!=='file:'&&['127.0.0.1','localhost'].includes(location.hostname);
if(!supported){status.textContent='Локальный расчёт недоступен в этом статическом отчёте. Откройте отчёт через локальный интерфейс Foresight.';submit.disabled=true;}
if(!data.episode_ids.length||!data.items.length){submit.disabled=true;if(!data.items.length)status.textContent='В каталоге нет описаний предметов для сравнения.';}
function el(tag,text,parent){const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(parent)parent.append(node);return node;}
function count(){document.getElementById('build-selection-count').textContent='Выбрано: '+selected.size+' из 6';}
const rows=[];
for(const item of data.items){const box=el('div',undefined,list);box.className='build-item';const label=el('label',undefined,box),check=el('input',undefined,label);check.type='checkbox';check.dataset.item=item.item_id;label.append(document.createTextNode(' '+item.label));
el('p',item.catalog_cost===null?'Текущая цена каталога неизвестна':'Полная цена текущего каталога: '+item.catalog_cost+' (не остаток)',box);
if(item.description)el('p',item.description,box);const costLabel=el('label','Оставшаяся цена, если известна ',box),cost=el('input',undefined,costLabel);cost.type='number';cost.min='0';cost.step='any';cost.inputMode='decimal';cost.disabled=true;
check.onchange=()=>{if(check.checked&&selected.size>=6){check.checked=false;status.textContent='Можно сравнить до шести предметов.';return;}if(check.checked)selected.set(item.item_id,cost);else selected.delete(item.item_id);cost.disabled=!check.checked;count();};rows.push({box,text:(item.label+' '+item.item_id).toLocaleLowerCase()});}
count();document.getElementById('build-item-search').oninput=e=>{const query=e.target.value.trim().toLocaleLowerCase();rows.forEach(row=>row.box.hidden=!row.text.includes(query));};
function amount(input){if(input.value.trim()==='')return null;const v=Number(input.value);if(!Number.isFinite(v)||v<0)throw Error('Золото и оставшаяся цена должны быть неотрицательными числами.');return v;}
function tri(name){const value=form.elements.namedItem(name).value;return value==='unknown'?null:value==='yes';}
function request(){const fields=form.elements,decision=fields.namedItem('decision_id').value,goal=fields.namedItem('goal_kind').value,description=fields.namedItem('goal_description').value.trim();
if(!data.episode_ids.includes(decision))throw Error('Выберите эпизод из этого отчёта.');if(!goal||!description)throw Error('Выберите цель и опишите её своими словами.');if(!fields.namedItem('confirmed').checked)throw Error('Подтвердите собственную формулировку цели и сведения.');if(!selected.size)throw Error('Выберите хотя бы один предмет.');
const remaining={};selected.forEach((input,id)=>remaining[id]=amount(input));return {schema_version:'foresight.build-plan-request.v1',decision_id:decision,source_context_hash:data.episodes.find(row=>row.decision_id===decision).source_context_hash,goal_kind:goal,goal_description:description,threat_kind:fields.namedItem('threat_kind').value,threat_description:fields.namedItem('threat_description').value.trim()||null,available_gold:amount(fields.namedItem('available_gold')),candidate_item_ids:[...selected.keys()],remaining_costs:remaining,free_inventory_slot:tri('free_inventory_slot'),purchase_available:tri('purchase_available'),confirmed:true,previous_plan_id:previousPlanId};}
function strings(parent,title,values){if(!Array.isArray(values)||!values.length)return;el('h4',title,parent);const ul=el('ul',undefined,parent);values.forEach(value=>el('li',typeof value==='string'?value:JSON.stringify(value),ul));}
function sourceURL(value){try{const url=new URL(value);return url.protocol==='https:'&&['www.dota2.com','dota2.com'].includes(url.hostname)&&!url.username&&!url.password&&(!url.port||url.port==='443')?url.href:null;}catch(e){return null;}}
function render(plan){resultBox.replaceChildren();el('h3','Редакция '+plan.revision,resultBox);const anchor=data.episodes.find(row=>row.decision_id===plan.source_binding?.decision_id);el('p','Эпизод: '+(anchor?.label||plan.source_binding?.decision_id||'неизвестен'),resultBox);el('p',plan.goal?.description||'Цель не указана',resultBox);el('p','Сведения пользователя не проверены независимо. Это исследовательский план; оптимальность не установлена.',resultBox);
if(plan.revision>1)el('p','Сценарии планирования в разных контекстах; изменение не измеряет улучшение поведения.',resultBox);
const scopeText={scenario_planning_not_behavior_progress:'Сценарии планирования; изменение не измеряет улучшение поведения',same_source_prefix:'Один и тот же префикс источника',different_source_prefix:'Разные префиксы источника',same_context:'Один контекст наблюдения',different_context:'Разные контексты наблюдения',same_anchor:'Один эпизод',different_anchor:'Разные эпизоды'};
if(plan.comparison_scope)el('p','Область сравнения: '+(scopeText[plan.comparison_scope]||'сопоставление гипотез планирования'),resultBox);
if(plan.revision_reason)el('p','Причина редакции: '+(plan.revision_reason==='initial_planning_request'?'первый сформулированный план':plan.revision_reason==='context_or_goal_changed'?'изменён контекст или цель':plan.revision_reason==='goal_or_declarations_changed'?'изменена цель или заявленные сведения':plan.revision_reason==='different_anchor'?'выбран другой эпизод':'обновлён сценарий планирования'),resultBox);
for(const option of plan.options||[]){const card=el('article',undefined,resultBox);card.className='build-option';el('h3',option.label||option.item_id||'Вариант',card);el('p',option.goal_condition||'',card);el('p',option.description||'',card);
el('p','Оставшаяся цена: '+(option.declared_remaining_cost??'неизвестно')+' · золото после покупки: '+(option.budget_after??'неизвестно')+' · доступность покупки и применения: не установлена',card);
const budgetText={affordable_by_declaration:'По указанным вами числам золота хватает. Компоненты, доставка и слот не проверены.',budget_shortfall_by_declaration:'По указанным вами числам золота не хватает.',unknown:'Достаточность золота неизвестна: укажите доступное золото и оставшуюся цену.'};el('p',budgetText[option.affordability]||budgetText.unknown,card);
strings(card,'Возможные преимущества',option.advantages);strings(card,'Цена и ограничения',option.tradeoffs);strings(card,'Когда пересмотреть',option.revisit_conditions);
for(const raw of option.source_urls||[]){const url=sourceURL(raw);if(url){const a=el('a','Источник Valve',card);a.href=url;a.target='_blank';a.rel='noopener noreferrer';el('span',' ',card);}}}
if(Array.isArray(plan.comparisons)&&plan.comparisons.length){el('h4','Сравнение заявленных расходов',resultBox);const ul=el('ul',undefined,resultBox);for(const pair of plan.comparisons){const label=id=>(plan.options||[]).find(item=>item.item_id===id)?.label||id;el('li',label(pair.first_item_id)+' − '+label(pair.second_item_id)+': '+(pair.first_minus_second_declared_cost??'неизвестно')+' золота. Разница полезности не установлена; ранжирования нет.',ul);}}
strings(resultBox,'Изменения плана',plan.deltas);strings(resultBox,'Следующая проверка',plan.research_questions);}
form.onsubmit=async e=>{e.preventDefault();if(!supported){status.textContent='Требуется локальный интерфейс Foresight.';return;}if(submitting||!hydrated)return;try{const payload=request();submitting=true;submit.disabled=true;status.textContent='Проверяем привязку и сравниваем условия…';const response=await fetch('/api/build-plan',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':ctx.token},body:JSON.stringify({job_id:ctx.job_id,request:payload})});const value=await response.json();if(!response.ok)throw Error(value.error||'Не удалось проверить план.');const plan=value.plan||value;if(typeof plan.plan_id!=='string')throw Error('Ответ не содержит идентификатора плана.');lastResult=plan;previousPlanId=plan.plan_id;render(plan);download.disabled=false;status.textContent='План сохранён как ваша гипотеза; сравнение не является игровым вердиктом.';}catch(error){status.textContent=error.message;}finally{submitting=false;submit.disabled=!supported||!data.episode_ids.length||!data.items.length;}};
download.onclick=()=>{if(!lastResult)return;const url=URL.createObjectURL(new Blob([JSON.stringify(lastResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='build-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
if(supported){submit.disabled=true;status.textContent='Загружаем сохранённую редакцию…';fetch('/api/build-plan/'+encodeURIComponent(ctx.job_id),{headers:{'X-Foresight-Token':ctx.token}}).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error||'Не удалось загрузить текущий план.');if(value.latest_plan){lastResult=value.latest_plan;previousPlanId=lastResult.plan_id;render(lastResult);download.disabled=false;status.textContent='Сохранена редакция '+lastResult.revision+'. Для изменения сформулируйте и подтвердите новую цель.';}else status.textContent='Сохранённого плана ещё нет. Заполните собственную цель.';hydrated=true;submit.disabled=!data.episode_ids.length||!data.items.length;}).catch(error=>{status.textContent=error.message+' Обновите страницу перед изменением плана.';});}
}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();})();</script>"""
