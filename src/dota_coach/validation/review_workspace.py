"""A blinded human review form and append-only, manifest-bound label intake.

This module never supplies reviewer identities, answers, or validation status.
It accepts trace blind cases only; system/outcome files are never opened.
"""
from __future__ import annotations

from dataclasses import asdict, fields
import json
import os
from pathlib import Path
import tempfile

from dota_coach.evidence.contracts import content_hash
from .contracts import Annotation, FactCheck, ActionCheck
from .pipeline import _rows, load_annotations, load_dataset, validate_annotations

_CASE_FIELDS = frozenset({"schema_version", "decision_id", "input_hash", "match_id", "subject",
    "observation_time", "boundary_status", "observed_action", "own_state_time", "own_state",
    "missing_context", "media_status", "review_readiness", "own_resource_facts"})
_STATE_FIELDS = frozenset({"fact_id", "predicate", "value", "correctness", "availability_to_subject",
                         "source_prefix_record_index"})
_RESOURCE_FIELDS = frozenset({"fact_id", "predicate", "raw_observation", "semantic_validation"})
_RAW_FIELDS = frozenset({"value", "status", "source_record_index", "source_tick", "net_tick", "wire_type",
                       "record_index", "tick", "unknown_reason"})


def _plain(value):
    """Reject nested objects in arbitrary scalar display fields."""
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("blind scalar field must not contain nested context")
    return value


def _pack(pack_dir):
    root = Path(pack_dir).resolve()
    for name in ("dataset.jsonl", "blinded/blind-cases.jsonl", "annotations.jsonl"):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("review pack must contain local regular files")
    records = load_dataset(root / "dataset.jsonl")
    by_id = {record.decision_id: record for record in records}
    cases = list(_rows(root / "blinded/blind-cases.jsonl"))
    seen = set()
    for case in cases:
        if case.get("schema_version") != "foresight.trace-blind-case.v1" or set(case) - _CASE_FIELDS:
            raise ValueError("unsupported or unblinded trace case")
        record = by_id.get(case.get("decision_id"))
        if record is None or case["decision_id"] in seen:
            raise ValueError("blind case does not have a unique manifest binding")
        seen.add(case["decision_id"])
        if (case.get("input_hash") != record.input_hash or
                content_hash({k: v for k, v in case.items() if k != "input_hash"}) != record.input_hash):
            raise ValueError("blind case input_hash differs from manifest or content")
        if case.get("match_id") != record.match_id or case.get("subject") != record.target_player:
            raise ValueError("blind case subject or match differs from manifest")
        for field in ("observation_time", "boundary_status", "own_state_time", "media_status", "review_readiness"):
            _plain(case.get(field))
        action = case.get("observed_action")
        if not isinstance(action, dict) or set(action) != {"stage", "item"}:
            raise ValueError("blind observed action must be a minimal token")
        for value in action.values():
            _plain(value)
        if not isinstance(case.get("missing_context"), list) or not all(
                isinstance(v, str) for v in case["missing_context"]):
            raise ValueError("missing context must be a string list")
        for field, allowed in (("own_state", _STATE_FIELDS), ("own_resource_facts", _RESOURCE_FIELDS)):
            facts = case.get(field, [])
            if not isinstance(facts, list):
                raise ValueError("blind own facts must be a list")
            for fact in facts:
                if not isinstance(fact, dict) or set(fact) - allowed:
                    raise ValueError("unblinded own fact fields")
                if not isinstance(fact.get("fact_id"), str) or not isinstance(fact.get("predicate"), str):
                    raise ValueError("blind fact requires identifiers")
                if not fact["predicate"].startswith("self."):
                    raise ValueError("only own facts may enter this workspace")
                for key, value in fact.items():
                    if key == "raw_observation":
                        if not isinstance(value, dict) or set(value) - _RAW_FIELDS:
                            raise ValueError("unblinded raw observation fields")
                        for scalar in value.values():
                            _plain(scalar)
                    else:
                        _plain(value)
        ids = [f["fact_id"] for f in case.get("own_state", []) + case.get("own_resource_facts", [])]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate blind fact id")
    if seen != set(by_id):
        raise ValueError("workspace requires exactly one blind case per dataset record")
    return root, records, cases


