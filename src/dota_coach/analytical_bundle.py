"""Deterministic surfaces for compiled prefix, case/history and grid proposals."""
from __future__ import annotations

import html
import json


def _e(value):
    return html.escape(str(value), quote=True)


def terrain_section(payload):
    if payload is None:
        return '<section id="terrain-support"><h2>Обзор и маршруты по карте</h2><p>Карта нужного патча и правила обзора не предоставлены. Позиции в replay не устанавливают обзор, безопасность пути или полезность варда.</p><a href="terrain-support.json">Состояние источника</a></section>'
    geometry = payload['candidate_geometry']
    summary = '<p>Условный расчёт по переданной сетке и заявленным правилам. Фактический обзор Dota, безопасность маршрута и ценность варда не установлены.</p>'
    body = ''
    if geometry is None:
        summary += '<p>Расчёт недоступен: карта, версия игры или временная граница не согласованы.</p>'
    else:
        views = geometry['ward_views']
        graph = geometry['navigation_graph']
        summary += '<p>Известных проходимых клеток: ' + str(len(graph['nodes']) if graph else 0) + '. Клеток с неизвестной проходимостью: ' + str(geometry['unknown_navigation_cells']) + '.</p>'
        summary += '<p>Клеток, покрытых хотя бы двумя предложенными точками: ' + str(len(geometry['duplicate_visible_cells'])) + '. Это геометрическое пересечение; оно не доказывает дублирование полезной информации.</p>'
        for index, view in enumerate(views):
            groups = {key: set(map(tuple, view[key])) for key in ('visible_cells', 'blocked_cells', 'unknown_cells')}
            points = set.union(*groups.values())
            if not points:
                continue
            minx, maxx = min(p[0] for p in points), max(p[0] for p in points)
            miny, maxy = min(p[1] for p in points), max(p[1] for p in points)
            width, height = (maxx - minx + 1) * 24, (maxy - miny + 1) * 24
            cells = ''
            for x, y in sorted(points):
                key = next(k for k, values in groups.items() if (x, y) in values)
                fill = {'visible_cells': '#438b75', 'blocked_cells': '#82525c', 'unknown_cells': '#8b7944'}[key]
                label = {'visible_cells': 'условно видима', 'blocked_cells': 'закрыта', 'unknown_cells': 'неизвестно'}[key]
                cells += '<rect x="' + str((x-minx)*24) + '" y="' + str((y-miny)*24) + '" width="23" height="23" fill="' + fill + '"><title>' + _e(f'{x},{y}: {label}') + '</title></rect>'
            q = view['query']
            cells += '<circle cx="' + str((q['x']-minx)*24+12) + '" cy="' + str((q['y']-miny)*24+12) + '" r="5" fill="#fff"/>'
            body += '<details' + (' open' if index == 0 else '') + '><summary>Предложение ' + _e(q['query_id']) + '</summary><p>Видимые / закрытые / неизвестные клетки: ' + str(len(groups['visible_cells'])) + ' / ' + str(len(groups['blocked_cells'])) + ' / ' + str(len(groups['unknown_cells'])) + '.</p><svg role="img" aria-label="Условная сетка обзора" viewBox="0 0 ' + str(width) + ' ' + str(height) + '" style="width:100%;max-width:640px;max-height:420px">' + cells + '</svg></details>'
        if views:
            body += '<p>Зелёный — условно видимо; красный — закрыто; жёлтый — неизвестно. Белая точка — предложенная позиция. Координаты относятся к переданной сетке.</p>'
    return '<section id="terrain-support"><h2>Обзор и маршруты по карте</h2>' + summary + body + '<details><summary>Границы проверки</summary><p>' + _e('; '.join(payload['reason_codes'])) + '</p></details><a href="terrain-support.json">Исходный результат и точные связи</a></section>'


def case_section(payload):
    if payload is None:
        return '<section id="verified-case"><h2>Оценка конкретного выбора</h2><p>Нет отдельно допущенного критерия и источника выбранного действия. Арифметика сценария не становится оценкой игрока.</p><a href="case-assessment.json">Состояние оценки</a></section>'
    # The typed producer owns decision/explanation semantics. Render only
    # public deterministic claims; never infer a verdict from candidate numbers.
    verdicts = {'insufficient_evidence':'недостаточно данных', 'good':'выбранное действие удовлетворяет проверенным ограничениям',
        'reasonable_options':'несколько допустимых вариантов в пределах цели',
        'confirmed_error_within_criterion':'подтверждённое нарушение в пределах проверенного критерия'}
    states = {'robustly_meets':'все расчётные значения удовлетворяют цели', 'robustly_fails':'все расчётные значения нарушают цель',
        'uncertain':'границы не устанавливают выполнение цели', 'infeasible':'действие исключено условиями'}
    alternatives = ''
    def bounds(value):
        return 'неизвестно' if value is None else _e(value['minimum']) + ' … ' + _e(value['maximum'])
    for alt in payload.get('alternatives', ()):
        alternatives += '<li><strong>' + {'activate':'Активировать', 'hold':'Сохранить ресурс'}.get(alt['action'], _e(alt['action'])) + '</strong>: баланс HP ' + bounds(alt['hp_after_impact']) + ', мана ' + bounds(alt['mana_after_action']) + '. ' + states.get(alt['goal_status'], 'Результат неизвестен') + '.</li>'
    goal = '<p>Заявленная цель: HP не ниже ' + _e(payload.get('minimum_hp_goal', 'неизвестно')) + ', мана не ниже ' + _e(payload.get('minimum_mana_goal', 'неизвестно')) + '.</p>'
    return '<section id="verified-case"><h2>Оценка конкретного выбора</h2><p>Вердикт: ' + verdicts.get(payload.get('verdict'), 'недостаточно данных') + '. Глобальная стратегическая правильность не установлена.</p>' + goal + ('<ul>' + alternatives + '</ul>' if alternatives else '<p>Для игрового вывода недостаточно допущенных сведений.</p>') + '<p>Экспорт — снимок расчёта. Перед использованием требуется текущая проверка допуска; файл её не заменяет.</p><a href="case-assessment.json">Расчёт, источники и ограничения</a></section>'


