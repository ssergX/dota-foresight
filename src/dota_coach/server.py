"""Loopback-only workbench over configured local artifacts, with explicit jobs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from dota_coach.decisions.batch import strict_json
from dota_coach.ingest.trace import load_trace_result
from dota_coach.ingest.valve_catalog import load_valve_snapshot
from dota_coach.live_report import render_live_report

PAGE="""<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='icon' href='data:,'><title>Foresight — рабочая область</title>
<style>body{font:17px system-ui;max-width:920px;margin:45px auto;padding:0 20px;background:#101922;color:#e7eff8}h1{font-size:36px}.panel{padding:24px;margin:25px 0;border:1px solid #456078;border-radius:14px;background:#1a2c3a}button,select{font:inherit;background:#284e6c;color:white;padding:12px;border:1px solid #6c8ba2;border-radius:8px}label{display:block;margin:12px 0}a{color:#a0d3ff}button:disabled{opacity:.5}#status{min-height:30px}#error{color:#ffc6b3}details{margin:20px 0}</style>
<h1>Foresight</h1><p>Replay → наблюдения → проверяемый разбор</p><div class='panel'><h2>Локальный матч __MATCH__</h2><p>Открыт источник публичного матча. Выбранный аккаунт задаёт игрока разбора и не означает, что это ваша история.</p>
<label for='account'>Игрок</label><select id='account'>__OPTIONS__</select><p><button id='run'>Создать отчёт</button></p><p id='status' role='status' aria-live='polite'>Готов к анализу сохранённого replay.</p><p id='error' role='alert'></p><div id='result'></div></div>
<section class='panel'><h2>Выбрать упражнение</h2><p>Вы сами выбираете задачу для следующих матчей. Это не подтверждение ошибки выбранного игрока.</p>
<label for='task'>Что проверять</label><select id='task'><option value='choice_alternatives'>Цель и альтернативы</option><option value='fight_entry'>Подключение к драке</option><option value='defensive_item_plan'>План защитных предметов</option><option value='vision_plan'>Задача варда</option></select>
<label for='goal'>Моя цель</label><textarea id='goal' maxlength='2000' rows='3' style='width:100%;box-sizing:border-box;font:inherit'></textarea>
<label><input type='checkbox' id='confirm-goal'> Я выбираю это упражнение для себя и подтверждаю указанную цель</label><button id='train'>Создать упражнение и журнал</button><p id='training-status' role='status' aria-live='polite'></p><div id='training-result'></div></section>
<details><summary>Охват и качество</summary><p>В интерфейсе доступны наблюдаемые защитные активации, доказательства, альтернативы для проверки, схема вардов, покупки и уточнение цели. Извлечение ещё не сверено в клиенте, критерий не проверен экспертами. Отказ от оценки не означает «ошибок нет».</p><p>При отсутствии истории привычки не диагностируются. Отсутствие учебных рекомендаций отображается отдельно.</p></details>
<script>const token=__TOKEN__,run=document.getElementById('run'),status=document.getElementById('status'),err=document.getElementById('error'),result=document.getElementById('result');let busy=false;
async function poll(id){const response=await fetch('/api/jobs/'+id,{cache:'no-store'});if(!response.ok)throw Error('Не удалось получить состояние задачи');const job=await response.json();status.textContent=job.message;
if(job.state==='error')throw Error(job.error);if(job.state==='complete'){const a=document.createElement('a');a.href=job.report_url;a.textContent='Открыть готовый разбор';result.replaceChildren(a);run.disabled=false;busy=false;return;}setTimeout(()=>poll(id).catch(fail),600);}
function fail(e){err.textContent=e.message;status.textContent='Анализ не завершён';busy=false;run.disabled=false;}
run.addEventListener('click',async()=>{if(busy)return;busy=true;run.disabled=true;err.textContent='';result.replaceChildren();status.textContent='Постановка в очередь…';try{const r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':token},body:JSON.stringify({account_id:Number(document.getElementById('account').value)})});const job=await r.json();if(!r.ok)throw Error(job.error);poll(job.job_id).catch(fail);}catch(e){fail(e);}});
document.getElementById('train').onclick=async()=>{const button=document.getElementById('train'),msg=document.getElementById('training-status'),box=document.getElementById('training-result');button.disabled=true;box.replaceChildren();try{if(!document.getElementById('confirm-goal').checked)throw Error('Подтвердите собственную цель перед назначением упражнения.');const r=await fetch('/api/training',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':token},body:JSON.stringify({account_id:Number(document.getElementById('account').value),task_code:document.getElementById('task').value,statement:document.getElementById('goal').value,confirmed:true})});const job=await r.json();if(!r.ok)throw Error(job.error);msg.textContent='Подбор упражнения и существующих учебных примеров…';async function wait(){const response=await fetch('/api/jobs/'+job.job_id,{cache:'no-store'});if(!response.ok)throw Error('Не удалось получить состояние упражнения');const result=await response.json();if(result.state==='error')throw Error(result.error);if(result.state==='complete'){const a=document.createElement('a');a.href=result.report_url;a.textContent='Открыть упражнение и журнал следующих матчей';box.replaceChildren(a);msg.textContent=result.message;button.disabled=false;}else setTimeout(()=>wait().catch(failTraining),600);}function failTraining(e){msg.textContent=e.message;button.disabled=false;}await wait();}catch(e){msg.textContent=e.message;button.disabled=false;}};</script></html>"""


class Workbench:
    def __init__(self, match_json, extraction_json, catalog_json, out_dir, *, study_json=None, catalog_raw_dir=None,action_states_json=None,combat_names_jsonl=None,
                 orders_jsonl=None,constraint_source_jsonl=None,event_visibility_jsonl=None,
                 command_binding_jsonl=None,projectiles_jsonl=None,unit_control_trace=None,movement_input_json=None,defensive_impact_json=None,
                 impact_prefix_json=None,terrain_input_json=None,history_input_json=None,analytical_review_provider=None,video_path=None,video_offset=None,ffmpeg=None):
        from dota_coach.video.trace_clips import validate_video_options
        validate_video_options(video_path,video_offset)
        self.video_path=video_path
        self.video_offset=video_offset
        self.ffmpeg=ffmpeg
        self.match_path,self.extraction_path,self.catalog_path=map(Path,(match_json,extraction_json,catalog_json))
        self.out=Path(out_dir).resolve()
        self.study_path=Path(study_json) if study_json else None
        self.catalog_raw_dir=catalog_raw_dir
        self.action_states_path=Path(action_states_json) if action_states_json else None
        self.combat_names_path=Path(combat_names_jsonl) if combat_names_jsonl else None
        self.orders_path=Path(orders_jsonl) if orders_jsonl else None
        self.constraint_source_path=Path(constraint_source_jsonl) if constraint_source_jsonl else None
        self.event_visibility_path=Path(event_visibility_jsonl) if event_visibility_jsonl else None
        self.unit_control_trace_path=Path(unit_control_trace) if unit_control_trace else None
        self.projectiles_path=Path(projectiles_jsonl) if projectiles_jsonl else None
        self.command_binding_path=Path(command_binding_jsonl) if command_binding_jsonl else None
        self.movement_input_path=Path(movement_input_json) if movement_input_json else None
        self.defensive_impact_path=Path(defensive_impact_json) if defensive_impact_json else None
        self.impact_prefix_path=Path(impact_prefix_json) if impact_prefix_json else None
        self.terrain_input_path=Path(terrain_input_json) if terrain_input_json else None
        self.history_input_path=Path(history_input_json) if history_input_json else None
        if analytical_review_provider is not None and not callable(analytical_review_provider):
            raise TypeError("backend review provider must be callable; portable registries forbidden")
        self.analytical_review_provider=analytical_review_provider
        self.analytical_witnesses={}
        self.raw=strict_json(self.match_path.read_text(encoding='utf-8-sig'))
        if (not isinstance(self.raw,dict) or type(self.raw.get('match_id')) is not int
                or self.raw['match_id']<=0 or not isinstance(self.raw.get('players'),list)
                or not self.raw['players']):
            raise ValueError('Источник требует положительный match_id и непустой список игроков.')
        for player in self.raw['players']:
            if (not isinstance(player,dict) or type(player.get('hero_id')) is not int
                    or player['hero_id']<=0 or type(player.get('player_slot')) is not int
                    or player['player_slot'] not in (*range(5),*range(128,133))):
                raise ValueError('Источник содержит некорректные hero_id или player_slot.')
            if player.get('account_id') is not None and (type(player['account_id']) is not int or player['account_id']<0):
                raise ValueError('account_id должен быть числом или null.')
            if player.get('personaname') is not None and not isinstance(player['personaname'],str):
                raise ValueError('Имя игрока должно быть строкой или null.')
        if len({p['player_slot'] for p in self.raw['players']})!=len(self.raw['players']):
            raise ValueError('Источник содержит повторяющиеся player_slot.')
        self.accounts={p['account_id'] for p in self.raw['players'] if type(p.get('account_id')) is int and p['account_id']>0}
        known_accounts=[p['account_id'] for p in self.raw['players'] if type(p.get('account_id')) is int and p['account_id']>0]
        if not self.accounts or len(self.accounts)!=len(known_accounts):
            raise ValueError('Источник требует хотя бы один однозначно связанный аккаунт.')
        self.token=secrets.token_urlsafe(32)
        self.jobs={}
        self.assignments={}
        self.training_selections={}
        self.latest_build_plans={}
        self.latest_ward_plans={}
        self.lock=threading.Lock()
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='foresight')

    def page(self):
        options=''.join(f"<option value='{p['account_id']}'>{html.escape(p.get('personaname') or str(p['account_id']))} · hero {html.escape(str(p['hero_id']))}</option>" for p in self.raw['players'] if p.get('account_id') in self.accounts)
        return PAGE.replace('__MATCH__',html.escape(str(self.raw['match_id']))).replace('__OPTIONS__',options).replace('__TOKEN__',json.dumps(self.token))

    def submit(self,account):
        if type(account) is not int or account not in self.accounts:
            raise ValueError('Указанный аккаунт отсутствует в сохранённом матче.')
        with self.lock:
            if any(j['state'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('Сначала дождитесь текущего анализа.')
            if len(self.jobs)>=50:
                raise ValueError('Достигнут лимит задач этой сессии; перезапустите рабочую область.')
            ident=secrets.token_hex(12)
            self.jobs[ident]={'job_id':ident,'state':'queued','message':'Задача в очереди.'}
        self.worker.submit(self._run,ident,account)
        return ident

    def _update(self,ident,**values):
        with self.lock:
            self.jobs[ident].update(values)

    def submit_training(self,account,task_code,statement,confirmed):
        if confirmed is not True or type(account) is not int or account not in self.accounts:
            raise ValueError('Нужны явное подтверждение цели и аккаунт из выбранного матча.')
        from dota_coach.learning.training_surface import assignment_from_source
        ident=secrets.token_hex(12)
        assignment=assignment_from_source(self.raw,account,task_code,statement,confirmation_id='local-user-goal:'+ident)
        with self.lock:
            if len(self.jobs)>=50 or any(j['state'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('Дождитесь текущей задачи; лимит сессии — 50 задач.')
            self.assignments[ident]=assignment
            self.jobs[ident]={'job_id':ident,'state':'queued','message':'Упражнение в очереди.'}
        self.worker.submit(self._run_training,ident,account)
        return ident

    def _run_training(self,ident,account):
        try:
            from dota_coach.learning.training import match_study_to_goal,write_training_report
            from dota_coach.learning.training_surface import append_journal_surface
            self._update(ident,state='running',message='Проверка источников учебных примеров…')
            selection=None
            assignment=self.assignments[ident]
            if self.study_path:
                from dota_coach.ingest.study_sources import load_study_discovery
                selection=match_study_to_goal(assignment.goal,self.raw,account_id=account,discovery=load_study_discovery(self.study_path))
            write_training_report(assignment,self.out/ident,selection=selection)
            append_journal_surface(self.out/ident/'index.html',assignment,job_id=ident,token=self.token)
            with self.lock:
                self.training_selections[ident]=selection
            self._update(ident,state='complete',message='Упражнение назначено по вашей цели. Выполнение ещё не измерено.',report_url=f'/reports/{ident}/index.html')
        except Exception as exc:
            self._update(ident,state='error',message='Упражнение не создано.',error=str(exc))

    def compare_training(self,ident,baseline_raw,followup_raw):
        from dota_coach.learning.training import load_training_period,write_training_report
        with self.lock:
            if ident not in self.assignments or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте упражнение в этой сессии.')
            if len(self.jobs)>=50 or any(j['state'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('Дождитесь текущей задачи; лимит сессии — 50 задач.')
            assignment=self.assignments[ident];selection=self.training_selections[ident]
            report_id=secrets.token_hex(12)
            self.jobs[report_id]={'job_id':report_id,'state':'running','message':'Проверка периодов.'}
        try:
            baseline=load_training_period(json.dumps(baseline_raw,allow_nan=False))
            followup=load_training_period(json.dumps(followup_raw,allow_nan=False))
            payload=write_training_report(assignment,self.out/report_id,baseline=baseline,followup=followup,selection=selection)
            self._update(report_id,state='complete',message='Периоды проверены; изменение качества решений не установлено.',report_url=f'/reports/{report_id}/index.html')
            return {'job_id':report_id,'report_url':f'/reports/{report_id}/index.html','progress':payload['progress']}
        except Exception as exc:
            self._update(report_id,state='error',message='Журналы не приняты.',error=str(exc))
            raise

    def _run(self,ident,account):
        try:
            self._update(ident,state='running',message='Проверка хешей извлечения и источников…')
            result=load_trace_result(self.extraction_path)
            catalog=load_valve_snapshot(self.catalog_path,raw_dir=self.catalog_raw_dir)
            discovery=None
            if self.study_path:
                from dota_coach.ingest.study_sources import load_study_discovery
                discovery=load_study_discovery(self.study_path)
            self._update(ident,message='Формирование собственных наблюдений, карты и карточек…')
            states=None
            if self.action_states_path:
                from dota_coach.ingest.action_state import load_action_states
                candidate=load_action_states(self.action_states_path,extraction=result)
                if candidate.get('account_id_verified_by_resource')==account:
                    states=candidate
            payload=render_live_report(result,self.raw,account_id=account,catalog=catalog,out_dir=self.out/ident,discovery=discovery,action_states=states,combat_names_path=self.combat_names_path,
                orders_path=self.orders_path,constraint_source_path=self.constraint_source_path,event_visibility_path=self.event_visibility_path,
                command_binding_path=self.command_binding_path,projectiles_path=self.projectiles_path,unit_control_trace_path=self.unit_control_trace_path,movement_input_path=self.movement_input_path,
                defensive_impact_path=self.defensive_impact_path,impact_prefix_path=self.impact_prefix_path,
                terrain_input_path=self.terrain_input_path,history_input_path=self.history_input_path,
                video_path=self.video_path,video_offset=self.video_offset,ffmpeg=self.ffmpeg,
                analytical_review=self.current_analytical_review(account),
                witness_sink=lambda workflow,history:self.analytical_witnesses.update({ident:(account,workflow,history)}))
            from dota_coach.analytical_bundle import attach_current_review_status
            attach_current_review_status(self.out/ident/"index.html",job_id=ident)
            from dota_coach.learning.resource_plan import attach_resource_plan_submission
            attach_resource_plan_submission(self.out/ident/'index.html',job_id=ident,token=self.token)
            from dota_coach.semantic_surface import attach_semantic_submission
            attach_semantic_submission(self.out/ident/'index.html',job_id=ident,token=self.token)
            from dota_coach.learning.build_plan_surface import attach_build_plan_submission
            attach_build_plan_submission(self.out/ident/'index.html',job_id=ident,token=self.token)
            from dota_coach.learning.ward_plan_surface import attach_ward_plan_submission
            attach_ward_plan_submission(self.out/ident/'index.html',job_id=ident,token=self.token)
            from dota_coach.validation.review_workspace import write_review_workspace
            write_review_workspace(self.out/ident/'independent-review',submit_url=f'/api/review/{ident}',submit_token=self.token)
            n=payload['notebook']['activation_candidates']
            self._update(ident,state='complete',message=f'Отчёт готов: {n} активаций для разбора. Проверенных вердиктов: 0.',report_url=f'/reports/{ident}/index.html')
        except Exception as exc:
            self._update(ident,state='error',message='Источник неполон или не прошёл проверку.',error=str(exc))

    def current_analytical_review(self,account):
        from dota_coach.analytical_workflow import AnalyticsReviewContext
        context=None if self.analytical_review_provider is None else self.analytical_review_provider(account)
        if context is not None and not isinstance(context,AnalyticsReviewContext):
            raise TypeError('typed current backend analytical context required')
        return context or AnalyticsReviewContext()

    def analytical_status(self,ident):
        from dota_coach.learning.verified_history import history_document
        with self.lock:
            if self.jobs.get(ident,{}).get('state')!='complete' or ident not in self.analytical_witnesses:
                raise ValueError('Сначала создайте отчёт в текущей сессии.')
            account,workflow,history=self.analytical_witnesses[ident]
        context=self.current_analytical_review(account)
        case=None if workflow is None else workflow.document(current_review=context.case_review)['case_assessment']
        prefix_active=True
        if workflow is not None and workflow.prefix is not None:
            from dataclasses import asdict
            from dota_coach.evidence.contracts import content_hash
            registry=context.prefix_registry
            candidate=workflow.prefix.get('candidate_defensive_impact_input')
            sources=[] if candidate is None else candidate['model']['source_refs']+candidate['goal']['source_refs']+[source for row in candidate['facts'] for source in row['fact']['source_refs']]
            prefix_active=bool(registry and candidate and any(
                content_hash({**asdict(a),'authenticated_passes':sorted(a.authenticated_passes)})==workflow.prefix.get('admission_hash')
                and all(content_hash(source) in registry.allowed_source_receipt_hashes for source in sources+[asdict(r) for r in a.review_sources])
                for a in registry.admissions))
        case_active=bool(case and prefix_active and (case.get('current_review')or{}).get('admitted_for_real_history'))
        if case is not None and not case_active:
            case['verdict']='insufficient_evidence'
        review=context.history_review
        history_options={} if review is None else {name:getattr(review,name) for name in ('admission','case_registry','current_case_admissions')}
        history_value=None if history is None else history_document(history,**history_options)
        return {'case':case,'case_admitted':case_active,'prefix_admission_active':prefix_active if workflow is not None and workflow.prefix is not None else None,
            'history':history_value,'snapshot_json_is_not_authority':True,'global_coaching_certified':False}

    def resource_plan(self,ident,request):
        from dota_coach.learning.resource_plan import compute_resource_plan
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            path=self.out/ident/'analysis.json'
            if not path.is_file():
                raise ValueError('Нужен отчёт эпизода с собственными ресурсами.')
            result=compute_resource_plan(strict_json(path.read_text(encoding='utf-8')),request)
            with (self.out/ident/'resource-plans.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
        return result

    def build_plan(self,ident,request):
        from dota_coach.learning.build_planner import create_build_plan
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            path=self.out/ident/'analysis.json'
            if not path.is_file():
                raise ValueError('Нужен отчёт собственного эпизода, а не журнал упражнения.')
            catalog=load_valve_snapshot(self.catalog_path,raw_dir=self.catalog_raw_dir)
            previous=self.latest_build_plans.get(ident)
            result=create_build_plan(strict_json(path.read_text(encoding='utf-8')),catalog,request,previous)
            from dota_coach.evidence.contracts import content_hash
            result['recorded_at']=datetime.now(timezone.utc).isoformat()
            result['payload_sha256']=content_hash({key:value for key,value in result.items() if key!='payload_sha256'})
            with (self.out/ident/'build-plan-history.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
            self.latest_build_plans[ident]=result
            return result

    def latest_build_plan(self,ident):
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            if not (self.out/ident/'analysis.json').is_file():
                raise ValueError('Нужен отчёт собственного эпизода, а не журнал упражнения.')
            return {'latest_plan':self.latest_build_plans.get(ident)}

    def semantic_prefix(self,ident,domain,cutoff):
        from dota_coach.ingest.semantic_events import project_semantic_timeline
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            path=self.out/ident/'semantic-events.json'
            if not path.is_file() or domain not in ('trace','combat_names'):
                raise ValueError('Ретроспектива provider не входит в префикс replay.')
            source=strict_json(path.read_text(encoding='utf-8'))
            events=source['lanes'].get(domain)
            if events is None:
                raise ValueError('Этот replay источник не подключён.')
            prefix=project_semantic_timeline(events,source_domain=domain,cutoff_record_index=cutoff,dataset_kind=source.get('dataset_kind','unknown'))
            from dota_coach.ingest.semantic_lifecycle import project_semantic_lifecycles
            from dota_coach.evidence.contracts import content_hash
            prefix['lifecycle_prefix']=project_semantic_lifecycles(source,domain,cutoff)
            from dota_coach.ingest.objective_state import project_objective_state
            prefix['objective_prefix']=project_objective_state(source,domain,cutoff)
            prefix['prefix_sha256']=content_hash({k:v for k,v in prefix.items() if k!='prefix_sha256'})
            return prefix

    def ward_plan(self,ident,request):
        from dota_coach.learning.ward_plan import create_ward_plan
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            path=self.out/ident/'ward-observations.json'
            report_path=self.out/ident/'analysis.json'
            if not path.is_file() or not report_path.is_file():
                raise ValueError('В отчёте нет связанного источника вардов.')
            source=strict_json(path.read_text(encoding='utf-8'))
            report=strict_json(report_path.read_text(encoding='utf-8'))
            if not isinstance(source,dict) or not isinstance(report,dict) or not isinstance(report.get('notebook'),dict):
                raise ValueError('Источник вардов и отчёт должны содержать связанные объекты.')
            if (source.get('match_id')!=self.raw['match_id'] or source.get('match_id')!=report.get('match_id')
                    or source.get('account_id')!=report.get('account_id')
                    or source.get('actor')!=report.get('notebook',{}).get('actor')
                    or source.get('resource_slot')!=report.get('notebook',{}).get('resource_slot')
                    or source.get('dataset_kind')!=report.get('dataset_kind')):
                raise ValueError('Источник вардов относится к другому отчёту или игроку.')
            result=create_ward_plan(source,request,self.latest_ward_plans.get(ident))
            with (self.out/ident/'ward-plan-history.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
            self.latest_ward_plans[ident]=result
            return result

    def latest_ward_plan(self,ident):
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete' or not (self.out/ident/'ward-observations.json').is_file() or not (self.out/ident/'analysis.json').is_file():
                raise ValueError('Сначала создайте отчёт с источником вардов в этой сессии.')
            return {'latest_plan':self.latest_ward_plans.get(ident)}

    def review(self,ident,payload):
        from dota_coach.validation.review_workspace import append_review
        with self.lock:
            if not isinstance(ident,str) or self.jobs.get(ident,{}).get('state')!='complete':
                raise ValueError('Сначала создайте отчёт в этой сессии.')
            path=self.out/ident/'independent-review'
            if not (path/'dataset.jsonl').is_file():
                raise ValueError('Для этого отчёта нет слепого пакета.')
            return append_review(path,payload)


def serve_workbench(workbench: Workbench,port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def respond(self,status,body,mime='application/json; charset=utf-8',headers=None):
            if not isinstance(body,bytes):
                body=(json.dumps(body,ensure_ascii=False) if isinstance(body,dict) else body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            for name,value in (headers or {}).items():
                self.send_header(name,value)
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                return self.respond(403,{'error':'Рабочая область доступна только по локальному адресу.'})
            path=urlsplit(self.path).path
            if path=='/':
                return self.respond(200,workbench.page(),'text/html; charset=utf-8')
            if path.startswith('/api/analytics-status/'):
                try:
                    return self.respond(200,workbench.analytical_status(path.removeprefix('/api/analytics-status/')))
                except (ValueError,TypeError,OSError) as exc:
                    return self.respond(400,{'error':str(exc)})
            if path.startswith('/api/jobs/'):
                with workbench.lock:
                    job=dict(workbench.jobs.get(path.split('/')[-1],{}))
                return self.respond(200,job) if job else self.respond(404,{'error':'Задача не найдена.'})
            if path.startswith('/api/build-plan/'):
                try:
                    return self.respond(200,workbench.latest_build_plan(path.removeprefix('/api/build-plan/')))
                except ValueError as exc:
                    return self.respond(400,{'error':str(exc)})
            if path.startswith('/api/ward-plan/'):
                try:
                    return self.respond(200,workbench.latest_ward_plan(path.removeprefix('/api/ward-plan/')))
                except ValueError as exc:
                    return self.respond(400,{'error':str(exc)})
            if path.startswith('/reports/'):
                parts=path.split('/')
                relative='/'.join(parts[3:])
                with workbench.lock:
                    published = len(parts)>=4 and workbench.jobs.get(parts[2],{}).get('state')=='complete'
                if not published:
                    return self.respond(404,{'error':'Отчёт ещё не опубликован.'})
                if relative.startswith('clips/'):
                    from dota_coach.video.trace_clips import verified_clip_path
                    target=verified_clip_path(workbench.out/parts[2],relative)
                    if target is not None:
                        try:
                            data=target.read_bytes()
                            range_header=self.headers.get('Range')
                            headers={'Accept-Ranges':'bytes'}
                            if range_header is None:
                                return self.respond(200,data,'video/mp4',headers)
                            match=re.fullmatch(r'bytes=([0-9]*)-([0-9]*)',range_header)
                            try:
                                if match is None or not any(match.groups()):
                                    raise ValueError('invalid byte range')
                                left,right=match.groups()
                                if left:
                                    start=int(left)
                                    end=int(right) if right else len(data)-1
                                    if start>=len(data) or end<start:
                                        raise ValueError('unsatisfiable byte range')
                                    end=min(end,len(data)-1)
                                else:
                                    suffix=int(right)
                                    if suffix<=0:
                                        raise ValueError('unsatisfiable suffix byte range')
                                    start=max(0,len(data)-suffix);end=len(data)-1
                            except ValueError:
                                headers['Content-Range']=f'bytes */{len(data)}'
                                return self.respond(416,{'error':'Диапазон клипа недоступен.'},headers=headers)
                            headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
                            return self.respond(206,data[start:end+1],'video/mp4',headers)
                        except OSError:
                            pass
                    return self.respond(404,{'error':'Проверенный клип не найден.'})
                allowed=('clip-navigation.json','index.html','analysis.json','source-match.json','trace-audit.json','observed-actions.json','activation-notebook.json','build-context.json','study-sources.json','profile.json','action-states.json','training.json','resource-plans.jsonl','semantic-events.json','build-plan-history.jsonl',
                    'semantic-lifecycles.json','resource-opportunities.json','ward-observations.json','ward-plan-history.jsonl','objective-state.json','ward-analysis.json','choice-windows.json','unit-control.json','replay-sources.json','mechanics.json','movement-support.json','defensive-impact.json','impact-prefix.json','case-assessment.json','terrain-support.json','verified-history.json',
                    'independent-review/README.md','independent-review/quality.json','independent-review/dataset.jsonl','independent-review/blinded/blind-cases.jsonl','independent-review/blinded/annotation-template.jsonl',
                    'independent-review/system/predictions.jsonl','independent-review/annotations.jsonl','independent-review/blinded/index.html')
                if len(parts)<4 or parts[2] not in workbench.jobs or relative not in allowed:
                    return self.respond(404,{'error':'Файл не найден.'})
                target=workbench.out/parts[2]/relative
                try:
                    root=(workbench.out/parts[2]).resolve()
                    if not target.resolve().is_relative_to(root):
                        return self.respond(404,{'error':'Файл не найден.'})
                    if workbench.video_path is not None:
                        video=Path(workbench.video_path).resolve()
                        if video.exists() and target.exists() and video.samefile(target):
                            return self.respond(404,{'error':'Исходная запись не публикуется.'})
                    return self.respond(200,target.read_bytes(),'text/html; charset=utf-8' if target.suffix=='.html' else 'application/json; charset=utf-8' if target.suffix=='.json' else 'text/plain; charset=utf-8')
                except OSError:
                    return self.respond(404,{'error':'Артефакт ещё не готов.'})
            return self.respond(404,{'error':'Страница не найдена.'})
        def do_POST(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                return self.respond(403,{'error':'Недопустимый адрес рабочей области.'})
            if (self.path not in ('/api/jobs','/api/training','/api/training-progress','/api/resource-plan','/api/semantic-prefix','/api/build-plan','/api/ward-plan') and not self.path.startswith('/api/review/')) or self.headers.get('X-Foresight-Token')!=workbench.token:
                return self.respond(403,{'error':'Недопустимый локальный запрос.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                limit=1024 if self.path=='/api/jobs' else 16384 if self.path=='/api/training' else 262144
                if not 0<length<=limit:
                    raise ValueError('Недопустимый размер запроса.')
                row=strict_json(self.rfile.read(length).decode('utf-8'))
                if not isinstance(row,dict):
                    raise ValueError('Ожидаются поля запроса.')
                if self.path.startswith('/api/review/'):
                    return self.respond(200,workbench.review(self.path.removeprefix('/api/review/'),row))
                elif self.path=='/api/build-plan':
                    if set(row)!={'job_id','request'}:
                        raise ValueError('Ожидается отчёт и явно выбранный план предметов.')
                    return self.respond(200,workbench.build_plan(row['job_id'],row['request']))
                elif self.path=='/api/ward-plan':
                    if set(row)!={'job_id','request'}:
                        raise ValueError('Ожидается отчёт и явно сформулированная задача варда.')
                    return self.respond(200,workbench.ward_plan(row['job_id'],row['request']))
                elif self.path=='/api/semantic-prefix':
                    if set(row)!={'job_id','source_domain','cutoff_record_index'}:
                        raise ValueError('Ожидается источник и граница префикса.')
                    return self.respond(200,workbench.semantic_prefix(row['job_id'],row['source_domain'],row['cutoff_record_index']))
                elif self.path=='/api/jobs':
                    if set(row)!={'account_id'}:
                        raise ValueError('Ожидается только account_id.')
                    ident=workbench.submit(row['account_id'])
                elif self.path=='/api/training':
                    if set(row)!={'account_id','task_code','statement','confirmed'}:
                        raise ValueError('Ожидаются аккаунт, выбранная задача и явно подтверждённая цель.')
                    ident=workbench.submit_training(row['account_id'],row['task_code'],row['statement'],row['confirmed'])
                elif self.path=='/api/resource-plan':
                    if set(row)!={'job_id','request'}:
                        raise ValueError('Ожидается отчёт и выбранный сценарий запаса.')
                    return self.respond(200,workbench.resource_plan(row['job_id'],row['request']))
                else:
                    if set(row)!={'job_id','baseline','followup'} or not isinstance(row['job_id'],str):
                        raise ValueError('Ожидается упражнение и два журнала периодов.')
                    return self.respond(200,workbench.compare_training(row['job_id'],row['baseline'],row['followup']))
                self.respond(202,{'job_id':ident})
            except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
                self.respond(400,{'error':str(exc)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Foresight -> http://127.0.0.1:{server.server_port}/',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close();workbench.worker.shutdown(wait=False,cancel_futures=True)
