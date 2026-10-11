# Контракты данных и первый оценщик

Все структуры ниже — нормативная спецификация следующей реализации. Это не описание уже поддержанных полей и не готовая схема сериализации. Sol должен реализовать типы и strict validators, сохранив семантику; отклонения от информационных границ требуют повторной архитектурной проверки.

## 1. Общие типы

```text
SourceRef = {
  artifact_id, content_hash, provider, schema_version,
  locator: raw_event_id | json_pointer | frame/tick | video_interval,
  extraction_method, extractor_version
}
TimeRef = {
  replay_tick: int|null, sequence_in_tick: int|null,
  game_time_ms: int|null, uncertainty_ms: int|null,
  clock_mapping_version, order_status: verified|partial|unknown
}
EntityRef = { replay_id, entity_index, generation }
PlayerRef = { match_player_id, provider_slot, canonical_slot, mapping_evidence_ids }
Fact<T> = {
  fact_id, subject_ref, predicate, value: T|null,
  status: observed|derived|estimated|unknown|conflict,
  valid_at: TimeRef, observed_at: TimeRef|null,
  available_at: TimeRef|null, ingested_at_utc,
  perspective: world|team|screen|public,
  observer_ref: team_id|player_id|null,
  source_refs: SourceRef[], derived_from: fact_id[],
  method_version, freshness_policy_id, quality_flags: string[],
  unknown_reason: string|null
}
```

Инварианты:

1. `unknown → value=null + unknown_reason`; известный ноль разрешён. Пустой список означает доказанно пустое множество только при полной наблюдаемости; иначе требуется отдельный статус.
2. `observed` означает непосредственно извлечённое наблюдение, а не автоматически корректный парсер. Проверенность capability — отдельная ось.
3. `derived_from` образует ациклический граф. Доступность производного факта не раньше доступности всех входов. Итог агрегата не раньше закрытия окна.
4. Если интервал возможного `available_at` пересекает cutoff, факт не считается гарантированно доступным до выбора.
5. `estimated` никогда автоматически не повышается до `observed`, даже при многократном использовании.
6. Полевая perspective policy обязательна. Неизвестная policy запрещает перенос world fact в TeamKnowledge.
7. Entity ownership/controller и primary hero relation имеют время действия и evidence; player slot не является entity ID.

## 2. Manifest и capabilities

```text
ReplayManifest = {
  artifact_id, replay_hash, match_id + source_ref,
  game_build: value|null, patch: value|null,
  extractor_name/version, schema_version, timebase_version,
  completeness: complete|partial|unknown,
  covered_intervals, gaps, parse_warnings,
  capabilities: CapabilityStatus[]
}
CapabilityStatus = {
  capability_id,
  implementation: absent|implemented,
  validation: unverified|validated|regressed,
  scope: patch/build, entity_kinds, predicates, time_precision,
  evidence: corpus_version + test_run_ids + client_review_ids,
  limitations
}
```

Наличие поля в JSONL не ставит `validated`. Проверка одной версии/героя не распространяется автоматически на все патчи и сущности. Набор обязательных capabilities хранится у критерия; disabled criterion возвращает причину, а не пытается угадать поле из общих метрик.

| Capability | Текущий статус по коду | Что требуется для допуска |
|---|---|---|
| primary hero/player identity | Implemented, unverified | Raw mapping и клиент: 10 distinct героев/слотов, owner/clone/illusion cases |
| positions/resources | Implemented, unverified; missing defaults unsafe | Проверка единиц/координат/полноты/возраста, nullable reads |
| game clock и event order | Частичный, непроверенный | Паузa, pregame, game-start mapping, same-tick order |
| ward lifecycle | Implemented, unverified; reuse/pre-game defects | Generation, события до horn, censored removal |
| exact team visibility | Absent | Проверенный источник observed visibility; в противном случае только estimated |
| screen content | Не часть replay-контракта; видео опционально | Проверенное POV и выравнивание, OCR/распознавание отдельно аттестуются |
| inventory/abilities/control/casts | Absent в текущем replay schema | Поддержать выбранный whitelist, exact events + availability conditions |
| TP/buyback/smoke/objectives | Не полноценные replay capabilities | Каждая отдельный контракт; OpenDota logs не заменяют полное состояние |

Важный блокирующий вопрос: Go использует `int(m_iPlayerID)/2`, а старая спецификация описывает слот 0–9. Это противоречие надо проверить по raw fields реального replay; не исправлять формулу наугад. Аналогично проверять формат сжатия по magic bytes, а не по суффиксу URL.