def history_section(payload):
    if payload is None:
        return '<section id="verified-history"><h2>Проверенная история решений</h2><p>История выбранного пользователя с полным учётом подходящих ситуаций не предоставлена. Один публичный replay не устанавливает привычку или изменение поведения.</p><a href="verified-history.json">Состояние истории</a></section>'
    groups=''
    for group in payload.get('groups', ()):
        context=group['context']
        title=f"Герой {context['hero_id']} · {context['role']} · {context['criterion']['patch']}"
        groups+='<details><summary>'+_e(title)+'</summary><p>Подходящих / исключённых / неизвестных / оценённых: '+str(group['eligible_count'])+' / '+str(group['ineligible_count'])+' / '+str(group['unknown_count'])+' / '+str(group['assessed_count'])+'.</p><p>Примеры: '+_e(', '.join(group['example_ids']) or 'не предоставлены')+'. Контрпримеры: '+_e(', '.join(group['counterexample_ids']) or 'не предоставлены')+'.</p>'
        exercise=group.get('exercise')
        if exercise:
            groups+='<p>Цель: '+_e(exercise['statement'])+'.</p><p>Упражнение: '+_e(exercise['exercise'])+'.</p><p>Условие применения: '+_e(exercise['trigger'])+'. Измерять: '+_e(exercise['measured_behavior'])+'.</p>'
        else:
            groups+='<p>Упражнение по выявленной привычке пока не допущено.</p>'
        groups+='</details>'
    return '<section id="verified-history"><h2>Проверенная история решений</h2><p>Знаменатель включает неизвестные и исключённые случаи. Сопоставляются одинаковые герой, роль, патч, критерий, цель и способ измерения.</p><div class="history-result">'+groups+'</div><p>Наблюдаемое изменение доли не устанавливает причинный эффект тренера.</p><a href="verified-history.json">Группы, примеры, контрпримеры и измерения</a></section>'



def write_proposal_page(path, section, *, title, artifact_name):
    from pathlib import Path
    # Callers guard output/input overlap before this reversible write.
    target = Path(path)
    sections = section
    for name in ('terrain-support.json', 'case-assessment.json', 'verified-history.json'):
        sections = sections.replace('href="'+name+'"', 'href="'+_e(artifact_name)+'"')
    page = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+_e(title)+'</title><style>body{font:16px/1.6 system-ui;background:#101b25;color:#e8eff5;margin:0}main{max-width:1000px;padding:24px;margin:auto}a{color:#a8d7ff}details{margin:16px 0;padding:12px;background:#182936;border-radius:10px}summary{cursor:pointer}svg{display:block;margin:12px auto}h1,h2{line-height:1.25}p,li{overflow-wrap:anywhere}</style><main><h1>'+_e(title)+'</h1><p>Предложенные сведения не являются независимой проверкой игры.</p>'+sections+'</main></html>'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding='utf-8')


def attach_current_review_status(path, *, job_id):
    from pathlib import Path
    import re
    if not isinstance(job_id,str) or re.fullmatch('[a-f0-9]{20,64}',job_id) is None:
        raise ValueError('exact local report job identity required')
    endpoint='/api/analytics-status/'+job_id
    script="""<script>(function(){const endpoint=ENDPOINT,verdicts={insufficient_evidence:'Недостаточно данных для текущей оценки.',good:'Выбранное действие удовлетворяет проверенным ограничениям цели.',reasonable_options:'Есть несколько допустимых вариантов в пределах цели.',confirmed_error_within_criterion:'Подтверждено нарушение в пределах проверенного критерия.'};let timer=null,running=false;const node=document.getElementById('verified-case'),first=node&&node.querySelector('p');if(first)first.textContent='Проверка текущего допуска…';const history=document.getElementById('verified-history'),groups=history&&history.querySelector('.history-result');if(groups)groups.hidden=true;async function refresh(){if(document.hidden||running)return;if(timer)clearTimeout(timer);timer=null;running=true;try{const response=await fetch(endpoint,{cache:'no-store'});if(!response.ok)throw Error('Допуск недоступен');const value=await response.json();if(first)first.textContent=verdicts[value.case&&value.case.verdict]||verdicts.insufficient_evidence;if(groups)groups.hidden=!(value.history&&value.history.current_history_witness===true);}catch(error){if(first)first.textContent='Текущий допуск не установлен. Сохранённый расчёт не подтверждает оценку.';if(groups)groups.hidden=true;}running=false;if(!document.hidden)timer=setTimeout(refresh,10000);}refresh();document.addEventListener('visibilitychange',()=>{if(timer)clearTimeout(timer);timer=null;if(!document.hidden)refresh();});})();</script>""".replace('ENDPOINT',json.dumps(endpoint))
    target=Path(path);page=target.read_text(encoding='utf-8');target.write_text(page.replace('</body>',script+'</body>'),encoding='utf-8')
