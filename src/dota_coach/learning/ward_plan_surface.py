"""A ward task beside the retrospective map, with explicit unknown evidence."""
from __future__ import annotations
import html
import json
from pathlib import Path
from dota_coach.learning.ward_plan import GOALS, ward_source_context, validate_ward_observations


def _json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')


def render_ward_plan_form(source: dict) -> str:
    validate_ward_observations(source)
    choices=[]
    for e in source['events']:
        if e['operation']!='placed' or e['team'] not in (source['subject_team'],None):
            continue
        try:
            context=ward_source_context(source,e['ward_id'])
        except ValueError:
            continue
        choices.append({'ward_id':e['ward_id'],'entity_id':e['entity_id'],'generation':e['generation'],
            'source_context_hash':context['source_context_hash'],
            'label':f"{e['kind']} {e['entity_id']}:{e['generation']} · "+(f"{e['game_time']/60:.1f} мин" if e['game_time'] is not None else 'время неизвестно')+(' · команда неизвестна' if e['team'] is None else '')})
    options="<option value=''>Выберите наблюдаемую постановку</option>"+''.join(
        f"<option value='{html.escape(e['ward_id'],quote=True)}'>{html.escape(e['label'])}</option>" for e in choices)
    goals="<option value=''>Выберите задачу</option>"+''.join(f"<option value='{k}'>{v}</option>" for k,v in GOALS.items())
    unavailable='' if choices else '<p>Нет подходящей постановки с привязкой к команде выбранного аккаунта. Это не отсутствие вардов в игре.</p>'
    return f"""<section id='ward-plan' class='card'><h2>Задача варда и условия проверки</h2>
<p>Выберите постановку для разбора командной задачи. Принадлежность варда команде может быть неизвестна. Кто поставил вард и что игрок заметил, пока не установлено. Цель ниже — ваш текущий план или вопрос к записи.</p>{unavailable}
<form id='ward-plan-form'><label>Наблюдаемая постановка <select name='ward_id' required>{options}</select></label>
<label>Задача <select name='goal_kind' required>{goals}</select></label>
<label>Для какого действия нужны сведения <textarea name='goal_description' maxlength='2000' required></textarea></label>
<details><summary>Предложить альтернативу для проверки</summary><label>Название альтернативы <input name='alternative_label' maxlength='200'></label>
<label>Почему её стоит сравнить <textarea name='alternative_rationale' maxlength='2000'></textarea></label>
<p>Координаты — необязательная непроверенная гипотеза в системе replay; они не доказывают доступность или безопасность точки.</p>
<label>Координата X <input name='alternative_x' type='number' step='any'></label><label>Координата Y <input name='alternative_y' type='number' step='any'></label></details>
<label><input name='confirmed' type='checkbox'> Подтверждаю собственную формулировку; она не устанавливает цель прошлой постановки</label>
<button id='ward-plan-submit' type='submit'>Разобрать условия обзора</button> <button id='ward-plan-download' type='button' disabled>Скачать план JSON</button>
<p id='ward-plan-status' role='status' aria-live='polite'></p></form><div id='ward-plan-result' aria-live='polite'></div></section>
<style>#ward-plan{{overflow-wrap:anywhere}}#ward-plan label{{display:block;margin:12px 0}}#ward-plan input:not([type=checkbox]),#ward-plan select,#ward-plan textarea{{box-sizing:border-box;font:inherit;max-width:100%;width:100%}}#ward-plan button{{max-width:100%;white-space:normal;margin:6px 0}}</style>
<script type='application/json' id='ward-plan-data'>{_json(choices)}</script>"""+_SCRIPT


def attach_ward_plan_submission(path: Path, *, job_id: str, token: str) -> None:
    if type(job_id) is not str or not job_id or type(token) is not str or not token:
        raise ValueError('local ward job and token required')
    path=Path(path);page=path.read_text(encoding='utf-8')
    if "id='ward-plan-form'" not in page or '</body>' not in page or "id='ward-plan-context'" in page:
        raise ValueError('complete unattached ward form required')
    context="<script type='application/json' id='ward-plan-context'>"+_json({'job_id':job_id,'token':token})+'</script>'
    path.write_text(page.replace('</body>',context+'</body>'),encoding='utf-8')


