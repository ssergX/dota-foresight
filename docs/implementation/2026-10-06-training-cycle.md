# Исполнимый цикл упражнения и подбора учебных задач

**Финальная интеграция:** доступны CLI `training`, выбор цели в Workbench, interactive journal с draft/notes/export и endpoint сравнения периодов. По умолчанию JSON import demotes `reviewed_issue` в unconfirmed, `verified_complete` в partial, `independent_observation` в unknown/null и `role_quality=verified` в user_declared: ссылки и status strings ещё не проверенные receipts. Trusted typed API для отдельно проверенных наблюдений остаётся отдельным интеграционным путём. Самостоятельная пользовательская цель доступна после её явного подтверждения, не требует выдуманного диагноза.

`learning/training.py` завершает локальный поток: подтверждённая цель → конкретное упражнение процесса → полный журнал возможностей → раздельные знаменатели baseline/followup → проверка сравнимости → описательное изменение поведения. Параллельно он сопоставляет выбранную задачу с конкретными source-backed эпизодами сильных игроков и показывает измеримое различие aggregate features. Это **не диагноз ошибки** и не допуск игрового evaluator.

## Входы и интеграционный API

```python
goal = load_training_goal(goal_json_text)
scope = load_training_scope(scope_json_text)
assignment = assign_exercise(goal, scope, review_match_count=3)
baseline = load_training_period(baseline_json_text)
followup = load_training_period(followup_json_text)
measurement = summarize_period(baseline)
progress = compare_training_periods(baseline, followup)
selection = match_study_to_goal(goal, target_match_json, account_id=account_id,
                                discovery=captured_discovery)
write_training_report(assignment, "out/my-training", baseline=baseline,
                      followup=followup, selection=selection)
```

`write_training_report` сохраняет открываемый `index.html` и `training.json`; период или подбор можно не передавать. Отсутствие журнала показывает «не измерено», а не completed/resolved. UI/CLI проекта интегрируются родительским исполнителем отдельно; этот модуль не изменяет `live_report.py` или CLI.

`TrainingGoal(goal_id, task_code, statement, origin, confirmation_refs=(), confirmed_at=None, issue_id=None, independent_review_refs=())`: origin — `user_confirmed`, `reviewed_issue` или `unconfirmed`. User-confirmed требует явного receipt человеческого выбора и timestamp; reviewed issue требует issue ID и independent review references. Импорт JSON проверяет контракты, но **не устанавливает аутентичность подтверждения или независимость reviewer**. Unconfirmed не получает назначения или персональных примеров. Ни user goal, ни произвольная external issue reference не включают live criterion admission.

Поддержанные конкретные задачи:

* `fight_entry`: перед добровольным подключением к драке записать задачу, наблюдаемый сигнал и две альтернативы; вынужденный бой исключить с причиной.
* `defensive_item_plan`: записать видимую угрозу, две альтернативы и tradeoff перед защитной покупкой; пересмотреть при изменении контекста. Никакой предмет не назначается автоматически.
* `vision_plan`: назвать ближайшее действие команды/необходимую информацию до установки; после эпизода записать реально полученное наблюдение или unknown. Срок жизни не quality score.
* `choice_alternatives`: один пользовательский повторяемый выбор — цель, доступные сведения, две альтернативы и неизвестные условия.

Три матча по умолчанию — **продуктовая review cadence**, не статистически достаточное N. Упражнение не должно задерживать необходимую реакцию: если запись сделана после эпизода, это надо честно сохранить в journal evidence. Текущий алгоритм не может проверить фактическое время человеческой записи без внешнего наблюдения.

`TrainingScope(subject_ref, hero_id, role, role_quality, patch, opponent_level_proxy, measurement_version='behavior-journal.v1')`: role quality verified/estimated/user_declared/unknown явная. Opponent proxy может быть provider rank tier, не числовой MMR. Unknown context запрещает delta progress. Одинаковые estimated/user-declared группы допускают лишь описание сопоставимых наблюдений, не аттестацию игрового качества.

## Журнал и знаменатели

`BehaviorOpportunity(opportunity_id, match_id, assignment_id, eligibility, behavior_completed, evidence_kind, evidence_refs, game_time_ms=None, reason_codes=())`. Eligibility: eligible/ineligible/unknown. `behavior_completed` — bool или null. Evidence kind: user_journal/independent_observation/unknown. Известное выполнение требует eligible opportunity и evidence; null не заменяется False. В журнал сохраняются также исключения/unknown, а не только успешные или неуспешные случаи.

