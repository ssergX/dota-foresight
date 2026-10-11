"""Evidence summaries for temporal algorithms; no extraction status promotion."""
from __future__ import annotations

import html
from collections import Counter


def objective_state_section(payload: dict) -> str:
    labels = {'building':'Здание', 'roshan':'Roshan', 'player_buyback':'Buyback игрока'}
    states = {'destruction_marker_observed':'зарегистрировано уничтожение',
              'kill_marker_observed':'зарегистрировано убийство',
              'buyback_marker_observed':'зарегистрирован buyback'}
    groups = []
    for domain, lane in payload['lanes'].items():
        rows = []
        for obj in lane['objects']:
            observations = ''.join('<li>'+html.escape(o['source_ref'])+'</li>' for o in obj['observations'])
            ambiguities = '; '.join(obj['ambiguity'])
            rows.append('<tr><td>'+html.escape(labels.get(obj['category'], obj['category']))+
                '<br>'+html.escape(obj['source_subject'] or 'Субъект неизвестен')+'</td><td>'+
                html.escape(states.get(obj['observed_state'], obj['observed_state']))+
                '<br>Владелец и доступность игроку неизвестны</td><td><ul>'+observations+'</ul>'+
                (html.escape(ambiguities) if ambiguities else '')+'</td></tr>')
        groups.append('<details><summary>'+html.escape(domain)+' · '+str(lane['coverage']['observed_markers'])+
            ' событий, '+str(lane['coverage']['source_objects'])+' наблюдаемых субъектов</summary>'+
            ('<div class="table-scroll"><table><tr><th>Субъект источника</th><th>Наблюдение</th><th>Записи</th></tr>'+
             ''.join(rows)+'</table></div>' if rows else '<p>Подходящих записей не получено.</p>')+'</details>')
    return ('<section id="objective-state"><h2>История объектов и buyback</h2>'
        '<p>Состояние складывается по записям каждого источника отдельно. Имя объекта не устанавливает '
        'его поколение или владельца. Убийство Roshan не задаёт время возрождения; buyback не доказывает '
        'текущую готовность или запас золота. Полная история OpenDota остаётся ретроспективой.</p>'+
        ''.join(groups)+'<a href="objective-state.json">Наблюдения, временные границы и неизвестные поля</a></section>')


def ward_analysis_section(payload: dict) -> str:
    rows=[]
    for analysis in payload['analyses']:
        anchor=analysis['placement_anchor'];data=analysis['callback_analysis']
        known=data['known_prefix_clock_callbacks'];missing=data['unknown_prefix_clock_callbacks']
        rows.append('<tr><td>'+html.escape(anchor['ward_id'])+'</td><td>'+str(data['callback_count'])+
            '</td><td>'+str(known)+' / '+str(missing)+'</td><td>'+str(len(data['conflict_source_refs']))+
            '</td><td>'+str(len(data['coordinate_comparisons']))+'</td></tr>')
    return ('<section id="ward-analysis"><h2>Контекст каждой командной постановки</h2><p>Для '+
        str(len(payload['analyses']))+' постановок вычислен контекст командного среза. Исключено из '
        'планирования: '+str(len(payload['excluded_placements']))+'. Это учёт переданных callback, а не полный '
        'учёт возможностей поставить вард.</p><details><summary>Записи среза постановки</summary>'+
        '<div class="table-scroll"><table><tr><th>Постановка</th><th>Записи среза</th>'
        '<th>С временем / без времени</th><th>Конфликты</th><th>Сравнения координат</th></tr>'+
        ''.join(rows)+'</table></div></details><p>Сходство координат не доказывает дублирование. '
        'Наблюдаемые объекты не являются проверенными источниками обзора. Для разбора своей задачи '
        'выберите постановку на карте или в форме ниже.</p><a href="ward-analysis.json">Все срезы и причины исключения</a></section>')