def _references(case):
    facts = {f["fact_id"] for f in case.get("own_state", []) + case.get("own_resource_facts", [])}
    facts.update({"boundary:" + case["decision_id"], "goal:" + case["decision_id"]})
    evidence = set(facts)
    for fact in case.get("own_state", []) + case.get("own_resource_facts", []):
        raw = fact.get("raw_observation", fact)
        for key in ("source_prefix_record_index", "source_record_index", "record_index"):
            value = raw.get(key)
            if type(value) is int and value >= 0:
                evidence.add("record:" + str(value))
    return facts, evidence


def _annotation(payload):
    if not isinstance(payload, dict):
        raise ValueError("annotation payload must be an object")
    expected = {f.name for f in fields(Annotation)} - {"review_pass"} | {"pass"}
    if set(payload) != expected:
        raise ValueError("complete annotation schema required; unexpected or missing fields")
    row = dict(payload)
    if row["pass"] not in ("decision_blinded", "extraction"):
        raise ValueError("only blinded decision or extraction passes are accepted here")
    if (row["annotator_kind"] != "human_expert" or row["adjudication_status"] != "unreviewed"
            or row["outcome_visible"] is not False or row["system_verdict_visible"] is not False):
        raise ValueError("blinded human submission cannot promote or adjudicate itself")
    row["review_pass"] = row.pop("pass")
    for name in ("acceptable_verdicts", "decisive_evidence_ids", "unknowns", "facts_checked", "available_actions"):
        if not isinstance(row[name], list):
            raise ValueError(name + " must be a JSON array")
    try:
        row["facts_checked"] = tuple(FactCheck(**f) for f in row["facts_checked"])
        actions = []
        for action in row["available_actions"]:
            if not isinstance(action.get("evidence_ids"), list):
                raise ValueError("action evidence must be an array")
            actions.append(ActionCheck(**(action | {"evidence_ids": tuple(action["evidence_ids"])})))
        row["available_actions"] = tuple(actions)
        for name in ("acceptable_verdicts", "decisive_evidence_ids", "unknowns"):
            row[name] = tuple(row[name])
        return Annotation(**row)
    except (TypeError, AttributeError) as exc:
        raise ValueError("invalid annotation field types") from exc


