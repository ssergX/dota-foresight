"""User-selected practice and explicit journals over the existing local UI."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import html
import json

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.study_sources import estimate_role
from dota_coach.learning.training import TrainingGoal, TrainingScope, TASKS, assign_exercise
from dota_coach.profile import describe_series


def assignment_from_source(raw, account_id, task_code, statement, *, confirmation_id):
    if type(account_id) is not int or account_id<=0 or task_code not in TASKS or not isinstance(statement,str) or not 1<=len(statement.strip())<=2000:
        raise ValueError('Выберите задачу и явно сформулируйте собственную цель до 2000 символов.')
    players=[p for p in raw['players'] if p.get('account_id')==account_id]
    if len(players)!=1:
        raise ValueError('Аккаунт отсутствует или неоднозначен в источнике.')
    player=players[0]
    role=estimate_role(raw,player,'supplied-source').role
    groups=describe_series([raw],account_id)
    level=groups[0].opponent_level_proxy if groups else 'unknown'
    stamp=datetime.now(timezone.utc).isoformat()
    goal=TrainingGoal(content_hash((confirmation_id,account_id,task_code,statement,stamp)),task_code,statement.strip(),
        'user_confirmed',(confirmation_id,),stamp)
    scope=TrainingScope(f'account:{account_id}',player['hero_id'],role,'estimated' if role!='unknown' else 'unknown',
        f"opendota_patch_id:{raw['patch']}" if raw.get('patch') is not None else 'unknown',level)
    return assign_exercise(goal,scope)


def append_journal_surface(path, assignment, *, job_id, token):
    """No pre-filled user events, confirmations, match lists or progress values."""
    context=json.dumps({'assignment':asdict(assignment),'job_id':job_id,'token':token},ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    def period(code,title):
        return f"""<fieldset data-period='{code}'><legend>{title}</legend>