def choice_window_section(payload: dict | None) -> str:
    if payload is None:
        return '<section id="choice-windows"><h2>Окно выбора и выполнимость</h2><p>Собственный поток ресурсов не предоставлен.</p></section>'
    reasons=Counter(r for w in payload['windows'] for r in w['reason_codes'])
    known={'reaction_cue_not_observed_in_prefix':'Сигнал реакции не получен в предшествующем потоке',
        'cue_not_independently_bound':'Сигнал не связан с независимой проверкой',
        'feasibility_requirements_unresolved':'Условия выполнимости не установлены',
        'paused_or_unknown_clock_cannot_measure_reaction_latency':'Пауза или неизвестные часы не позволяют измерить реакцию',
        'clock_uncertainty_overlaps_choice_boundary':'Погрешность времени пересекает границу выбора'}
    gaps=''.join('<li>'+html.escape(known.get(r,r))+': '+str(n)+' срезов.</li>' for r,n in reasons.most_common())
    return ('<section id="choice-windows"><h2>Окно выбора и выполнимость</h2><p>Рассмотрено '+str(payload['sample_count'])+
        ' срезов. Получено сигналов: '+str(payload['cue_count'])+'. Условно поддержанных срезов выбора: '+
        str(payload['supported_choice_count'])+'; исключённых: '+str(payload['excluded_count'])+
        '; неизвестных: '+str(payload['unknown_count'])+'. Эти числа не являются оценкой качества решения.</p>'
        '<p>Расчёт проверяет поколение предмета, ману и стоимость, слот, контроль, трактовку кулдауна, заряды и цель. '
        'Границы реакции задаёт исследовательская политика, а не измерение реакции этого игрока. '
        'Между срезами постоянная готовность не предполагается.</p><details><summary>Причины неопределённости</summary><ul>'+
        ('<li>Непрерывные окна не оценены: проверенный поток изменений условий не допущен. '
         'Полнота журнала попыток действия не установлена; число попыток неизвестно.</li>'
         if payload.get('command_attempt_status')=='command_channel_not_supplied' else '')+
        gaps+'</ul></details><a href="choice-windows.json">Все вычисленные условия, операнды и временные границы</a></section>')


def replay_source_section(payload: dict) -> str:
    orders=payload['orders'];constraints=payload['constraints'];visibility=payload['event_visibility']
    order_text=('Источник приказов не предоставлен.' if orders is None else
        'Получено '+str(sum(orders['callback_counts'].values()))+
        ' сообщений приказов spectator по всему матчу. Число собственных попыток, принятых команд и начатых применений неизвестно.')
    constraint_text=('Поток изменений собственных ресурсов для выбранного аккаунта не предоставлен.' if constraints is None else
        'Получено '+str(constraints['counts']['observations'])+
        ' записей изменений собственных полей с поколениями сущностей и ссылками на исходные записи. '
        'Непрерывная доступность действия требует проверки механики и часов.')
    visibility_text=('Источник флагов видимости событий не предоставлен.' if visibility is None else
        'Флаги видимости боевых событий извлечены отдельно. Отсутствующее поле остаётся неизвестным. '
        'Они не устанавливают непрерывный обзор противника или сигнал на экране игрока.')
    binding=payload.get('command_binding')
    binding_text=('' if binding is None else '<p>В момент сообщения найдено '+
        str(binding['association_counts']['raw_ability_index_link_association'])+
        ' точных связей поля приказа с предметом или способностью выбранного героя. '
        'Сохранены поколение объекта и handle. Значение поля и стадия исполнения требуют отдельной проверки.</p>')
    if binding is not None:
        bkb=sum(n for name,n in binding.get('linked_class_counts',{}).items()
                if name.replace('_','').lower()=='cdotaitemblackkingbar')
        if bkb:
            binding_text+=('<p>Сообщений со ссылкой на объект BKB: '+str(bkb)+'. '
                'Сопоставляйте их с зарегистрированными активациями: эти потоки описывают разные события.</p>')
    return ('<section id="replay-sources"><h2>Полученные данные replay</h2><p>'+html.escape(order_text)+
        '</p><p>'+html.escape(constraint_text)+'</p><p>'+html.escape(visibility_text)+'</p>'+binding_text+
        '<details><summary>Источники и точность</summary><p>Каждый поток проверяется по хешу replay, '
        'контрольным суммам и завершающей записи. Порядок callback и номера записей разных потоков '
        'не определяют порядок игровых решений. Проверка целостности файла не заменяет проверку в клиенте.</p>'
        '<a href="replay-sources.json">Счётчики, версии, примеры и ссылки на записи</a></details></section>')


def mechanics_section(payload: dict | None) -> str:
    if payload is None:
        text='Поток собственных условий применения для выбранного аккаунта не предоставлен.'
    else:
        counts=payload['counts']
        text=('Обработано '+str(counts['projected_samples'])+' изменений собственного состояния; '+
              str(counts.get('raw_exact_linked_item_samples',0))+' записей содержат точную связь с объектом BKB. '
              'Условия применения остаются неизвестными до проверки механики соответствующей версии игры и часов. '
              'Заряды, контроль, фаза способности, цель и ограничения канала проверяются отдельно.')
    return ('<section id="mechanics"><h2>Условия применения</h2><p>'+html.escape(text)+
            '</p><details><summary>Почему готовность ещё не установлена</summary><p>Сырое значение кулдауна '
            'требует проверки его значения в этой версии игры. Наличие предмета и достаточная мана '
            'не устанавливают все условия применения. Изменение любого обязательного условия закрывает '
            'окно доступности; отсутствие данных сохраняется как неизвестность.</p>'
            '<a href="mechanics.json">Условия, ссылки на исходные записи и причины неопределённости</a></details></section>')