## 3. Knowledge snapshot и граница времени

```text
KnowledgeSnapshot = {
  snapshot_id, subject_player, team, cutoff: TimeRef,
  facts: Fact[], observation_policy_version, manifest_id,
  last_seen: [{entity_ref, observed_fact_ids, seen_at, freshness,
               state: currently_observed|last_observed|never_observed|unknown}],
  screen_observation_ids: [], limitations: [], content_hash
}
DecisionBoundary = {
  boundary_id, opportunity_id,
  trigger_ref, choice_window: [earliest, latest],
  anchor: TimeRef|null,
  method: observable_trigger|action_commit|expert_annotation|unresolved,
  uncertainty, resolution_evidence_ids, resolver_version
}
```

`selection_time` (когда анализатор нашёл эпизод), `choice_window`, `anchor`, `outcome_window` — разные поля. Anchor описывает последний момент соответствующего выбора, не удобное время клипа. При unresolved boundary нет механического вердикта.

Для явного действия состояние фиксируется непосредственно перед соответствующей границей команды/активации, а ActionObservation является разрешённым объектом оценки. Команда, попытка команды, успешная активация и эффект — разные события. Если доступны только successful casts, нельзя говорить, что игрок не пытался нажать. Дальнейшее движение, урон и успех защиты не добавляются к входу под видом action token. Неизвестный порядок/семантика журнала ведёт к отказу.

Для отсутствия активации требуется наблюдаемое окно возможности и проверяемая граница его окончания, установленная по информации и механике в начале окна. Её нельзя ставить в момент последующей смерти. Наблюдение `observed_no_activation` не означает намерение сохранить предмет и не доказывает отсутствия попытки.

Общая модель окна — PolicyTrace: последовательность `(knowledge_prefix_at_step_start, local_action_observation, step_end)`. Каждый шаг оценивается только по своему разрешённому префиксу; конечный snapshot нельзя использовать для объяснения раннего выбора. Любое новое существенное наблюдение закрывает шаг и открывает новый. Discovery и boundary должны быть prefix-consistent: будущее не меняет уже установленные границы, лишь добавляет следующие шаги.

В v1 разрешён только один шаг с подтверждённой стабильностью значимых для сравнения предпосылок **до local action commit**, а для observed_no_activation — до deadline. Это не побитовое постоянство всех значений: предсказуемое изменение ресурсов/кулдауна допускается, если criterion явно подтверждает неизменность сравнения. Последствия собственной активации, включая потраченный ресурс и начавшийся cooldown, не являются причиной отбраковки положительного примера и не добавляют оснований вердикта. Триггер устанавливает начало и допустимый deadline; монитор проверяет полноту action log и изменения контекста. Существенное изменение до действия, неизвестная полнота, конкурирующие шаги или неоднозначный порядок дают abstention для оценки всего окна. Данные интервала могут только удостоверить action observation и пригодность шага; их нельзя добавлять как новые основания предпочтения действия в начале. До отдельного валидированного PolicyTrace evaluator многосоставные окна не оцениваются.

Для тестов разделять `knowledge_cutoff` в начале локального шага и `action_observation_end` (commit/deadline). Любые произвольные события после action_observation_end не меняют input/assessment. Изменение самого наблюдаемого действия внутри окна — другой объект оценки и не обязано сохранять verdict. При неизменном ActionObservation и admission-статусе факты после knowledge_cutoff не имеют права становиться новыми основаниями выбора. Эти исключения не разрешают evaluator читать World stream: подготовительный слой передаёт только типизированный ActionObservation и причины пригодности/отказа, не payload будущих событий.

Разрешённый интервал заканчивается до воздействия рассматриваемой угрозы и не содержит её результата. Если окно нельзя отделить от воздействия/неопределённости времени, класс неприменим для автоматического механического вердикта. Латентность ввода/реакции нельзя считать нулевой; неизвестное слишком короткое окно ведёт к отказу. Подтверждённое обвинение в отсутствии команды требует command-attempt coverage; журнал одних успешных активаций допускает только вывод о наблюдаемом неприменении и условный разбор, без утверждения о намерении/внимании.

Если boundary имеет интервал, оценка должна быть устойчива на всех допустимых срезах и порядках, необходимых критерию. Выбрать из интервала самый обвиняющий момент запрещено.

## 4. Opportunity, input и result

