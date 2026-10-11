"""Retrospective marker timeline, separated from decision and blind review inputs."""
from __future__ import annotations
import html
import json
from pathlib import Path

LABELS = {
    'tp_use_observed': 'Наблюдаемое использование TP',
    'tp_modifier_applied': 'Добавлен маркер телепортации',
    'tp_modifier_removed': 'Снят маркер телепортации',
    'smoke_use_observed': 'Наблюдаемое использование smoke',
    'smoke_modifier_applied': 'Добавлен маркер smoke',
    'smoke_modifier_removed': 'Снят маркер smoke',
    'buyback_observed': 'Наблюдаемый buyback',
    'building_destroyed_observed': 'Здание уничтожено по источнику',
    'roshan_killed_observed': 'Roshan убит по источнику',
}


def semantic_section(payload: dict) -> str:
    groups = []
    for domain, events in payload['lanes'].items():
        rows = []
        for event in events:
            stamp = event['game_time']
            if stamp is None:
                time = 'Игровое время неизвестно'
                if event['raw_timestamp'] is not None:
                    time += f"; raw clock {event['raw_timestamp']:g}"
            else:
                sign = '−' if stamp < 0 else ''
                seconds = abs(stamp)
                time = f'{sign}{int(seconds)//60}:{seconds%60:04.1f} (непроверенный clock)'
            label = LABELS.get(event['kind'], 'Наблюдаемое событие')
            who = ' → '.join(x for x in (event['actor'], event['target']) if x) or 'Субъект неизвестен'
            button = (f"<button type='button' class='semantic-prefix' data-domain='{html.escape(domain,quote=True)}' "
                      f"data-cutoff='{event['source_record_index']}'>История маркеров до события</button>"
                      if domain != 'provider' else 'Ретроспектива; не вход оценки решения')
            rows.append(f"<tr><td>{html.escape(time)}</td><td>{html.escape(label)}<br>{html.escape(who)}</td>"
                        f"<td><code>{html.escape(event['source_ref'])}</code><br>{button}</td></tr>")
        names = {'trace': 'Replay: прямые наблюдения действий', 'combat_names': 'Replay: модификаторы и действия',
                 'provider': 'OpenDota: ретроспективные objectives и buyback'}
        groups.append(f"<details><summary>{html.escape(names.get(domain,domain))} · {len(events)} событий</summary>"
                      f"<div class='table-scroll'><table><thead><tr><th>Время</th><th>Событие</th><th>Источник</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
                      + ('<p>Подходящих событий в этом источнике не получено. Это не доказательство их отсутствия в игре.</p>' if not events else '') + '</details>')
    return ("<section id='semantic-events'><h2>TP, smoke, buyback и objectives</h2>"
            "<p>Здесь показано, что зарегистрировал каждый источник. Использование TP не доказывает завершение телепортации; "
            "снятие smoke не устанавливает причину. Источники не объединены по времени или субъектам: один случай может иметь несколько записей.</p>"
            "<p>Эта ретроспектива отделена от оценки выбора и слепой разметки. Наблюдаемость игроком, точная длительность, исход канала и полезность не установлены.</p>"
            + ''.join(groups) + "<p id='semantic-prefix-result' role='status'></p><a href='semantic-events.json'>Все события, источники и неизвестные поля</a></section>")


def attach_semantic_submission(path, *, job_id: str, token: str):
    config = json.dumps({'job_id': job_id, 'token': token}, ensure_ascii=True).replace('<', '\\u003c')
    script = """<script>const semanticContext=__CONFIG__;
document.querySelectorAll('button.semantic-prefix').forEach(button=>button.addEventListener('click',async()=>{
const box=document.getElementById('semantic-prefix-result');button.disabled=true;box.textContent='Получение предшествующей истории…';
try{const response=await fetch('/api/semantic-prefix',{method:'POST',headers:{'Content-Type':'application/json','X-Foresight-Token':semanticContext.token},body:JSON.stringify({job_id:semanticContext.job_id,source_domain:button.dataset.domain,cutoff_record_index:Number(button.dataset.cutoff)})});
const prefix=await response.json();if(!response.ok)throw Error(prefix.error);
box.replaceChildren();const info=document.createElement('p');info.textContent='Записей до этого события: '+prefix.events.length+'. Это история наблюдаемых маркеров; исход и доступность действия неизвестны.';box.append(info);
const list=document.createElement('ul');prefix.states.forEach(state=>{const row=document.createElement('li');const statuses={unknown:'неизвестно',apply_marker_observed:'последним наблюдалось добавление',remove_marker_observed:'последним наблюдалось снятие'};
row.textContent=state.subject+' · '+state.category+': '+statuses[state.modifier_status]+'; использований в наблюдаемом префиксе: '+state.use_count+'. Источник: '+state.last_source_ref;list.append(row);});box.append(list);
if(!prefix.states.length){const empty=document.createElement('p');empty.textContent='До этого события подходящих маркеров не получено; состояние неизвестно.';box.append(empty);}
if(prefix.lifecycle_prefix){const lane=prefix.lifecycle_prefix.lanes[prefix.lifecycle_prefix.source_domain];const line=document.createElement('p');line.textContent='Интервалов маркеров в этом префиксе: '+lane.intervals.length+'. Добавление/снятие относятся к одному субъекту; причина завершения и доступность игроку неизвестны.';box.append(line);}
if(prefix.objective_prefix){const lane=prefix.objective_prefix.lanes[prefix.objective_prefix.source_domain];const line=document.createElement('p');line.textContent='Наблюдаемых объектов и buyback до события: '+lane.objects.length+'. Владение, возрождение и сведения игрока не установлены.';box.append(line);}
}catch(error){box.textContent=error.message;}finally{button.disabled=false;}}));</script>""".replace('__CONFIG__', config)
    page = Path(path).read_text(encoding='utf-8')
    Path(path).write_text(page.replace('</body>', script+'</body>'), encoding='utf-8')