def movement_section(payload: dict | None) -> str:
    text=('Для расчёта подключения нужны проходимый маршрут соответствующей версии карты, '
          'текущая позиция, диапазон скорости и состояние контроля, доступные игроку в момент выбора. '
          'Эти данные для реального маршрута пока не предоставлены.')
    if payload is not None:
        bounds=payload['travel_duration_bounds']
        text=('Условия маршрута не установлены.' if bounds is None else
              'При сохранении указанных условий модель даёт диапазон времени движения: '+
              f"{bounds['minimum_ms']/1000:g}–{bounds['maximum_ms']/1000:g} с.")
        text+=' Фактическое прибытие и безопасность маршрута не установлены.'
    return ('<section id="movement-support"><h2>Подключение союзника и маршрут</h2><p>'+html.escape(text)+
            '</p><details><summary>Допущения расчёта</summary><p>Модель ищет путь по доступным рёбрам карты '
            'и учитывает ограничения движения и диапазон скорости. Время зависит от сохранения '
            'проходимости, скорости и контроля на всём маршруте. Новая угроза, столкновение или действие '
            'могут изменить эти условия. Без проверки обзора и угроз безопасность постановки варда неизвестна.</p>'
            '<a href="movement-support.json">Входные условия и результат модели</a></details></section>')


def defensive_impact_section(payload: dict | None) -> str:
    heading='<section id="defensive-impact"><h2>Активировать защиту или сохранить ресурс</h2>'
    if payload is None:
        return (heading+'<p>Для расчёта нужны известная до выбора угроза, её временной диапазон, '
            'механика предмета соответствующего патча и явная цель. Из эффекта BKB эти условия '
            'не восстанавливаются автоматически.</p><a href="defensive-impact.json">Состояние расчёта</a></section>')
    arithmetic=payload.get('candidate_arithmetic')
    if arithmetic is None:
        return (heading+'<p>Расчёт альтернатив недоступен: допустимые исходные условия не установлены.</p>'
            '<a href="defensive-impact.json">Причины отказа и источники</a></section>')
    labels={'activate':'Активировать','hold':'Удержать ресурс'}
    status={'robustly_meets':'Проходит заявленные ограничения','robustly_fails':'Не проходит заявленные ограничения',
            'uncertain':'Диапазон не устанавливает результат','infeasible':'Недоступно в заданной модели'}
    def interval(value):
        if value is None:
            return 'Не установлено'
        return html.escape(f"{value['minimum']:g}–{value['maximum']:g}")
    rows=[]
    for key,alt in arithmetic['alternatives'].items():
        rows.append('<tr><td data-label="Действие">'+html.escape(labels.get(key,key))+
            '</td><td data-label="Баланс HP">'+interval(alt['hp_after_impact'])+
            '</td><td data-label="Мана">'+interval(alt['mana_after_action'])+'</td><td data-label="Цель">'+
            html.escape(status.get(alt['goal_status'],alt['goal_status']))+'</td></tr>')
    timing={'full':'Защита покрывает весь заданный диапазон удара.',
            'partial':'Удар может попасть вне защиты; диапазон включает оба случая.',
            'none':'Заданный диапазон удара не пересекается с защитой.',
            'exempt':'Указанное исключение механики сохраняет исходное воздействие.'}
    assumptions_text={
        'one_committed_impact_no_other_damage_healing_or_regeneration':'Одно заранее известное воздействие; других источников урона, лечения и восстановления в модели нет.',
        'activation_and_hold_change_only_declared_mana_and_damage_multiplier':'Действия изменяют только указанный расход маны и множитель урона.',
        'declared_multiplier_fully_models_this_damage_tag_and_exemptions':'Указанный множитель и исключения полностью описывают этот тип воздействия.',
        'defender_item_and_threat_parameters_stable_until_impact':'Параметры героя, предмета и угрозы сохраняются до воздействия.'}
    assumptions=''.join('<li>'+html.escape(assumptions_text.get(v,v))+'</li>' for v in arithmetic['assumptions'])
    goal=arithmetic['goal']
    goal_text=html.escape(f"Заявленные пороги: баланс HP не ниже {goal['minimum_hp_after_impact']:g}; мана не ниже {goal['minimum_mana_after_action']:g}.")
    return (heading+'<p>Условный сценарий по предложенным исходным данным. Числа не подтверждают '
        'историческую механику, замеченную угрозу или правильность игрового решения.</p><p>'+goal_text+'</p>'
        '<style>@media(max-width:600px){.impact-alternatives,.impact-alternatives tbody,.impact-alternatives tr{display:block}'
        '.impact-alternatives thead{display:none}.impact-alternatives tbody tr{margin:16px 0;border:1px solid #496176;padding:8px}'
        '.impact-alternatives td{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;border:0;padding:8px}'
        '.impact-alternatives td:before{content:attr(data-label);font-weight:600}}</style>'
        '<div class="table-scroll"><table class="impact-alternatives"><thead><tr><th scope="col">Альтернатива</th><th scope="col">Баланс HP после одного удара</th>'
        '<th scope="col">Мана после действия</th><th scope="col">Заявленная цель</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p>'+
        html.escape(timing.get(arithmetic['timing_coverage'],'Перекрытие угрозы не установлено.'))+
        ' Отрицательный баланс HP означает дефицит в модели; это не прогноз фактической смерти.</p>'
        '<details><summary>Допущения и границы</summary><ul>'+assumptions+'</ul><p>Здесь нет новых '
        'вражеских действий, восстановления, иных источников урона или оценки исхода драки. '
        'Невыполнение явной цели в модели не является общим обвинением игрока.</p>'
        '<a href="defensive-impact.json">Все операнды, причины и ссылки на источники</a></details></section>')