`TrainingPeriod(period_id, assignment_id, scope, started_at, ended_at, match_ids, opportunities, coverage_status, coverage_refs, coverage_policy)`. Coverage: user_journal_complete/verified_complete/partial/unknown. Complete требует отдельной coverage receipt. Это supplied declaration: реестр/оператор обязан подтвердить происхождение; строка complete сама не доказывает обнаружение всех игровых возможностей. `coverage_policy` должен описывать одинаковый trigger/метод учёта в обоих периодах. Match IDs distinct, ledger opportunity IDs unique, все привязаны к assignment и period match set.

`summarize_period` возвращает considered matches/supplied opportunities/eligible/ineligible/eligibility unknown/behavior observed/completed/behavior unknown, completion rate **среди известных наблюдений**, coverage **среди eligible**, examples/counterexamples и explicit source kinds. Rate null при нулевом знаменателе. Это частота измеренного поведения, не probability/confidence и не win rate.

`compare_training_periods` выдаёт delta только при непересекающихся match sets и хронологических периодах, одинаковых assignment/scope/measurement/source/coverage policy и полном supplied учёте без неизвестной eligibility/behavior. Self-report имеет статус `comparable_self_report`; независимые наблюдения отдельно. Смена контекста/версии/метода требует rebaseline. Пустой followup или missing records — insufficient_evidence. Ни один статус не означает «ошибка исправлена» или причинный эффект тренера.

## Персональный task matching и измеримое различие

`match_study_to_goal` принимает typed `StudyDiscovery` от проверенного source adapter/load, фактический target raw match, account и подтверждённую цель. Target match исключается. Проверяются actual candidate player association, hero, точный provider patch ID, estimated role agreement, registered pro/high rank source и captured replay availability.

Task anchors выбираются из **соответствующих существующих source events**:

* fight_entry/choice_alternatives → teamfight pointers;
* defensive_item_plan → purchase_log entries ограниченного списка защитных предметов;
* vision_plan → obs_log entries.

Нет relevant event — кандидат исключается. Нельзя выдать teamfight за учебный эпизод защитной покупки или придумать карту варда. Это места просмотра, не доказанные decision boundaries, безопасность или успех действий.

Алгоритм измеримого различия использует source-backed GPM, last hits/min, deaths/10min, observer placements/10min, teamfight participation. Missingness остаётся null; сравнение минимум трёх общих из пяти features, иначе distance=null. Известный ноль сохраняется. Дистанция — среднее абсолютных разниц с открытыми scale constants `(500,10,5,5,1)`. Эти scales лишь приводят единицы к сопоставимому display range, **не обученные веса качества/стиля**. Кандидаты сначала упорядочиваются по наличию distance и coverage общих features, затем по distance и source ID; меньше полей не даёт ложного преимущества «нулевого сходства».

Каждый `StudyTaskMatch` сохраняет source refs/features/missing features/число общих измерений/viewing task и transfer differences. Если другой матч того же аккаунта, это явно отмечается: такой пример не независимый игрок. Сходство измерений не объявляется устойчивым стилем или доказательством tactical equivalence; team task/opponents/available knowledge остаются различиями. Goal user-confirmed — learning preference, не подтверждённая ошибка.

## Проверка и границы

`tests/test_training.py`: **21 passed**. Combined learning/source/ward/training: **100 passed**. Проверены assignment admission, неизвестность и полные знаменатели, source/journal distinctions, disjoint chronology/context/rebaseline, нулевой followup, strict JSON, task-specific existing source pointers, self-match exclusion, missing features, descriptive distance, report escape и report evidence output.

Данные реальных source candidates уже доступны в `out/study-live/discovery.json`: 9031046793 и9030693809. Для текущего пользователя нет подтверждённой личной задачи и journals. Поэтому **реальное персональное назначение/изменение поведения не сфабрикованы**. Пользователь может явно выбрать цель и вести журнал, а UI передаст реальные confirmation refs. Затем этот полностью исполнимый цикл считает данные без dependency на недопущенный evaluator. Самопротокол не заменяет независимую проверку игрового совета, реального trigger detection и coach efficacy.