def static_semantic_script():
    return """<script>document.querySelectorAll('button.semantic-prefix').forEach(button=>button.addEventListener('click',()=>{
if(typeof semanticContext==='undefined')document.getElementById('semantic-prefix-result').textContent='Для просмотра префикса открой этот отчёт в локальной рабочей области Foresight.';}));</script>"""


def lifecycle_section(payload: dict) -> str:
    groups=[]
    for domain,lane in payload['lanes'].items():
        rows=[]
        for interval in lane['intervals']:
            starts=', '.join(interval['apply_refs']) or 'начало не наблюдалось'
            end=interval['remove_ref'] or 'конец не наблюдался'
            delta=interval['observed_timestamp_delta']
            elapsed='неизвестна' if delta is None else f'{delta:g} с по сырому clock; не подтверждённая длительность эффекта'
            status='неоднозначное повторное добавление' if interval['ambiguity'] else 'левая граница неизвестна' if interval['left_censored'] else 'правая граница неизвестна' if interval['right_censored'] else 'наблюдались добавление и снятие'
            illusion=interval['subject_is_illusion']
            subject_note='флаг иллюзии в источнике' if illusion is True else 'флаг не-иллюзии в источнике' if illusion is False else 'тип сущности неизвестен'
            rows.append('<tr><td>'+html.escape(interval['category']+' · '+interval['subject']+' · '+subject_note)+'</td><td>'+html.escape(status)+'</td><td>'+html.escape(starts)+'<br>'+html.escape(end)+'</td><td>'+html.escape(elapsed)+'</td></tr>')
        groups.append(f"<details><summary>{html.escape(domain)} · {len(lane['intervals'])} интервалов маркеров</summary><div class='table-scroll'><table><thead><tr><th>Модификатор и субъект</th><th>Границы</th><th>Источники</th><th>Разница записанных времён</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>")
    return "<section id='semantic-lifecycles'><h2>Интервалы TP и smoke</h2><p>Связаны наблюдения добавления и снятия модификатора у одного субъекта внутри одного источника. Имя и флаг иллюзии не устанавливают полную идентичность сущности; поколения здесь неизвестны. Снятие не устанавливает прибытие, прерывание TP или раскрытие smoke. Неполные и неоднозначные границы сохранены отдельно.</p>"+''.join(groups)+"<a href='semantic-lifecycles.json'>Интервалы и ссылки на исходные записи</a></section>"


def resource_opportunity_section(payload: dict | None) -> str:
    if payload is None:
        return "<section id='resource-opportunities'><h2>Наблюдения без отбора по активациям</h2><p>Собственная последовательность предметов не предоставлена. Возможности выбора и их число неизвестны.</p></section>"
    rows=[]
    def stamp(value):
        return 'неизвестно' if value is None else f'{value/60:.1f} мин'
    for w in payload['observed_windows']:
        member=html.escape(str(w['handle']))+':'+html.escape(str(w['generation']))
        rows.append(f"<tr><td>{html.escape(w['item_id'])} · handle {member}</td><td>{stamp(w['start_game_time'])} — {stamp(w['end_game_time'])} (непроверенное время извлечения)</td><td>{w['sample_count']}</td><td>Пригодность и выбор не установлены</td><td><code>{html.escape(w['window_id'])}</code></td></tr>")
    coverage=payload['supplied_stream_coverage']
    return ("<section id='resource-opportunities'><h2>Наблюдения без отбора по активациям</h2>"
        f"<p>Обработано {coverage['processed_sample_count']} из {coverage['supplied_sample_count']} предоставленных собственных срезов; наблюдаемых окон состояния предметов: {len(payload['observed_windows'])}.</p>"
        "<p>Успешная активация не требуется для отбора. Срезы не устанавливают непрерывную готовность, момент выбора или полный охват возможностей. Пустая компактная проекция не доказывает отсутствие предмета. Проверенных решений по этим окнам: 0.</p>"
        "<details><summary>Наблюдаемые окна и источники</summary><div class='table-scroll'><table><thead><tr><th>Предмет</th><th>Границы наблюдений</th><th>Срезов</th><th>Пригодность</th><th>Идентификатор</th></tr></thead><tbody>"+''.join(rows)+"</tbody></table></div></details><a href='resource-opportunities.json'>Все срезы, пропуски и неизменные идентификаторы окон</a></section>")