def projectile_source_section(payload):
    heading='<section id="projectile-sources"><h2>Снаряды: исходные сообщения</h2>'
    if payload is None:
        return heading+'<p>Поток сообщений снарядов не предоставлен. Угроза до выбора не восстанавливается из последующего урона.</p></section>'
    counts=payload['callback_counts'];roles=payload['prefix']['selected_reference_association_counts']
    text=('Получено '+str(sum(counts.values()))+' сообщений создания, удаления и других изменений снарядов по всему матчу. '
        'Со ссылкой на выбранного героя в поле цели: '+str(roles.get('target',0))+', источника: '+str(roles.get('source',0))+'. '
        'Это сопоставления исходных ссылок; они не подтверждают попадание, входящий урон или замеченную игроком угрозу.')
    rows=''.join('<li>'+html.escape(kind.split('.')[-1])+': '+str(n)+'</li>' for kind,n in counts.items())
    return heading+'<p>'+html.escape(text)+'</p><details><summary>Сообщения и ограничения</summary><ul>'+rows+'</ul><p>Снимок сущностей может предшествовать обновлению того же пакета. Raw launch_tick не задаёт проверенное игровое время. Handle снаряда не является handle игровой сущности; удаление сообщения не устанавливает причину завершения. Видимость, внимание и историческая модель урона требуют отдельных источников.</p><a href="replay-sources.json">Полный источник, связи и границы</a></details></section>'


def unit_control_section(payload):
    heading='<section id="unit-control"><h2>Герой и связанные единицы</h2>'
    if payload is None:
        return heading+'<p>Исходный поток сущностей для этого разбора не подключён. Иллюзии и другие связанные единицы не сводятся к основному герою.</p></section>'
    cards=[]
    for graph in payload['snapshots']:
        units=[]
        for node in graph['nodes']:
            a=node['associations']; reasons=[]
            if a['selected_hero']: reasons.append('основной герой по текущему handle')
            if a['raw_player_id_equal'] is True: reasons.append('совпадает raw PlayerID')
            if a['raw_owner_player_id_equal'] is True: reasons.append('совпадает raw owner PlayerID')
            if a['raw_control_bit_set'] is True: reasons.append('установлен бит в raw mask')
            if a['raw_owner_path']['status']=='raw_handle_path_to_selected_hero' and a['raw_owner_path']['path']: reasons.append('цепочка raw owner handles')
            illusion=node['illusion_raw']
            if illusion is not None and type(illusion['value']) is bool:
                reasons.append('raw illusion: '+('true' if illusion['value'] else 'false'))
            label=f"{node['class_name']} · {node['entity_index']}:{node['generation']} · "+', '.join(reasons)
            units.append('<li>'+html.escape(label)+'</li>')
        cards.append('<details><summary>До записи '+str(graph['cutoff_record_index'])+': '+str(graph['associated_unit_count'])+' связанных единиц</summary><ul>'+''.join(units)+'</ul></details>')
    omitted=payload.get('anchor_selection',{}).get('omitted_anchors',0)
    omission='<p>По ограничению размера разобраны первые 128 границ; оставлено без проекции: '+str(omitted)+'.</p>' if omitted else ''
    return (heading+omission+'<p>Связи реконструированы до исходных записей защитных активаций. Это границы наблюдений, а не подтверждённые моменты выбора. '
        'Владелец, маска управления и основной герой показаны отдельно. Эти признаки не устанавливают доступность управления, видимость или внимание игрока.</p>'
        +''.join(cards)+'<details><summary>Источник и границы</summary><p>Используются точные поколения сущностей. Удалённый handle не связывается с новым юнитом того же индекса. '
        'Слот ресурса не принимается за PlayerID. Raw illusion не определяет тип клона; историческая семантика требует отдельной проверки.</p>'
        '<a href="unit-control.json">Графы, цепочки и ссылки на исходные записи</a></details></section>')