```text
Opportunity = {
  opportunity_id, match_id, player_id, decision_class,
  trigger_ref, boundary_id,
  eligibility: eligible|ineligible|unknown,
  eligibility_reason_codes, discovery_version,
  context_stratum, manifest_id
}
DecisionInput = {
  decision_id, opportunity_id, knowledge_snapshot,
  boundary, action_observation,
  goal_hypotheses: [{goal_id, source, support_ids, alternatives}],
  criterion_id/version, mechanics_scope
}
ActionCandidate = {
  action_id, description, scope,
  feasibility: feasible|infeasible|unknown,
  prerequisite_fact_ids, blocking_fact_ids, unknown_requirements,
  benefits: supported_claim_ids[], costs: supported_claim_ids[]
}
ActionObservation = {
  kind: command_attempt|accepted_command|activation_commit|observed_no_activation,
  action_id: value|null, observed_interval, event_refs,
  log_kind, log_completeness: complete|partial|unknown,
  coverage_evidence_ids, intent: unknown
}
Assessment = {
  assessment_id, decision_id, input_hash,
  applicability: applicable|not_applicable|unknown,
  verdict: good|reasonable_options|probable_error|
           confirmed_error_within_criterion|insufficient_evidence,
  criterion_id/version, criterion_scope, evaluator_version,
  action_evaluations, claim_ids, decisive_evidence_ids,
  uncertainty_reasons, abstention_reason_codes,
  evidence_grade, probability: null,
  frozen_at, assessment_hash
}
Claim = {
  claim_id, kind: fact|evaluation|hypothesis|exercise,
  proposition_code, arguments, evidence_ids, criterion_ids,
  scope: decision|outcome|descriptive,
  limitations, allowed_render_templates
}
OutcomeAnnotation = {
  decision_id, frozen_assessment_hash, outcome_window,
  observed_events, claims: outcome_only[], limitations
}
```

В DecisionInput запрещены: полные Match/World DTO; конечные score/deaths/networth; event summary, построенный после эпизода; нынешние hidden coordinates/HP; post-hoc severity; label эксперта, видевшего будущий outcome; свободные outcome-derived заметки. Стабильный opaque ID допускается для связывания, но не как прогнозный признак.

`good` требует положительного доказательства в ограниченном критерии; отсутствие найденного нарушения не повышает результат до good. `reasonable_options` требует аргументов хотя бы для двух выполнимых разумных действий. `confirmed_error_within_criterion` требует всех обязательных фактов, доказанного нарушения и рассмотрения существенных исключений. Существенно неизвестная цель, при которой вердикт меняется, запрещает безусловное обвинение.

Evidence grade описывает качество основания; он не является вероятностью правильности. Вероятности запрещены до независимой калибровки. Версии допускают повторяемость, но сами не доказывают точность.

## 5. Первый класс: защитная активация перед наблюдаемой угрозой

Рабочее имя: `defensive_activation.v1`. Конкретизация для спайка — BKB и **одна** способность-угроза. Имя способности и патч намеренно не выдуманы: их выбирают после проверки реальных событий и механик на доступных replay. Это открытый data gate, не разрешение считать любую способность угрозой или любую BKB полезной.

Почему этот класс: ограниченный action set, наблюдаемый триггер, возможность разделить техническую выполнимость и стратегическую цену сохранения ресурса. Приоритетные альтернативы — farm-vs-fight, билды и risky movement — требуют более широкой модели целей/карты/подключения и на текущих данных гораздо легче дают ложные обвинения. Выбор пилота условный: если нужную observability получить нельзя, выпуск остаётся dossier, а не переходит к более слабой эвристике.

**В области:** одно применение угрозы из whitelist и один стабильный шаг выбора; достоверно наблюдаемое окно, primary hero, известные собственные ресурсы и блокировки, поддержанный patch, отсутствие сложных неподдержанных взаимодействий. Альтернативы: применить предмет в проверенном окне; не применять в этом окне. «Сохранить» — возможная цель второго действия, а не установленное намерение. Уход/другая защита указываются как competing alternatives; если они могут изменить сравнение, но не оценены, безусловная ошибка запрещена.

Для реактивного пилота обязательна отдельная capability `reaction_cue_available_to_subject`: конкретный сигнал, канал (свой экран/звук/другой проверенный канал), начало доступности и временная погрешность. Общая team visibility недостаточна для обвинения в пропущенной реакции. Отсутствие этой capability разрешает только условный разбор командной информации. Подтверждённая доступность сигнала не доказывает внимание человека.