<label>Начало периода <input type='datetime-local' data-field='started_at'></label>
<label>Конец периода <input type='datetime-local' data-field='ended_at'></label>
<label>Все рассмотренные матчи (ID через запятую) <input type='text' data-field='match_ids' placeholder='ID реальных матчей'></label>
<p>Добавьте каждую подходящую ситуацию, включая невыполненное упражнение и неизвестный результат. Отдельно отметьте случаи, в которых выбора не было.</p>
<div data-rows></div><button type='button' data-add>Добавить ситуацию</button>
<label><input type='checkbox' data-field='complete'> Я перечислил все ситуации в указанных матчах по одному правилу учёта</label></fieldset>"""
    widget="""<section id='journal'><h2>Проверка в следующих матчах</h2><p>Это ваш журнал выполнения выбранного упражнения. Он не устанавливает правильность игровых решений или причинный эффект тренера. Не включайте один матч в оба периода.</p>"""+period('baseline','Базовый период')+period('followup','Следующая проверка')+"""<button type='button' id='compare-journals'>Проверить сопоставимость и сравнить</button> <button type='button' id='download-journals'>Скачать журналы</button><p id='journal-status' role='status' aria-live='polite'></p></section>"""
    script="""<script type='application/json' id='journal-context'>"""+context+"""</script><script>(()=>{
const ctx=JSON.parse(document.getElementById('journal-context').textContent),status=document.getElementById('journal-status'),draftKey='foresight.journal.draft.v1:'+ctx.assignment.assignment_id;
function addRow(box){const row=document.createElement('div');row.className='journal-row';
row.innerHTML='<label>Матч <input type="number" data-match min="1" step="1"></label><label>Время в матче, секунды (если известно) <input type="number" data-time step="0.1"></label><label>Ситуация <select data-eligible><option value="unknown">Недостаточно сведений</option><option value="eligible">Подходит для упражнения</option><option value="ineligible">Не было допустимого выбора</option></select></label><label>Упражнение <select data-behavior><option value="unknown">Неизвестно</option><option value="done">Выполнено</option><option value="not_done">Не выполнено</option></select></label><label>Заметка или ссылка на момент <input data-note maxlength="2000"></label><button type="button" data-remove>Удалить эту запись</button>';
row.querySelector('[data-remove]').onclick=()=>{row.remove();saveDraft();};box.querySelector('[data-rows]').append(row);return row;}
document.querySelectorAll('[data-period]').forEach(box=>box.querySelector('[data-add]').onclick=()=>{addRow(box);saveDraft();});
function saveDraft(){try{const data=[...document.querySelectorAll('[data-period]')].map(box=>({code:box.dataset.period,fields:[...box.querySelectorAll('[data-field]')].map(e=>({field:e.dataset.field,value:e.type==='checkbox'?e.checked:e.value})),rows:[...box.querySelectorAll('.journal-row')].map(row=>[...row.querySelectorAll('input,select')].map(e=>e.value))}));localStorage.setItem(draftKey,JSON.stringify(data));}catch(e){status.textContent='Браузер не сохранил черновик; скачайте журналы перед закрытием страницы.';}}
document.getElementById('journal').addEventListener('input',saveDraft);document.getElementById('journal').addEventListener('change',saveDraft);
try{const saved=JSON.parse(localStorage.getItem(draftKey)||'null');if(Array.isArray(saved)&&saved.length===2)for(const item of saved){const box=[...document.querySelectorAll('[data-period]')].find(e=>e.dataset.period===item.code);if(!box)continue;if(Array.isArray(item.fields))for(const f of item.fields){const el=[...box.querySelectorAll('[data-field]')].find(e=>e.dataset.field===f.field);if(el){if(el.type==='checkbox')el.checked=f.value===true;else if(typeof f.value==='string')el.value=f.value;}}if(Array.isArray(item.rows)&&item.rows.length<=500)for(const values of item.rows){if(!Array.isArray(values)||values.length!==5)continue;const row=addRow(box);[...row.querySelectorAll('input,select')].forEach((e,i)=>{if(typeof values[i]==='string')e.value=values[i];});}}}catch(e){status.textContent='Не удалось восстановить локальный черновик.';}
function readPeriod(box){const code=box.dataset.period,raw=box.querySelector('[data-field=match_ids]').value.trim();
if(!raw||!raw.split(',').every(v=>/^\\s*[1-9][0-9]*\\s*$/.test(v)))throw Error('Укажите ID всех рассмотренных матчей.');
const matches=raw.split(',').map(Number);if(matches.some(v=>!Number.isSafeInteger(v))||new Set(matches).size!==matches.length)throw Error('ID матчей должны быть различными положительными целыми.');
function date(key){const v=box.querySelector('[data-field='+key+']').value;if(!v)throw Error('Укажите начало и конец обоих периодов.');return new Date(v).toISOString();}
const rows=[...box.querySelectorAll('.journal-row')].map((row,i)=>{const mid=Number(row.querySelector('[data-match]').value),eligible=row.querySelector('[data-eligible]').value,behavior=row.querySelector('[data-behavior]').value;
if(!Number.isSafeInteger(mid)||!matches.includes(mid))throw Error('Каждая запись должна относиться к одному из указанных матчей.');
if(eligible!=='eligible'&&behavior!=='unknown')throw Error('Выполнение оценивается только в подходящей ситуации.');
const time=row.querySelector('[data-time]').value,seconds=time===''?null:Number(time);if(seconds!==null&&!Number.isFinite(seconds))throw Error('Время должно быть числом.');
return {opportunity_id:ctx.job_id+':'+code+':'+i,match_id:mid,assignment_id:ctx.assignment.assignment_id,eligibility:eligible,behavior_completed:behavior==='unknown'?null:behavior==='done',evidence_kind:'user_journal',evidence_refs:['user-journal:'+ctx.job_id+':'+code+':'+i],game_time_ms:seconds===null?null:Math.round(seconds*1000),reason_codes:eligible==='unknown'?['user_not_sure']:eligible==='ineligible'?['user_declared_no_choice']:[],note:row.querySelector('[data-note]').value};});
const complete=box.querySelector('[data-field=complete]').checked;
return {period_id:ctx.job_id+':'+code,assignment_id:ctx.assignment.assignment_id,scope:ctx.assignment.scope,started_at:date('started_at'),ended_at:date('ended_at'),match_ids:matches,opportunities:rows,coverage_status:complete?'user_journal_complete':'partial',coverage_refs:complete?['user-journal-coverage:'+ctx.job_id+':'+code]:[],coverage_policy:'all-submitted-match-opportunities.v1'};}
function journals(){return [...document.querySelectorAll('[data-period]')].map(readPeriod);}
document.getElementById('download-journals').onclick=()=>{try{const all=journals();all.forEach((v,i)=>{const url=URL.createObjectURL(new Blob([JSON.stringify(v,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=i?'followup.json':'baseline.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});status.textContent='Журналы экспортированы как собственные отметки.';}catch(e){status.textContent=e.message;}};
document.getElementById('compare-journals').onclick=async()=>{try{const [baseline,followup]=journals();status.textContent='Проверка периодов…';const response=await fetch('/api/training-progress',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':ctx.token},body:JSON.stringify({job_id:ctx.job_id,baseline,followup})});const result=await response.json();if(!response.ok)throw Error(result.error);const link=document.createElement('a');link.href=result.report_url;link.textContent='Открыть сравнение с проверкой знаменателей';status.replaceChildren(link);}catch(e){status.textContent=e.message;}};
})();</script>"""
    page=path.read_text(encoding='utf-8')
    styles="<style>fieldset{border:1px solid #496176;border-radius:12px;margin:24px 0;padding:18px}label{display:block;margin:10px 0}input,select,button{font:inherit;padding:7px;max-width:100%;box-sizing:border-box}input[type=text]{width:100%}.journal-row{padding:14px;margin:15px 0;background:#243a4b;border-radius:10px}</style>"
    page=page.replace('</head>',styles+'</head>').replace('</body>',widget+script+'</body>')
    path.write_text(page,encoding='utf-8')