def append_review(pack_dir, payload) -> dict:
    """Append one actual human submission after binding and revision validation.

    Same reviewer/pass revisions must cite the current latest hash and increment
    its version. A file lock serializes separate processes; atomic replacement
    preserves all previous bytes. No quality, case, or system file is modified.
    """
    annotation = _annotation(payload)
    root, records, cases = _pack(pack_dir)
    case = next((c for c in cases if c["decision_id"] == annotation.decision_id), None)
    if case is None:
        raise ValueError("unknown decision id")
    facts, evidence = _references(case)
    if any(f.fact_id not in facts for f in annotation.facts_checked):
        raise ValueError("fact check outside blinded input")
    cited = set(annotation.decisive_evidence_ids)
    cited.update(e for a in annotation.available_actions for e in a.evidence_ids)
    if not cited <= evidence:
        raise ValueError("evidence outside blinded input")
    allowed_actions = {"action:" + case["decision_id"], "hold:" + case["decision_id"]}
    if any(a.action_id not in allowed_actions for a in annotation.available_actions):
        raise ValueError("action outside blinded case")
    # This pack explicitly lacks a verified pre-choice boundary and subject goal.
    if any(f.fact_id.startswith(("goal:", "boundary:")) and f.correctness == "correct"
           for f in annotation.facts_checked):
        raise ValueError("missing goal or choice boundary cannot be certified from this trace pack")
    assessed = annotation.review_pass == "decision_blinded" and set(annotation.acceptable_verdicts) - {
        "insufficient_evidence", "not_actionable"}
    if assessed:
        checked = {f.fact_id for f in annotation.facts_checked
                   if f.correctness == "correct" and f.availability == "available"}
        supported = set(checked)
        for fact in case.get("own_state", []) + case.get("own_resource_facts", []):
            if fact["fact_id"] in checked:
                raw = fact.get("raw_observation", fact)
                for key in ("source_prefix_record_index", "source_record_index", "record_index"):
                    if type(raw.get(key)) is int:
                        supported.add("record:" + str(raw[key]))
        if not annotation.decisive_evidence_ids or not set(annotation.decisive_evidence_ids) <= supported:
            raise ValueError("assessed decision requires correct available decisive evidence")
        if not any(a.feasibility != "unknown" for a in annotation.available_actions):
            raise ValueError("unknown feasibility cannot establish an assessed decision")
        if any(a.feasibility != "unknown" and not set(a.evidence_ids) <= supported
               for a in annotation.available_actions):
            raise ValueError("known action feasibility requires checked correct available evidence")
    lock = root / ".annotations.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("another review append is in progress; retry") from exc
    os.close(fd)
    temporary = None
    try:
        target = root / "annotations.jsonl"
        existing = load_annotations(target) if target.exists() else ()
        validate_annotations(existing, records)
        group = [a for a in existing if (a.decision_id, a.annotator_id, a.review_pass) ==
                 (annotation.decision_id, annotation.annotator_id, annotation.review_pass)]
        latest = max(group, key=lambda a: a.annotation_version) if group else None
        if latest is None:
            if annotation.annotation_version != 1:
                raise ValueError("first reviewer/pass annotation must start at version 1")
        elif (annotation.annotation_version != latest.annotation_version + 1 or
              annotation.previous_annotation_hash != latest.annotation_hash):
            raise ValueError("revision must reference the current latest reviewer/pass annotation")
        validate_annotations(existing + (annotation,), records)
        before = target.read_bytes() if target.exists() else b""
        if before and not before.endswith(b"\n"):
            before += b"\n"
        row = asdict(annotation)
        row["pass"] = row.pop("review_pass")
        encoded = (json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=root, prefix=".annotations-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(before + encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        return {"annotation_hash": annotation.annotation_hash, "annotation_version": annotation.annotation_version,
                "status": "recorded_unreviewed", "validation_status": "data_validation_pending"}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def write_review_workspace(pack_dir, *, submit_url=None, submit_token=None) -> Path:
    """Create blinded/index.html with blank review fields and optional local POST.

    The HTML contains only manifest binding fields and allowlisted blind cases.
    No previous annotations are loaded or shown to another independent reviewer.
    """
    root, records, cases = _pack(pack_dir)
    if submit_url is not None and (not isinstance(submit_url, str) or not submit_url.startswith("/api/")):
        raise ValueError("submit URL must be a local /api/ path")
    if submit_token is not None and not isinstance(submit_token, str):
        raise ValueError("submit token must be a string")
    by_id = {r.decision_id: r for r in records}
    cards = []
    for case in cases:
        record = by_id[case["decision_id"]]
        cards.append({"case": case, "binding": {k: getattr(record, k) for k in
            ("decision_id", "input_hash", "replay_hash", "patch", "dataset_kind")},
            "evidence": sorted(_references(case)[1])})
    data = json.dumps({"cards": cards, "submit_url": submit_url, "submit_token": submit_token},
                      ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    html = _HTML.replace("__DATA__", data)
    target = root / "blinded/index.html"
    if target.is_symlink():
        raise ValueError("workspace output cannot be a symlink")
    target.write_text(html, encoding="utf-8")
    return target


_HTML = r'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>Независимая слепая проверка</title><style>
body{overflow-wrap:anywhere}fieldset{min-width:0}
body{max-width:1000px;margin:24px auto;padding:0 18px;background:#101820;color:#e8edf1;font:16px system-ui}fieldset{border:1px solid #456;margin:18px 0;padding:16px}label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;max-width:100%;box-sizing:border-box}input,textarea,select{display:block;background:#192935;color:inherit;border:1px solid #678;padding:8px;width:100%}textarea{min-height:72px}button{padding:10px;margin:8px 8px 8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192935;padding:12px}details{margin:12px 0}.check{border-bottom:1px solid #456;padding:12px 0}.check input[type=checkbox]{display:inline;width:auto}#status{white-space:pre-wrap;color:#ffdf8c}h1{font-size:1.7rem}</style>
<body><h1>Независимая слепая проверка</h1><p>Ни исход боя, ни системная оценка здесь не раскрыты. Сверьте собственный контекст с проверенной записью до выбора. Название эксперта — декларация; независимость проверяется отдельно. Разметка не открывает validation gate.</p>
<label>Случай<select id="case"></select></label><div id="context"></div>
<form id="review"><fieldset><legend>Рецензент и проход</legend>
<label>Настоящее имя или согласованный ID рецензента<input id="identity" required maxlength="200" autocomplete="off" value=""></label>
<label>Проход<select id="pass" required><option value="">Выберите явно</option><option value="decision_blinded">Слепая оценка решения</option><option value="extraction">Проверка извлечения</option><option disabled value="outcome">Исход — отдельный проход после раскрытия</option><option disabled value="text">Текст — отдельный проход после раскрытия</option></select></label>
<label>Пригодность возможности<select id="eligibility" required><option value="">Выберите явно</option><option value="eligible">Пригодна</option><option value="ineligible">Непригодна</option><option value="unknown">Неизвестно</option></select></label>
<label>Допустимый вердикт<select id="verdict" required><option value="">Выберите явно</option><option value="good">Хорошее решение</option><option value="reasonable_options">Несколько разумных вариантов</option><option value="probable_error">Вероятная ошибка</option><option value="confirmed_error_within_criterion">Ошибка в рамках критерия</option><option value="insufficient_evidence">Недостаточно данных</option><option value="not_actionable">Нет возможности действия</option></select></label></fieldset>
<fieldset><legend>Проверенные факты</legend><div id="facts"></div></fieldset>
<fieldset><legend>Цель и граница выбора — отдельная проверка</legend><p>В текущем trace pack цель и точная граница выбора отсутствуют. Их нельзя подтвердить из этих наблюдений.</p><div id="bindingchecks"></div></fieldset>
<fieldset><legend>Доступные действия</legend><div id="actions"></div></fieldset>
<fieldset><legend>Обоснование и неизвестное</legend><label>Основание<textarea id="reason" required maxlength="10000"></textarea></label>
<label>Решающие evidence ID, по одному на строку<textarea id="decisive"></textarea></label>
<label>Неизвестное, по одному на строку<textarea id="unknowns"></textarea></label>
<label>Версия разметки<input id="version" type="number" min="1" step="1" placeholder="Укажите 1 для первой разметки" required></label>
<label>Hash предыдущей версии (только при исправлении)<input id="previous" maxlength="64"></label>
<label>Причина исправления<textarea id="revision"></textarea></label></fieldset>
<button type="submit">Экспортировать JSONL</button><button type="button" id="payload">Экспортировать POST payload</button><button type="button" id="send" hidden>Сохранить в локальный pack</button><pre id="status" role="status"></pre></form>
<script type="application/json" id="data">__DATA__</script><script>
'use strict';const cfg=JSON.parse(document.getElementById('data').textContent);const $=id=>document.getElementById(id);let current;
function text(tag,value,parent){const n=document.createElement(tag);n.textContent=value;parent.appendChild(n);return n}
function select(parent,id,title,options){const lab=text('label',title,parent);const s=document.createElement('select');s.id=id;lab.appendChild(s);const blank=new Option('Выберите явно','');s.appendChild(blank);for(const [v,t] of options)s.appendChild(new Option(t,v));return s}
function area(parent,id,title){const lab=text('label',title,parent);const a=document.createElement('textarea');a.id=id;a.maxLength=10000;lab.appendChild(a);return a}
function checkbox(parent,id,title){const lab=text('label','',parent),n=document.createElement('input');n.type='checkbox';n.id=id;lab.appendChild(n);lab.appendChild(document.createTextNode(title))}
function fact(container,id,index){const d=text('div','',container);d.className='check';text('strong',id,d);checkbox(d,'f-'+index,' Включить эту проверку');select(d,'c-'+index,'Корректность',[['correct','Корректно'],['incorrect','Некорректно'],['unverifiable','Невозможно проверить']]);select(d,'a-'+index,'Доступность игроку',[['available','Доступно'],['not_available','Недоступно'],['unknown','Неизвестно']]);area(d,'r-'+index,'Основание проверки')}
function render(){current=cfg.cards[Number($('case').value)];$('review').reset();for(const id of ['context','facts','bindingchecks','actions'])$(id).replaceChildren();const c=current.case;text('h2',c.decision_id,$('context'));text('p','Матч '+c.match_id+'; '+c.subject+'; патч '+current.binding.patch+'; происхождение '+current.binding.dataset_kind,$('context'));const detail=text('details','',$('context'));text('summary','Собственный слепой контекст и source references',detail);text('pre',JSON.stringify(c,null,2),detail);text('p','Допустимые evidence ID: '+current.evidence.join(', '),$('context'));current.factIDs=(c.own_state||[]).concat(c.own_resource_facts||[]).map(f=>f.fact_id);current.factIDs.push('boundary:'+c.decision_id,'goal:'+c.decision_id);current.factIDs.forEach((id,i)=>fact(i<current.factIDs.length-2?$('facts'):$('bindingchecks'),id,i));current.actionIDs=['action:'+c.decision_id,'hold:'+c.decision_id];current.actionIDs.forEach((id,i)=>{const d=text('div','',$('actions'));d.className='check';text('strong',id,d);checkbox(d,'include-'+i,' Включить проверку действия');select(d,'feasible-'+i,'Выполнимость',[['feasible','Выполнимо'],['infeasible','Невыполнимо'],['unknown','Неизвестно']]);area(d,'evidence-'+i,'Evidence ID, по одному на строку');area(d,'actionreason-'+i,'Основание')});$('status').textContent='';$('send').hidden=!cfg.submit_url}
for(let i=0;i<cfg.cards.length;i++)$('case').appendChild(new Option(cfg.cards[i].case.decision_id,String(i)));$('case').addEventListener('change',render);if(cfg.cards.length)render();else $('status').textContent='В pack нет случаев.';
const lines=id=>$(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);function required(id){const v=$(id).value.trim();if(!v)throw Error('Заполните поле '+id);return v}
function build(){if(!current)throw Error('Нет выбранного случая');const row={schema_version:'foresight.annotation.v1',...current.binding,annotator_id:required('identity'),annotator_kind:'human_expert',pass:required('pass'),eligibility:required('eligibility'),acceptable_verdicts:[required('verdict')],rationale:required('reason'),facts_checked:[],available_actions:[],decisive_evidence_ids:lines('decisive'),unknowns:lines('unknowns'),outcome_visible:false,system_verdict_visible:false,adjudication_status:'unreviewed',annotation_version:Number(required('version')),previous_annotation_hash:$('previous').value.trim()||null,revision_reason:$('revision').value.trim()||null};current.factIDs.forEach((id,i)=>{if($('f-'+i).checked){const f={fact_id:id,correctness:required('c-'+i),availability:required('a-'+i),reason:required('r-'+i)};if((id.startsWith('goal:')||id.startsWith('boundary:'))&&f.correctness==='correct')throw Error('Цель и граница выбора отсутствуют в trace pack');row.facts_checked.push(f)}});current.actionIDs.forEach((id,i)=>{if($('include-'+i).checked){const a={action_id:id,feasibility:required('feasible-'+i),evidence_ids:lines('evidence-'+i),reason:required('actionreason-'+i)};if(a.feasibility!=='unknown'&&!a.evidence_ids.length)throw Error('Известная выполнимость требует evidence ID');row.available_actions.push(a)}});const cited=row.decisive_evidence_ids.concat(row.available_actions.flatMap(a=>a.evidence_ids));if(cited.some(id=>!current.evidence.includes(id)))throw Error('Evidence ID отсутствует в слепом контексте');if(!Number.isInteger(row.annotation_version)||row.annotation_version<1)throw Error('Укажите целую версию от 1');if(row.annotation_version===1&&(row.previous_annotation_hash||row.revision_reason))throw Error('Первая версия не ссылается на предыдущую');if(row.annotation_version>1&&(!/^[a-f0-9]{64}$/.test(row.previous_annotation_hash||'')||!row.revision_reason))throw Error('Исправление требует hash и причину');const v=row.acceptable_verdicts[0];if((v==='insufficient_evidence'||row.eligibility==='unknown')&&!row.unknowns.length)throw Error('Укажите неизвестное');if(v==='not_actionable'&&row.eligibility!=='ineligible')throw Error('Нет возможности действия требует непригодность');if(!['insufficient_evidence','not_actionable'].includes(v)&&row.pass==='decision_blinded'&&(!row.facts_checked.length||!row.available_actions.length||!row.decisive_evidence_ids.length))throw Error('Вердикт требует проверки фактов, действий и решающих evidence');if(v==='reasonable_options'&&row.pass==='decision_blinded'&&row.available_actions.filter(a=>a.feasibility==='feasible').length<2)throw Error('Несколько вариантов требуют двух проверенных выполнимых действий');return row}
function validatedBuild(){const row=build();for(const values of [row.decisive_evidence_ids,row.unknowns,...row.available_actions.map(a=>a.evidence_ids)])if(new Set(values).size!==values.length)throw Error('Удалите повторяющиеся evidence ID или неизвестные причины');if(row.pass==='decision_blinded'&&!['insufficient_evidence','not_actionable'].includes(row.acceptable_verdicts[0])){const checked=new Set(row.facts_checked.filter(f=>f.correctness==='correct'&&f.availability==='available').map(f=>f.fact_id)),supported=new Set(checked);for(const f of (current.case.own_state||[]).concat(current.case.own_resource_facts||[])){if(!checked.has(f.fact_id))continue;const raw=f.raw_observation||f;for(const key of ['source_prefix_record_index','source_record_index','record_index'])if(Number.isInteger(raw[key]))supported.add('record:'+raw[key])}if(row.decisive_evidence_ids.some(e=>!supported.has(e)))throw Error('Вердикт требует корректных и доступных решающих фактов');if(!row.available_actions.some(a=>a.feasibility!=='unknown'))throw Error('Неизвестная выполнимость не подтверждает вердикт');if(row.available_actions.some(a=>a.feasibility!=='unknown'&&a.evidence_ids.some(e=>!supported.has(e))))throw Error('Выполнимость требует проверенных корректных доступных фактов')}return row}
function download(row,jsonl){const blob=new Blob([JSON.stringify(row,null,jsonl?0:2)+(jsonl?'\n':'')],{type:jsonl?'application/x-ndjson':'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=jsonl?'annotation.jsonl':'review-payload.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);$('status').textContent='Экспортировано. Независимость и правильность не подтверждены автоматически.'}
function safe(fn){try{fn()}catch(e){$('status').textContent=e.message}}$('review').addEventListener('submit',e=>{e.preventDefault();safe(()=>download(validatedBuild(),true))});$('payload').addEventListener('click',()=>safe(()=>download(validatedBuild(),false)));$('send').addEventListener('click',async()=>{try{const row=validatedBuild(),response=await fetch(cfg.submit_url,{method:'POST',headers:{'Content-Type':'application/json',...(cfg.submit_token?{'X-Foresight-Token':cfg.submit_token}:{})},body:JSON.stringify(row)}),result=await response.json();if(!response.ok)throw Error(result.error||'Не удалось сохранить');$('status').textContent='Сохранено без подтверждения качества. Для исправления сохраните hash:\n'+JSON.stringify(result,null,2)}catch(e){$('status').textContent=e.message}});
</script></body></html>'''
