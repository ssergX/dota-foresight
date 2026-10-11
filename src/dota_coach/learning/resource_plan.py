"""Explicit what-if reserve plans; raw arithmetic never becomes a game verdict."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re

from dota_coach.evidence.contracts import content_hash


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def compute_resource_plan(report: dict, request: dict) -> dict:
    expected = {'decision_id', 'resource_input_hash', 'reserve_action', 'reserve_cost', 'repetitions', 'margin', 'confirmed'}
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError('Нужны эпизод, hash ресурсов и явно выбранные параметры запаса.')
    if request['confirmed'] is not True:
        raise ValueError('Подтвердите, что это ваш сценарий планирования.')
    name = request['reserve_action']
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError('Укажите резервируемое действие, до 200 символов.')
    for key in ('reserve_cost', 'margin'):
        value = request[key]
        if not _finite(value) or value < 0:
            raise ValueError('Стоимость и запас должны быть конечными неотрицательными числами.')
    count = request['repetitions']
    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError('Число применений должно быть целым от 1 до 20.')
    required = request['reserve_cost'] * count + request['margin']
    if not _finite(required):
        raise ValueError('Переполнение расчёта запаса.')
    ident = request['decision_id']
    if not isinstance(ident, str):
        raise ValueError('Нужен идентификатор эпизода.')
    resource = report.get('resource_reviews', {}).get(ident)
    if not resource or resource.get('schema_version') != 'foresight.resource-prefix-review.v1':
        raise ValueError('В эпизоде нет связанного собственного префикса ресурсов.')
    if resource.get('action_id') != ident or request['resource_input_hash'] != resource.get('input_hash'):
        raise ValueError('Ресурсный контекст изменился; заново откройте эпизод.')
    mana, cost = resource.get('own_mana_raw'), resource.get('activation_mana_cost_raw')
    def numeric(value):
        return _finite(value) and value >= 0
    known = numeric(mana) and numeric(cost)
    after = mana - cost if known else None
    if after is not None and after < 0:
        status = 'conflicting_raw_resources'
        claim = 'Стоимость превышает предшествующее поле маны. Срезы или семантика требуют сверки; план не оценивается.'
        activate_slack = hold_slack = None
    elif known:
        activate_slack, hold_slack = after - required, mana - required
        status = 'arithmetic_on_raw_prefix_and_user_assumptions'
        claim = (f'Для «{name.strip()}» по указанной тобой стоимости нужен запас {required:g}. '
                 f'Арифметический остаток после поля стоимости предмета — {after:g}; '
                 f'разница с запасом — {activate_slack:g}. Без этой стоимости разница — {hold_slack:g}. '
                 'Это условие планирования; угроза, выполнимость и точный момент выбора ещё не проверены.')
    else:
        status = 'insufficient_resource_fields'
        activate_slack = hold_slack = None
        claim = 'Неизвестна собственная мана или стоимость предмета. Условие запаса записано, сравнение недоступно.'
    assumptions = {key: request[key] for key in ('reserve_action', 'reserve_cost', 'repetitions', 'margin')}
    assumptions['reserve_action'] = name.strip()
    kind=report.get('dataset_kind','unknown')
    if kind not in ('replay','synthetic','unknown'):
        raise ValueError('Неизвестный тип происхождения отчёта.')
    projection = {'match_id': report.get('match_id'), 'account_id': report.get('account_id'), 'dataset_kind':kind,
                  'decision_id': ident, 'resource_input_hash': resource['input_hash'], 'assumptions': assumptions}
    return {'schema_version': 'foresight.resource-plan.v1', 'plan_id': content_hash(projection),
            **projection, 'created_at': datetime.now(timezone.utc).isoformat(),
            'goal_origin': 'user_declared_what_if_not_prior_intent',
            'reserve_cost_origin': 'user_declared_not_historical_mechanic',
            'required_mana': required, 'own_mana_raw': mana, 'selected_cost_raw': cost,
            'mana_source': resource['mana_source'], 'cost_source': resource['cost_source'],
            'activate_slack': activate_slack, 'hold_slack': hold_slack, 'status': status,
            'claim': claim, 'verdict': 'insufficient_evidence', 'feasibility': 'unknown',
            'strategic_quality': 'not_established', 'training_eligible': False,
            'next_check': 'Перед следующим похожим действием назови резервируемое действие и его стоимость; отдельно проверь угрозу и ограничения применения.'}


def resource_plan_form(resource: dict) -> str:
    ident = html.escape(resource['action_id'], quote=True)
    digest = html.escape(resource['input_hash'], quote=True)
    return f"""<details><summary>Спланировать запас для следующего действия</summary>
<form class='resource-plan' data-decision='{ident}' data-resource-hash='{digest}'>
<p>Выбери свой сценарий. Указанная стоимость — твоё предположение, не проверенная механика исторического патча. Это не оценка прошлого решения.</p>
<label>Какое действие сохранить? <input name='reserve_action' required maxlength='200'></label>
<label>Мана на одно применение <input name='reserve_cost' type='number' min='0' step='any' required></label>
<label>Число применений <input name='repetitions' type='number' min='1' max='20' step='1' required></label>
<label>Дополнительный запас <input name='margin' type='number' min='0' step='any' required></label>
<label><input name='confirmed' type='checkbox' required> Это выбранный мной сценарий планирования</label>
<button type='submit'>Проверить запас</button><p class='plan-result' role='status'></p></form></details>"""


def attach_resource_plan_submission(path, *, job_id: str, token: str):
    if re.fullmatch(r'[0-9a-f]{24}', job_id) is None:
        raise ValueError('local job identity required')
    config = json.dumps({'job_id': job_id, 'token': token}, ensure_ascii=True).replace('<', '\\u003c')
    script = """<script>const planContext=__CONFIG__;
document.querySelectorAll('form.resource-plan').forEach(form=>form.addEventListener('submit',async e=>{e.preventDefault();
const box=form.querySelector('.plan-result'),button=form.querySelector('button');button.disabled=true;box.textContent='Расчёт выбранного условия…';
try{const fields=new FormData(form);const request={decision_id:form.dataset.decision,resource_input_hash:form.dataset.resourceHash,
reserve_action:fields.get('reserve_action'),reserve_cost:Number(fields.get('reserve_cost')),repetitions:Number(fields.get('repetitions')),
margin:Number(fields.get('margin')),confirmed:form.elements.confirmed.checked};
const response=await fetch('/api/resource-plan',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':planContext.token},body:JSON.stringify({job_id:planContext.job_id,request})});
const result=await response.json();if(!response.ok)throw Error(result.error);box.textContent=result.claim;
const link=document.createElement('a');link.textContent='Скачать план и источники';
link.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));link.download='resource-plan.json';box.append(document.createElement('br'),link);
}catch(error){box.textContent=error.message;}finally{button.disabled=false;}}));</script>""".replace('__CONFIG__', config)
    page = Path(path).read_text(encoding='utf-8')
    Path(path).write_text(page.replace('</body>', script + '</body>'), encoding='utf-8')


def static_resource_plan_script() -> str:
    return """<script>document.querySelectorAll('form.resource-plan').forEach(form=>form.addEventListener('submit',e=>{
if(typeof planContext==='undefined'){e.preventDefault();form.querySelector('.plan-result').textContent='Для расчёта открой этот эпизод в локальной рабочей области Foresight.';}}));</script>"""