**Вне области v1:** универсальное «почему не BKB», нескольких угроз без проверенного порядка, восстановление намерения по смерти, обещание выживания, точные проценты win chance, неизвестные reset/refresh/control interactions, неподтверждённая возможность реакции. Нельзя скрыть эти случаи в среднем качестве пилота.

### Алгоритм

1. Проверить manifest, identity, patch и capabilities. Если не прошли — `insufficient_evidence` с конкретными причинами; criterion disabled не маскировать отсутствием эпизодов.
2. Найти **все** наблюдаемые начала угрозы в поддержанном scope, независимо от последующей смерти/успеха. Сохранить eligibility и причину исключения каждого кандидата.
3. Построить окно выбора из проверенной механики и наблюдаемого префикса. Проверить доступность конкретного reaction cue субъекту, полноту action log и стабильность единственного шага. При изменении существенного контекста, неопределённости порядка/видимости/возможности реакции — отказ v1.
4. Сформировать KnowledgeSnapshot. Проверить каждую предпосылку доступности применения: ownership, slot/state, cooldown, charges/resources при применимости, disable/control restrictions и другие обязательные поля выбранной механики. Список условий задаёт проверенный mechanics registry; `ready=true` не заменяет его.
5. Построить activate/hold и допустимые конкурирующие альтернативы. `infeasible activate` не означает ошибку hold. `feasible activate` тоже не означает ошибку hold.
6. Проверить цель/издержки сохранения и criterion rubric. При нескольких разумных вариантах вывести их. При неизвестной существенной цели — условный разбор либо insufficient, а не диагноз внимания.
7. Выдать Assessment и минимальные claims, заморозить hash. Затем отдельно присоединить outcome.
8. Выдать одно упражнение, связанное с доказанным условием выбора, например проверку нужного собственного ресурса при **подтверждённо распознаваемом** триггере. Не советовать реакцию на сигнал, которого игрок не мог получить.

### Какие данные нужны до включения

- Реальные replay выбранного patch/build с существующими match IDs и legal access, желательно полный демо-файл, а не только агрегаты.
- Запись клиента с перспективой команды и проверкой времён/видимости; для реактивного вывода — доказанная доступность конкретного сигнала субъекту, из POV или другого проверенного источника. Без своей POV нельзя утверждать, что игрок увидел сигнал глазами; даже с POV нельзя утверждать внимание.
- Raw property/event traces для предмета, угрозы и всех ограничений применения.
- Проверенные patch-scoped источники механики и набор пограничных случаев в клиенте. Никакой универсальной формулы взаимодействия BKB здесь не заявлено.
- Экспертный rubric: основания предпочтения activate/hold, исключения, конкурирующие цели. Исход скрыт на стадии оценки.

### Первый законченный результат до data gates

Evidence dossier: эпизод/интервал, имеющиеся наблюдения, источник каждого факта, явные пробелы, доступный клип и причина невозможности оценить. Verdict — insufficient_evidence, а не «нейтрально, но ты ошибся». Это полноценная законченная поверхность проверки данных, **не** подтверждённый анализ качества решений. После прохождения gates тот же контракт и UI получают работающий evaluator без переписывания всей цепочки.

## 6. Контракты для расширений

| Сущность | Обязательные поля |
|---|---|
| HabitEvidence | habit_id, criterion/context scope, example и counterexample decision IDs, eligible/assessed/unknown counts, sampling policy, период, patch/role/hero качества |
| CoachingPlan | habit_id, trigger condition, exercise, measured behavior, baseline IDs, target policy, review window, guardrails против нежелательного поведения |
| ProgressObservation | два периода/наборa IDs, comparability decision и причины, counts/rates/uncertainty, версии; никакого resolved из отсутствия сигнала |
| StudyMatch | verified match/source/link, checked_at, pro/high-MMR status + source, patch/hero/role, replay availability, episode refs, similarity features, learning task, transfer limitations |
| BuildPlan | knowledge snapshot, goal hypothesis, threats with evidence, options/tradeoffs, mechanics refs, revisit conditions, descriptive statistics отдельно |
| WardDecision | instance ID, placement boundary, team-task hypotheses, placement feasibility, information geometry quality, alternatives, later information outcome отдельно |
| Feedback | feedback_id, decision/assessment/version, user answer, supplied goal, created_at, review status; immutable original analysis |

Эти контракты не обещают автоматический подбор или расчёт, пока конкретные источники/критерии не подключены.