_SCRIPT=r"""<script>(()=>{function start(){
const form=document.getElementById('ward-plan-form');if(!form)return;
const choices=JSON.parse(document.getElementById('ward-plan-data').textContent),context=document.getElementById('ward-plan-context'),ctx=context?JSON.parse(context.textContent):null;
const message=document.getElementById('ward-plan-status'),result=document.getElementById('ward-plan-result'),submit=document.getElementById('ward-plan-submit'),download=document.getElementById('ward-plan-download');
let last=null,busy=false,hydrated=false;const supported=!!ctx&&['127.0.0.1','localhost'].includes(location.hostname)&&location.protocol!=='file:';
function el(tag,text,parent){const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(parent)parent.append(node);return node;}
function render(plan){result.replaceChildren();el('h3','Редакция '+plan.revision+' · '+(choices.find(e=>e.ward_id===plan.placement_anchor.ward_id)?.label||'выбранная постановка'),result);el('p',plan.declaration_receipt.goal_description,result);
el('p','Полезность обзора и доступность действий не установлены. Изменение плана не измеряет прогресс поведения.',result);const detail=el('details',undefined,result);el('summary','Задача, доказательства и неизвестные условия',detail);
for(const check of plan.checks){el('h4',check.title,detail);el('p',check.status==='current_user_hypothesis'?'Ваша текущая гипотеза':'Неизвестно; требуется проверка',detail);el('p',check.question,detail);}
el('p','Ранее наблюдённые объекты команды выбранного аккаунта: '+plan.preceding_same_team_objects.length+'. Эти записи не доказывают активный обзор или дублирование.',detail);
if(plan.task_analysis){const data=plan.task_analysis.callback_analysis;el('h4','Что вычислено из источника',detail);el('p','Записей команды в срезе постановки: '+data.callback_count+'. Из них с собственным временем: '+data.known_prefix_clock_callbacks+', без времени: '+data.unknown_prefix_clock_callbacks+'. Конфликтов жизненного цикла: '+data.conflict_source_refs.length+'.',detail);el('p','Сравнено координат с предшествующими объектами: '+data.coordinate_comparisons.length+'. Равенство координат не устанавливает дублирование обзора.',detail);el('p','Сопоставлений с предложенными альтернативами: '+plan.task_analysis.pairwise_alternatives.length+'. Полезность и ранжирование не установлены.',detail);}
for(const alternative of plan.proposed_alternatives){el('h4',alternative.label,detail);el('p',alternative.rationale+' Доступность и безопасность неизвестны.',detail);}const ul=el('ul',undefined,detail);plan.limitations.forEach(text=>el('li',text,ul));}
function number(name){const text=form.elements.namedItem(name).value.trim();if(!text)return null;const value=Number(text);if(!Number.isFinite(value)||Math.abs(value)>Number.MAX_SAFE_INTEGER)throw Error('Введите конечные координаты или оставьте обе пустыми.');return value;}
function request(){const f=form.elements,ward=choices.find(e=>e.ward_id===f.namedItem('ward_id').value);if(!ward)throw Error('Выберите постановку из этого отчёта.');if(!f.namedItem('confirmed').checked)throw Error('Подтвердите свою формулировку задачи.');
const goal=f.namedItem('goal_kind').value,description=f.namedItem('goal_description').value.trim();if(!goal||!description)throw Error('Выберите задачу и назовите действие команды.');
const label=f.namedItem('alternative_label').value.trim(),rationale=f.namedItem('alternative_rationale').value.trim(),x=number('alternative_x'),y=number('alternative_y'),alternatives=[];
if(label||rationale||x!==null||y!==null){if(!label||!rationale||(x===null)!==(y===null))throw Error('Для альтернативы нужны название, обоснование и обе координаты либо ни одной.');alternatives.push({label,rationale,x,y});}
return {schema_version:'foresight.ward-plan-request.v1',ward_id:ward.ward_id,source_context_hash:ward.source_context_hash,goal_kind:goal,goal_description:description,confirmed:true,alternatives,previous_plan_id:last?.plan_id??null};}
form.elements.namedItem('ward_id').onchange=()=>{form.elements.namedItem('confirmed').checked=false;};
document.addEventListener('foresight:ward-selected',event=>{const e=choices.find(e=>e.entity_id===event.detail.entity_id&&e.generation===event.detail.generation);if(!e)return;form.elements.namedItem('ward_id').value=e.ward_id;form.elements.namedItem('confirmed').checked=false;document.getElementById('ward-plan').scrollIntoView();});
form.onsubmit=async event=>{event.preventDefault();if(!supported||!hydrated||busy)return;try{const payload=request();busy=true;submit.disabled=true;message.textContent='Проверяем источник и условия…';const response=await fetch('/api/ward-plan',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':ctx.token},body:JSON.stringify({job_id:ctx.job_id,request:payload})});const value=await response.json();if(!response.ok)throw Error(value.error||'Не удалось сохранить план.');last=value;render(last);download.disabled=false;message.textContent='План сохранён как гипотеза для проверки.';}catch(error){message.textContent=error.message;}finally{busy=false;submit.disabled=!supported||!choices.length;}};
download.onclick=()=>{if(!last)return;const url=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='ward-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
submit.disabled=true;if(!choices.length){message.textContent='Нет привязанной постановки для этого аккаунта.';}else if(!supported){message.textContent='Расчёт требует локального интерфейса Foresight; статический отчёт сохраняет наблюдения.';}else fetch('/api/ward-plan/'+encodeURIComponent(ctx.job_id)).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error||'Не удалось получить сохранённый план.');last=value.latest_plan;if(last){render(last);download.disabled=false;message.textContent='Сохранена редакция '+last.revision+'. Для изменения подтвердите новую задачу.';}else message.textContent='Сформулируйте задачу самостоятельно.';hydrated=true;submit.disabled=false;}).catch(error=>message.textContent=error.message+' Обновите страницу.');
}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();})();</script>"""
