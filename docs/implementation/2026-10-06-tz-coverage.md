# Покрытие исходного ТЗ Foresight: проверка по обязанностям

**Актуальная итоговая матрица 8 октября:** [закрытие доступного первого этапа и границы полного продукта](2026-10-08-tz-closure.md). Таблицы ниже сохраняют исторический аудит; сведения об отсутствии raw command joins, адаптера механических условий и модели маршрута обновлены в итоговой матрице. Количество и результат финальных проверок находятся в `out/verification/release-readiness.json`.

Последнее исполнение: [replay-source stage](2026-10-07-replay-source-stage.md). R01/R05/R06/D02–D04 расширены фактическими prefix operand deltas и raw spectator orders; R11 — optional event visibility. Эти потоки не устанавливают complete attempts, continuous truth, real FoW или экранную доступность. Утверждения ниже «raw extractor отсутствует» уточнены этим обновлением; соответствующие игровые capabilities остаются partial/external validation.

Предшествующее исполнение: [continuous/command stage](2026-10-07-continuous-command-stage.md) расширяет D02–D04/R07 conditional span reconstruction и exact command census. В тот момент raw extractor ещё отсутствовал; replay-source stage выше закрывает извлечение raw сообщений и operand deltas, но не собственных attempts/stages, cues и игровых truth transitions. Полный game opportunity census и validated rubric остаются открытыми. Числа тестов далее фиксируют предыдущие этапы.

Аудит начат 6 октября и актуализирован **8 октября 2026 года**, во время продолжающейся реализации. Источник требований: исходное вложение `Вставленный текст.txt`, attachment `72ab3159-89a5-4b5f-aec0-83a7e8af1ee6`. Это проверка исполнения, а не декларация готовности всех функций. Прочитаны текущие `src`, Go extractor, tests, архитектурный пакет и фактические артефакты `out`.

**Главный результат:** evidence dossier, строгие информационные границы, экспериментальная арифметика сравнения и вычисляемые условия choice feasibility заданы исполнимым кодом. **Проверенная оценка реального игрового решения пока не реализована сквозным алгоритмом.** Старый experimental evaluator принимает boolean prerequisites и utility bounds; новый `choice_window.py` вычисляет конечный набор механических условий из exact operands и требует отдельного reviewed binding. Проверенных bounds стратегического критерия из реального replay/POV пока нет. Отказы в report не закрывают требование полезного разбора и упражнения.

Актуальное продолжение: [choice/knowledge/ward stage](2026-10-07-choice-knowledge-ward-stage.md), **939 Python tests, 9 Go tests**. R06/D03/D04 — partial с sample-level вычислениями; R11/F05 — partial с TTL/conflict projection typed наблюдений; R16 — partial с source-local objective history; W04–W08 — partial с independently bound supplied attribution. Real extraction, continuous census, navigation/geometry и игровые критерии перечислены отдельно от этих алгоритмов.

Статусы: `implemented` — конкретное локальное поведение есть и проверяется; `partial` — реализована только часть требуемого алгоритма/потока; `missing` — необходимого исполнения нет; `external_validation` — код/источник есть, но требуемая проверка по клиенту, экспертам или пользователям не выполнена. Для `external_validation` нельзя делать соответствующий положительный продуктовый вывод. Ссылки на tests устанавливают проверку контрактов/веток, если явно не указано реальное свидетельство.

## 1. Пользовательский результат и аналитическая цепочка

**7 октября — финальное расширение доступного этапа:** R13/R15 теперь имеют source-local apply/remove fold и честные censored/ambiguous intervals; D02 частично исполняется как census всех supplied own-inventory samples, а не только cast rows. Семь наблюдаемых сырьевых окон не устанавливают полный census игровых возможностей. Раздел вардинга принимает собственную текущую задачу, сохраняет revisions и выдаёт шесть конкретных проверочных вопросов из original prefix. Неизвестные безопасность/обзор/альтернативы не превращаются в полезность. Исправлены cooldown semantics, future metadata leak и identity/revision проверки качества: `2026-10-07-remaining-analytics-stage.md`. Недостающие данные и алгоритмы: `2026-10-07-external-validation-inputs.md`.

**7 октября — дополнительный этап:** R13–R16 имеют прямые sourced markers и отделённую ретроспективу; full lifecycle/visibility остаются partial. U/Q включают рабочую слепую форму разметки с атомарным приёмом revisions. G04/G06 дополнены планом запаса в собственной карточке: пользовательские допущения сохраняются отдельно от прошлого намерения и игровых вердиктов. Исполнение и оставшиеся coding gaps: `2026-10-07-semantic-review-stage.md`.

**7 октября — план покупки:** B01–B04/U07 дополнены вводом явной цели/контекста, привязкой к собственному source prefix, выбранными предметами, арифметикой остаточных расходов и пересмотром сценария. Saved revision/hash/date и reload доступны через локальный backend. Это исполнимое исследовательское сравнение, не verified threat→item registry, не доказательство feasible purchase и не optimal individual build. Подробности: `2026-10-07-contextual-build-plan.md`.

**Актуализация перед внешними тестами.** Следующая таблица сохраняет историю первоначального аудита; финальные изменения перечислены здесь и в `2026-10-06-test-handoff.md`. G04/R05/R06 теперь имеют исполнимый own-prefix handle/generation→raw fields→candidate checks→resource arithmetic путь (`ingest/action_state.py`, `decisions/resource_review.py`), а не только boolean slots. Full feasibility остаётся unknown до control/clock/patch/command validation. G05/D10 дополнены `declared-mana-reserve.v1`: модель сама считает ресурсное ограничение, источник стоимости связан с action, факт/граница/цель/admission проверяются отдельно; это research, не validated стратегический вердикт. C05/C08/C09/U06/S04–S07 имеют сквозной self-directed training/task matching/journal/progress UI+CLI. Диагноз confirmed habit и устойчивое сходство стиля остаются неустановленными. U12 queue/parsing/error/loading работает в локальном Workbench. Q/P delivery включает чистую установку wheel, source archive audit и Windows/Linux CI; GitHub CI ещё не выполнен. Функциональная реализация не заменяет внешние проверки.

Обновление после сквозной интеграции: `decisions/trace_episode.py`, `live_report.py`, `server.py`, `validation/trace_pack.py`, `validation/fact_quality.py` и `learning/contextual.py` исполняют реальные activation notebooks, editable goal contract, source-backed research alternatives, работу с очередью/ошибками и раздельные quality passes. В `out/real-review` получены 5 активаций, 262 ward events, 2 внешних учебных примера и профиль публичного аккаунта. G03 теперь partial, S01/S08/UI integration реализованы; C02 теперь partial (полная пятёрка rank tiers как явно обозначенный proxy, иначе unknown); C03 расширен resource/participation/item preference features; Q12 реализует consensus factual-error report. Эти обновления не закрывают D10/D11/D13, client validation или benefit/progress.

| ID | Конкретная обязанность | Статус | Исполнение / свидетельство | Что ещё требуется |
|---|---|---|---|---|
| G01 | Установить конкретный выбор игрока | partial | `decisions/contracts.py`, `dossier.py`; `test_dossier.py`: death остаётся incident/unresolved | Реальный trigger/discovery и независимая граница выбора; вместо постоянного unresolved найти хотя бы один supported класс |
| G02 | Установить доступную в тот момент информацию | partial | `evidence/knowledge.py`: projection собственных полей; `test_evidence_boundary.py`; чужая информация неизвестна | Проверенная наблюдаемость/last-seen и доступность сигнала конкретному субъекту; inventory/control до cutoff |
| G03 | Указать возможную цель и альтернативные интерпретации | partial | `trace_episode.py` содержит гипотезы; `contextual.py` typed GoalHypothesis/GoalFeedback/revise_goal сохраняет происхождение и revisions | Проверить реальные prior goals и sensitivity вердикта; гипотеза не установленное намерение |
| G04 | Установить реально доступные действия | partial | `ActivationInput` принимает boolean activate/hold feasible; `ActionCandidate` различает unknown | Извлечь и проверить cooldown/mana/inventory/control/range и competing alternatives; переданный boolean не алгоритм feasibility |
| G05 | Объяснить разумность/спорность/ошибочность выбранного действия | partial | `decisions/evaluator.py`: bounded dominance; `test_activation_engine.py` | Проверенный игровой rubric, получение bounds/цен альтернатив и исключений из источников; live criterion admission |
| G06 | Предложить конкретное изменение поведения для следующих матчей | partial | `learning/habits.py`: gated CoachingPlan; `test_learning_modules.py` | Реальные повторяющиеся validated assessments, релевантный trigger/exercise, проверка полезности и поведения |
| G07 | Поддерживать хорошие решения и несколько разумных вариантов | partial | Экспериментальные good_decision/reasonable_alternative; bounds/floor tests | Реальная positive discovery, правильность acceptable floor, examples с плохим outcome |
| G08 | Различать вероятную и подтверждённую в пределах критерия ошибку | partial | Validation/habit contracts имеют оба label; experimental mistake маппится в probable_error | Реальный критерий confirmed_error с обязательными evidence/exceptions; evaluator не выпускает validated confirmed_error |
| G09 | Не требовать ошибки в каждом эпизоде | implemented | Dossier abstention, evaluator good/options/not_actionable; tests не требуют mistake | Проверить comprehension пользователей; это не доказывает полезность abstention-only на реальных данных |
| G10 | Явно показывать ограниченный охват | implemented | Manifest/capabilities, report reasons; batch population coverage=null | Добавить реальную opportunity census для измеримого охвата выбранного класса |
| G11 | Связать Replay→facts→choice→actions→claims→plan | partial | Модули ingest/evidence/decisions/learning/validation существуют | Соединить реальный trace с admissible input и validated HabitEvidence; сейчас trace и batch — разные ветки |
| G12 | LLM объясняет только проверенные claims | partial | `explain_evaluation` deterministic templates; legacy LLM не вызывается при dossier | Controlled ClaimSet adapter/validator для LLM, если LLM вообще включается; свободный старый provider нельзя возвращать без проверки |

## 2. Аудит и сохранение полезного кода

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| A01 | Прочитать инструкции, код, tests/docs; разделить существующее и обещанное | implemented | `docs/architecture/2026-10-05/01-audit.md`, source snapshot, probes; этот traceability audit | Повторить независимый review финального diff после текущих параллельных изменений |
| A02 | Сохранить полезные части проекта | implemented | Сохранены Python/Go/CLI/static HTML, ingest OpenDota, video alignment/clips | Проверить интеграцию на реальных входах; отсутствие переписывания само не качество |
| A03 | NETWORTH_SWING не автоматический MISTAKE/HIGH | implemented | `scoring.py`; `test_scoring.py`, anti-resultism tests | Swing остаётся outcome navigation, нельзя вновь включать его в evaluator |
| A04 | Не считать radius-видимость точной и не выдавать hidden truth через grounding | implemented | `coach/info_state.py`, `evidence/knowledge.py`; `test_info_state.py`, boundary tests | Exact visibility отсутствует; approximation годится только для ограниченного retrospective UI |
| A05 | Не подменять выбор состоянием смерти | implemented | `dossier.py`, `episode_card.py`; `test_dossier.py` | Incident snapshot не становится decision anchor; требуется реальный resolver |
| A06 | Устранить противоречие severity t−5 и death snapshot | implemented | `episodes.py`; `test_episodes_deaths.py`, `test_episodes_deep.py` | Другой fixed offset не должен появиться в mechanical criteria |
| A07 | Устранить предел секундных replay slices | partial | Новый `replay_tool/trace.go`, `ingest/trace.py` сохраняют event records/fields | Clock/sub-tick order/field semantics не валидированы; downstream dossier всё ещё sampled, не event-ready evaluator |
| A08 | Агрегатные перцентили не сравнение решений | implemented | `benchmarks.py` остаётся описательным, prompts/reports не утверждают matched decisions | Сам алгоритм сравнения решений в похожих допустимых состояниях отсутствует |
| A09 | Ручные leak thresholds не доказанная ошибка стиля | implemented | `_common.py`, registry/report: LOW descriptive signals; `test_leaks_registry.py` | `leaks/roles.py` остаётся эвристическим; оценка роли и стиль требуют отдельной валидации |
| A10 | Исчезновение детектора не resolved | implemented | `coach/progress.py`, `test_coach_progress.py`, history revision tests | Реальный comparable habit progress пока нет |

## 3. Факты, доступность и защита от знания будущего

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| F01 | Для значимого факта сохранять источник | implemented | `evidence/contracts.py`: SourceRef/Fact; hashes/locators в report | Расширить provenance до каждого semantic события нового trace; raw field наличия недостаточно |
| F02 | Сохранять время и качество факта | implemented | TimeRef uncertainty/order/clock version; Fact statuses/flags | Реальная точность tick/clock отдельно не установлена |
| F03 | Сохранять гарантированную доступность субъекту до cutoff | partial | `definitely_available_before`, allowlists; `test_activation_engine.py` same-tick/future tests | Семантика реального available_at для visibility/cue ещё не извлекается |
| F04 | Неизвестность не превращается в 0/False | implemented | Nullable parser/models/projector; `test_replay_foundation.py`, Go null tests | Следить за legacy normalized counters; отсутствие optional raw metric должно сохраняться при profile |
| F05 | Разделить World и TeamKnowledge | partial | World поля не допускаются в ActivationInput; own projection в Knowledge | Полноценный observation stream TeamKnowledge не реализован; broad stream остаётся world |
| F06 | Отдельно учитывать экран/звук игрока | missing | Контракт screen cue требует observer; video alignment существует | Real POV/audio capture/sync и cue detection; собственные world resources не доказательство внимания |
| F07 | Не выводить намерение/внимание из действия или отсутствия команды | implemented | ActionObservation без intent, complete log requirement; noactivation tests | Goal/attention hypotheses как отдельная review-сущность ещё не реализованы |
| F08 | Не смешивать team visibility с игрок заметил | implemented | `screen.reaction_cue` не принимает team perspective; tests | Никакой real cue capability не аттестован |
| F09 | Evaluator не получает hidden enemy/future outcome | implemented | Pure allowlisted ActivationInput/DecisionInput; anti-resultism/metamorphic tests | Ещё требуется проверить semantic derived inputs/bounds/trigger selection на real corpus |
| F10 | Полные данные результата держать отдельно | implemented | Dossier outcome/incident branch отдельно от input; assessment hashes | Более богатая OutcomeAnnotation не интегрирована; формальный hash не доказывает causal purity derivations |
| F11 | LLM не придумывает факты, альтернативный outcome и проценты | implemented | Current explanation templates, LLM ignored regression; probability не выпускается | Проверять любую будущую LLM integration на entailment отдельно |
| F12 | Факты/границы инвариантны при изменении будущего | partial | Knowledge/ward prefix и forbidden-field tests | Реальный discovery и derived rubric prefix consistency не проверены, т.к. ещё нет алгоритма |

## 4. Replay foundation: отдельные требуемые capabilities

Реальный файл уже получен: `out/real-data/9030822324.dem`; receipt `replay-9030822324.receipt.json`: raw **126864874 bytes**, SHA-256 `55d582de8fc9eb85d51becf0c38c28522f1277701e4bad8f053d1c0d7f6e9b47`, transport/hash only, client validation not performed. Суффикс URL `.bz2` фактически содержит zstd: magic-based decompression нужна и используется. Старый `2026-10-05-completion.md` тезис об отсутствии `.dem` больше не актуален; отсутствие client/expert validation остаётся актуальным.

| ID | Capability / обязанность | Статус | Исполнение / свидетельство | Недостающий алгоритм/проверка |
|---|---|---|---|---|
| R01 | Player/primary hero identity | external_validation | v3 resource selected hero handles; `trace.go`, trace parser; legacy mapping unverified | Join resource slots с provider player_slot/account на всех 10 героях; raw/client сверка |
| R02 | Иллюзии/clone/подконтрольные сущности и ownership | partial | Raw Owner/Illusion/Clone/Control поля сохраняются | Временные owner/controller/primary relations, generation cases, summons/Meepo/Arc и client proof |
| R03 | Позиции/HP/mana/уровни/XP | external_validation | Nullable fields и coordinates reconstruction; реальный trace записывается | Units/scale/field ages/tick completeness проверить по клиенту; не аттестовано |
| R04 | Экономика в момент выбора | partial | OpenDota gold_t описательные; Go trace сохраняет Gold fields | Exact spendable gold/networth/inventory values, availability/missingness до cutoff |
| R05 | Предметы и способности | partial | Raw item/ability entity fields и hero item handles сохраняются | Handle resolution→semantic identity, slot/facet/charge ownership timeline, actual supported item whitelist |
| R06 | Cooldown/charges/mana/control feasibility | partial | `choice_window.py` вычисляет конечный набор operand constraints: generation, mana/cost, slot, control mask, cooldown interpretation, charges, range/target; exact review binding | Полные silence/stun/mute/channel/command rules, historical mechanics и client validation; conditional research ≠ real cast certification |
| R07 | Касты и этапы попытка→accepted→commit→effect | partial | Raw combat logs и LoggedAction ability/item | Привязать actor/target/items к entities; command attempt coverage; определить stage/sequence без выдумки |
| R08 | Контроль/модификаторы | partial | Go raw modifier/game-event stream | Интервалы статусов, active effects и restriction semantics, completeness; verified observations отсутствуют |
| R09 | Урон и смерти | partial | Sampled alive transitions, combat death logs, OpenDota tf stats | Exact damage/death semantic events с attribution и clock; клиентная сверка; не selection→mistake |
| R10 | Actual team visibility | missing | Возможные Visible/FoW raw properties сохраняются, approximate circles отдельно | Валидировать meanings/bitfields/team observer, terrain/tree/elevation; typed observation stream |
| R11 | Enemy last-seen история | partial | `evidence/temporal.py`: typed availability/TTL, late-delivery ordering, last-known/stale/conflict, entity bindings | Настоящий visibility extractor и client/POV проверка; last-known не current visibility |
| R12 | Ward lifecycle | external_validation | Generation/pregame/prefix/censoring; `wards.py`, parser tests | Real entity create/delete/map coordinates сверить; отличать removal reason/placement unobserved |
| R13 | Телепорты | partial | `semantic_events.py`: прямые TP use/modifier apply/remove markers с source-local refs; report/prefix API | Channel outcome, interrupt/arrival, target/feasibility; удаление modifier не устанавливает причину |
| R14 | Buyback | partial | Combat log type12 сохраняется LoggedAction | Время/actor/economy/cooldown/availability и own-visible semantics; не аттестовано |
| R15 | Smoke | partial | `semantic_events.py`: use/apply/remove markers отдельно по trace/sidecar; source-local prefix API | Smoke-break cause, actual observation/visibility и feasibility; raw removal не доказывает раскрытие врагом |
| R16 | Линии, здания, objectives | partial | `objective_state.py`: source-local building/Roshan/buyback markers, temporal bounds, unknown ownership/respawn | Exact lane/map ownership, source availability и historical patch geometry |
| R17 | Patch/parser/schema version | partial | Manifest schema/parser, provider patch ID60; game build footer, Valve snapshot version | Доказанный build↔patch mapping; не подставлять live catalog в исторический матч |
| R18 | Exact event time для механики | external_validation | Trace record_index, net_tick, callback sequence, combat timestamps | Callback order не simulation sub-tick order; game clock/pause offsets/uncertainty сверить, не автоматически verified |
| R19 | Наличие raw field не даёт validated capability | implemented | Parser всегда implemented/unverified; experimental scope cannot validated switch | Реестр независимого grant и corpora evidence, если потребуется production admission |
| R20 | Реальная client verification видимости | external_validation | Protocol в `docs/data-spike/defensive-activation-v1.md`; реальный демо уже доступен | Провести client/POV comparisons; данных такой проверки нет |

## 5. Оценка решений: что ещё не является игровым алгоритмом

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| D01 | Один ценный ограниченный decision class | partial | Выбран defensive_activation.v1; typed ActivationInput | Конкретные item/ability/patch ещё не допущены; нужна выбранная пара и реальная исполнимая рубрика |
| D02 | Discovery всех supported opportunities | partial | `opportunity_discovery.py` обходит все supplied own-inventory samples с prefix identity; 2999 samples/7 raw windows, game coverage=null | Реальный cue/choice opportunity trigger и полный census пригодных возможностей, включая хорошие решения и unpunished errors |
| D03 | Choice window/anchor с evidence | partial | `choice_window.py`: possible/guaranteed cue intervals, uncertainty, pause/expiry, exact review binding | Настоящий screen cue extractor, commit/deadline semantics и проверка на client/POV corpus |
| D04 | Stable step и время реакции | partial | Sample-level feasibility пересчитывается при изменении control/generation/resources; прежние samples invariant; reaction policy explicit research | Continuous stable-step monitor, validated latency/minimum action window и complete attempt log |
| D05 | Known context и competing goal hypotheses | missing | Allowlist own facts есть | Командная задача/цель, видимые угрозы, переносимые evidence и sensitivity to goal |
| D06 | Feasible alternatives и arguments pro/con | partial | Experimental activate/hold values, ActionCandidate unknown | Отдельные уход/иная защита/сохранение ресурса с costs/tradeoffs; rubric bounds не могут быть свободными числами |
| D07 | Unknowns и основание verdict | implemented | Reason codes, claims/evidence IDs, admission refusal | Семантическая полнота decisive evidence проверяется только после real criterion |
| D08 | Outcome отдельно и без hindsight обвинения | implemented | Dossier/experimental input separation; tests | Real input assembly должен сохранить invariance |
| D09 | Смерть/выжил/BKB ready/damage/ward count/rare action не одиночный verdict | implemented | Legacy signals descriptive, only bounded comparative criterion | Проверить real pilot не заменяет utility готовностью BKB; отсутствует opportunity algorithm |
| D10 | Ally support: resources/connectability/movement restrictions | missing | Legacy positions могут показываться retrospective | Feasibility of ally arrival/TP/channel and available knowledge; distance≠arrival time |
| D11 | Удачные решения и ошибки без наказания | missing | Математический evaluator умеет good, но incident index outcome-based | Реальный complete supported discovery, positive/unpunished examples и holdout |
| D12 | Не выдавать корреляцию за alternative causal outcome | implemented | Нет counterfactual win%/gold cost; deterministic bounded caveats | Reliable alternative model не реализована; если появится, отдельно валидировать assumptions |
| D13 | Проверенный критерий live good/probable/confirmed error | missing | CriterionScope допускает лишь disabled/experimental; validation_status unverified | Real extraction + rubric + independent holdout + release grant; green tests не закрывают |

## 6. Персональный профиль, привычки, обучение и progress

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| C01 | История с hero/role/patch/data quality | partial | `profile.describe_series`; `test_profile.py`; measured/considered medians, группировка | Real validated roles, patch join, temporal sample quality и migration signatures |
| C02 | Учитывать уровень соперников | partial | `profile.py` группирует полную пятёрку известных opponent rank tiers как явно обозначенный median proxy; иначе unknown | Числовой MMR/реальная сила не выведены; нужны validated strength context и история качества источников |
| C03 | Стиль: риск, движения, ресурсы, team involvement, item preference | partial | GPM/XPM/deaths/wards/stacks median; purchase sequence | Operational risk/movement/resource/participation descriptors с opportunities; текущие medians не полный style model |
| C04 | Не устойчивый ярлык по одному матчу, не агрессия=ошибка | implemented | Profile descriptive, no stable style labels; unverified sources | Human comprehension и validity style descriptors отдельно |
| C05 | Условия каждой привычки | partial | Habit criterion/role/patch; gating | Concrete trigger/task/context stratum beyond criterion name |
| C06 | Подтверждённые примеры и контрпримеры | partial | HabitEvidence example_ids/counterexample_ids; tests | Реальные independently validated examples; сейчас receipts могут быть только supplied registry declarations |
| C07 | Frequency относительно eligible opportunities | partial | eligible/ineligible/assessed/unknown и coverage разделены | Actual complete opportunity discovery; caller tuple не доказывает полного census |
| C08 | Конкретное упражнение/attention rule | partial | `training.py`: явная цель → task-specific self-directed exercise и журнал | Упражнение от validated issue, проверка побочных эффектов/полезности; диагностическое назначение закрыто |
| C09 | Проверка в следующих матчах | partial | CLI/UI journals: dates/windows/disjoint IDs/scope/source/coverage gates и descriptive delta | Реальные complete opportunities и independent measured behavior; user behavior pilot отсутствует |
| C10 | Не resolved из исчезновения/смены роли/данных | implemented | Legacy progress + Habit progress gates/rebaseline; tests | Не смешивать изменения detector/coverage с progression |
| C11 | Feedback/expert corrections/model versions без self-learning | partial | `feedback.py`, browser export; `validation/contracts.py` annotation revisions | Reviewer identity/provenance and model/rubric registry; manual adjudication workflow/promotion absent |
| C12 | Обновления проходят независимую проверку | external_validation | Release gate deliberately not evaluated; blind pack tooling | Actual independent reviewer(s), sealed holdout и reviewed deployment policy |

## 7. Источник учебных матчей и контекстное обучение

Реальное свидетельство: `out/study-live/study-source.json`, `smoke-receipt.json`; match **9030822324**, hero **145**, account **904131336**, source hash/checked times, registry pro account, position_1 **estimated**, patch provider ID60, первый TF413с. Этот source smoke не является рекомендацией целевого матча самому себе. Для рекомендаций нужно исключить target match и получить альтернативные source-backed examples.

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| S01 | Подключённый источник существующих матчей | implemented | `ingest/study_sources.py`, CLI study/trace-review, live_report и local workbench; checked GET/TTL/hash/cache, actual ID/hero/account validation, реальные внешние примеры | Context-task matching и независимая проверка преподавательской ценности остаются отдельными требованиями |
| S02 | Герой и роль сходны | partial | Hero association exact, role_estimate openly estimated | Verify role source/annotations; role estimate не выдавать за verified match suitability |
| S03 | Релевантный патч | partial | Strict provider patch ID filtering | Historical mapping и transfer scope; exact provider ID не mechanics proof |
| S04 | Сопоставимые игровые задачи | partial | `training.py`: goal/task matching выбирает actual fight/purchase/ward pointers | Validated team-task suitability и самостоятельная преподавательская проверка |
| S05 | Измеримое сходство стиля | partial | Descriptive feature distance GPM/LH/deaths/wards/participation с missingness/scales | Проверенная устойчивая style metric и context controls; расстояние не доказывает сходный стиль |
| S06 | Подбор под конкретную проблему пользователя | partial | Явная learning preference связана с task episodes; target match исключён | Confirmed habit→criterion/task и проверка индивидуальной пользы; preference не диагноз |
| S07 | Зачем этот матч, какие эпизоды, transfer differences | partial | Real tf/purchase source refs + concrete time-based task/limitations | Episode-specific supported teaching hypothesis; task/style matching, not generic lookup only |
| S08 | Проверенные ID/links/source receipts | implemented | Actual API ID checks, URL association, hash/time; untrusted local import demoted | UI must retain receipt and source check age; online URL existence may later expire |
| S09 | Pro отдельно от high-MMR | partial | `registered_pro` via proPlayers; `high_rank` proxy explicitly not numeric MMR | Actual numeric/high-MMR cohort source if claimed; current rank80 alone нельзя назвать проверенным MMR |
| S10 | Replay unavailable/unknown explicit | implemented | Valve range header probe; 404/410 vs unknown; tests SSRF/network/HTML | Complete download/playability separately checked; prefix-only не full file validation |
| S11 | Нет fabricated unavailable-source recommendations | implemented | Import verified/pro/real демотируется; empty catalog unavailable | Source adapter CLI/UI integration не заменяет missing problem/style match |

## 8. Контекстные билды

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| B01 | Билд отвечает конкретной задаче матча | partial | `build_planner.py`/UI: явная текущая цель, выбранные предметы, условные вопросы | Verified item/threat criterion и prior/team task; исследовательский план не подтверждённый билд |
| B02 | Учитывать role/drafts/threats/enemy items/economy/stage/team task | partial | Own pre-anchor/purchase prefix, явные непроверенные угрозы и budget/component declarations; source binding | Verified opponent item observability, actual role/draft/team task и exclusions; угрозы не повышаются в Fact |
| B03 | Какая проблема решается предметом | partial | Goal-conditioned research question/descriptor retrieval и источник для проверки эффекта | Evidence-backed per-state problem→effect mapping; literal description не доказательство полезности |
| B04 | Альтернативы, sacrifice/tradeoffs, revisit | partial | Сравнение заявленных remaining costs, ограничения/условия пересмотра, saved revisions | Real patch-scoped utility и context monitoring; budget arithmetic не utility ranking |
| B05 | Purchase popularity/stat association ≠ contextual recommendation | implemented | PurchaseSequence always descriptive/optimality not_established | Validated individual recommendation пока отсутствует |
| B06 | Не точная win%/gold loss без модели | implemented | Такой результат не выпускается; no probabilities | Если понадобится numerical model — независимая проверка/калибровка |
| B07 | Источники mechanics соответствуют patch | partial | `ingest/valve_catalog.py` live descriptors/receipts, unassigned patch | Подписанные исторические snapshots/patch mapping, checks спорных mechanics в клиенте |

## 9. Интерактивная карта и вардинг

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| W01 | Карта+timeline+wards+movements | partial | `wards.render_ward_map`: SVG schematic slider, optional retrospective hero positions; `test_ward_surface.py` | Actual map geometry/objective state и task-relevant movement; current crosshair не игровая карта |
| W02 | Ward lifecycle/pregame/generation/censoring | implemented | `ward_instances`, prefix tests, missing placements/conflict states | Raw extraction клиентно не валидирована; software fold выполнен |
| W03 | Какую задачу решал обзор | missing | UI честно unknown utility | Typed team task/coverage intent evidence, goal alternatives |
| W04 | Соответствие планируемому действию команды | partial | `learning/ward_review.py`: supplied verified Task predicate alignment; `test_ward_review.py` | Actual team-plan source/goal and decision criterion; совпадение predicate не tactical quality |
| W05 | Возможность безопасно поставить | partial | Только verified supplied PlacementEvidence; unknown иначе | Алгоритм вывода safety/feasibility из доступного context/verified threat reach отсутствует |
| W06 | Дублирование существующего обзора | partial | `ward_review`: повтор уже известного attributed predicate и simultaneous joint sources | Реальный verified observation/attribution stream; geometry/coverage overlap отдельно не вычисляется |
| W07 | Информация, действительно данная вардом | partial | Prefix first-seen/novel supplied observations, attribution+coverage receipts; 14 tests | Actual visibility attribution from replay/client; novel относительно supplied prefix не marginal utility |
| W08 | Реально доступные альтернативы | partial | Только подтверждённые supplied feasible actions; no invention | Actual candidate generation/choice boundary+placement context+comparative task utility |
| W09 | Lifetime не usefulness | implemented | Ward observed_lifetime separated; no quality verdict | Short decisive-information examples and expert checks нужны для utility model |
| W10 | Point purpose/conditions, без универсальных лучших точек | partial | Universal recommendation не рисуется | Contextual validated point recommendations пока вообще отсутствуют |
| W11 | Не точная geometry без validation | implemented | Schematic label/fixed extent, no radius visibility overlay | Реальная geometry+terrain/tree/elevation/patch validation отдельный workstream |

## 10. Интерфейс и сквозной продукт

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| U01 | Сохранить подходящий стек, современная иерархия | implemented | Static HTML/CSS/JS `report.py`, `surface.py`; desktop/mobile screenshots в verification | User comprehension/accessibility pilot; внешний вид не доказывает analytics |
| U02 | Overview с приоритетными находками | partial | Incident ranking/timeline; outcome impact annotated | Приоритетные проверенные decision findings отсутствуют, а не «ошибок нет» |
| U03 | Timeline эпизодов | implemented | Unique episode IDs/anchors, no same-second overwrites; dossier tests | Real decision timeline после trigger discovery |
| U04 | Map и доступный clip | partial | Schematic map, clip pipeline `video/*`, tests; absence explicit | Real POV alignment/clip artifact matching decision; interactive object-aware map |
| U05 | Карточка decision→evidence→alternatives→behavior | partial | Evidence details/alternative unknown/reasons clear | Actual choice, feasible alternatives и behavior recommendation для одного реального supported эпизода |
| U06 | История повторяющихся проблем | partial | Profile/history/learning DTO; habits section currently explanatory unavailable | Ledger→habit renderer→comparison periods→examples/counters integration |
| U07 | Study/build recommendations | partial | Source-backed study task matching и контекстный план покупки с сохранёнными редакциями | Verified personal usefulness/build criterion, historical mechanics и actual feasibility |
| U08 | Ward map для соответствующих задач | partial | Schematic lifecycle exists | Task-aware ward analysis absent |
| U09 | Краткий first-level, раскрываемые детали | implemented | Facts/manifest details collapsed; browser QA recorded | Comprehension quality independent validation pending |
| U10 | Открыть evidence серьёзного утверждения | partial | Source links/locators/hash, tf source refs; no false headline | Real replay tick/POV seek binding для claim, valid semantic proof prerequisites |
| U11 | Verdict/headline/text не противоречат | implemented | Deterministic dossier/templates, legacy accusing LLM ignored; tests | Review future source/build/habit renderers before live admission |
| U12 | Loading и parsing-error UI states | implemented | Workbench queue/loading/complete/error, план показывает validation/stale/session errors | CI Linux и comprehension сетевых ошибок ещё требуют внешнего прогона |
| U13 | Incomplete data/no-history/no-recommendations | implemented | Manifest reasons and explicit unavailable sections | Не смешивать no findings with inability to assess when valid pilot appears |
| U14 | «Не согласен/другая цель/полезно» | implemented | `feedback.py`, browser storage/export/hash validation; `test_feedback.py` | Review/adjudication interface and longitudinal measurement separate |
| U15 | Feedback material не automatic truth | implemented | unreviewed status, import promotion rejected, idempotent store | Real independent expert review needed before using corrections |
| U16 | Demo не выдавать за actual analytics | implemented | Explicit synthetic labels, independent real-quality cohort empty | Реальный source data smoke сам по себе не делает evaluator/habit validated |

## 11. Независимая проверка качества

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| Q01 | Отдельная correctness проверка facts | partial | FactCheck contracts, replay source/nullable tests, raw audit | Raw/client trace corpus по identity/clock/visibility/inventory/control |
| Q02 | Отдельная decision correctness | partial | Annotation acceptable sets, blind pack, prediction metrics; `test_validation_pipeline.py` | Реальные human labels, concrete validated criterion, sealed holdout |
| Q03 | Explanation соответствует evidence | partial | Deterministic claim templates, evidence linkage | Expert entailment audit на real claims; future LLM text checking |
| Q04 | Совет полезен пользователю | external_validation | useful feedback button, no quality score fabricated | User comprehension/usefulness pilot с критериями и adverse advice audit |
| Q05 | Поведение меняется в следующих матчах | external_validation | Progress DTO и comparable gates | Real longitudinal baseline/followup opportunities; причинность отдельно от descriptive change |
| Q06 | Expert annotation формат и revisions | implemented | `validation/contracts.py`, JSONL loader, typed facts/actions, hash chains | Expert provenance workflow outside declarations |
| Q07 | Независимая проверочная выборка | external_validation | Dataset split audits/holdout fields | Real sealed sample, verified independent humans; synthetic fixtures не выборка качества |
| Q08 | Good bad outcome, bad good outcome, alternatives, insufficient | partial | Synthetic criterion/anti-resultism fixtures | Real expert-balanced cases независимо от death selection |
| Q09 | Разделение matches и всех players train/test | implemented | `audit_splits` targets+participants overlap checks; tests | Проверенные actual identities/full roster; withheld corpus processes |
| Q10 | Перенос между patch | partial | patch_transfer partition, patch counts and mismatch gates | Actual cross-patch corpora and comparative validation; grouped counts не transfer proof |
| Q11 | False accusations/coverage/abstention metrics | implemented | `evaluate_predictions`: all issued accusations, missing predictions, disagreement/unknown denominators | Real labels/complete opportunity census; текущие real rates null |
| Q12 | Factual error rate | implemented | `validation/fact_quality.py`: latest revisions, минимум два разных raters, incorrect/known consensus denominator, unknown/disputed отдельно; tests | Реальная client/human fact-разметка отсутствует; error rate null, а не 0 |
| Q13 | Не получить accuracy полным молчанием | partial | Missed assessable cases/coverage reported, no false accuracy from empty cohort | Real sufficient assessable cohort и критерий допустимого coverage/false accusation tradeoff |
| Q14 | Калибровка вероятностей, если показаны | implemented | Probabilities не выдаются; no fake confidence | Calibration pipeline не требуется до внедрения probabilities; появление требует отдельной реализации |
| Q15 | Проверки скрытых/будущих dependencies не только radiant_win | implemented | World/future fields, same-tick uncertainty, prefix hash and ward tests | Real derivation/selection semantic leakage после создания opportunity discovery |
| Q16 | Missing replay/labels не подделывать validation | implemented | Реальный replay уже есть, client labels нет; release disabled/experimental; annotation templates marked | Завершить реальные проверки вместо вечного abstention-only результата |

## 12. Порядок работы и фактический первый этап

| ID | Обязанность | Статус | Исполнение / свидетельство | Оставшаяся работа |
|---|---|---|---|---|
| P01 | Карта разрывов, один класс, исправленная база | implemented | Архитектурный пакет, S0 fixes, typed experimental class | Не считать interface slots закрытием real pilot |
| P02 | Оценка с evidence/abstention в законченном UI | partial | Offline batch mathematical evaluator + synthetic UI; real dossier abstains | Реальный narrow criterion input assembly→assessment→evidence→exercise |
| P03 | Проверка на реальных данных и edge cases | partial | `.dem` acquisition, actual API source study, synthetic regressions | Real trace semantic correctness/POV/criterion gold labels |
| P04 | Не только план, максимально полный доступный этап | implemented | Рабочий CLI/report/trace/source tooling, fixtures, local artifacts | User goal real coaching не достигнут одними infrastructure artifacts |
| P05 | Не публиковать/не менять main без разрешения | implemented | Local edits only, own git checkout absent, unrelated parent git untouched | Правильный Git checkout/branch для review когда предоставлен; сейчас нет Git diff/commit |
| P06 | Сообщить working/tested/forbidden/demo/run/next step | implemented | README/INSTALL/handoff, актуальные stage docs и release-readiness; full TZ явно не закрыт | Поддерживать документы по мере получения внешних проверок |

## Реальные пробелы в порядке зависимости

1. **Semantics data gate.** Реальный replay есть. Проверить по raw/client primary identity и resource-slot join; clock/pause/sub-tick order; semantic inventory/cooldown/control/cast/cue. Затем построить observed/team/screen stream. Наличие Go callback и raw полей не завершает ни один из этих допусков.
2. **Первый реальный criterion.** Выбрать конкретные patch+item+ability, проверить threat interaction и availability, задать goal/cost/competing alternatives. Реализовать trigger/choice window/stable-step admission и полный opportunity census. Получать feasibility и rubric bounds из проверенных фактов, а не просить JSON авторов написать четыре числа.
3. **Independent labels.** Реальные decision-blinded expert cases: хорошие решения с плохим outcome, ошибки без наказания, reasonable alternatives, insufficient. Seal train/calibration/holdout/player/patch splits; затем измерить false accusation и coverage. Два заявленных annotator ID не доказывают независимость людей.
4. **Coaching, problem/task matching.** Лишь после criterion — реальный HabitEvidence→criterion-specific exercise→followup evaluation. Self-directed goal/task matching и descriptive feature comparison работают; подтверждённый habit, устойчивый style metric и verified team-task suitability отсутствуют. Target match обязательно исключать из внешних рекомендаций.
5. **Builds/wards.** Данные источников и API для rules ещё не алгоритмы: нужна patch-scoped contextual build registry; observation attribution/novel information/task alignment и feasible ward alternatives. Не выдавать карту координат и purchased items за эти функции.
6. **User utility.** Локальные feedback/annotation данные не устанавливают пользу. Провести comprehension/advice pilot и затем comparable longitudinal observations; не заявлять причинный эффект тренера.

Синтетический этап завершает software foundation и безопасное представление неизвестности. Полное исходное ТЗ **не закрыто**; главный незавершённый результат — конкретный разбор реального решения с проверенными альтернативами и применимым персональным упражнением.

## Дополнение после основной фиксации

Получены два **внешних** source-backed учебных примера hero145: **9031046793** (account458287006, TF1003с) и **9030693809** (account904131336, TF719с). Оба registered_pro, provider patch ID60, position_1 estimated, binary replay prefix доступен в момент проверки. Целевой **9030822324** исключён API параметром `exclude_match_ids`. Артефакт `out/study-live/discovery.json` содержит реальные receipts/hash/task/episode refs. S04–S06 теперь partial за счёт последующего training stage: одни источники не доказывают сходство задач/стиля и связь с подтверждённой персональной проблемой.

Для offline повторного открытия реализованы `save_study_discovery`/`load_study_discovery`: строгий SHA/schema/URL и body→match/hero/account/slot/role/rank/pro registry/episode binding. Loader ничего не запрашивает и не выдаёт criterion grant. Captured probe explicitly not rechecked; текущая доступность после сохранённой проверки неизвестна. Структурно согласованный локальный receipt не доказывает аутентичность сервера или независимость provenance review.

`learning/ward_review.py` добавил реальный prefix алгоритм описания **переданного проверенного** attributed observation stream: first observed entity внутри supplied history, novel changed predicate, duplicate known predicate, simultaneous joint attribution, supplied task alignment. Неполнота/нет attribution/нет validation receipts/conflicts дают отказ. Будущее не меняет prefix; lifetime не является входом; circles отсутствуют; utility всегда not_established. Actual stream extractor и real ward quality отсутствуют, поэтому W04–W08 — partial, не implemented.

Focused проверки после этих изменений: **37 source + 28 learning + 14 ward = 79 passed**. Это алгоритмические contract/edge cases; real ward visibility, utility и coaching quality не аттестованы.

Следующее дополнение — `learning/training.py`, `tests/test_training.py` (**21 passed**, combined **100**). Исполним user-directed training cycle по явно подтверждённой цели: конкретное task exercise, eligible/ineligible/unknown journal, self-report/independent observation distinction, baseline/followup chronology/disjoint IDs/scope/source/coverage checks. Это расширяет C05/C08/C09 и S04/S07 до более полной partial реализации. Source task matching выбирает фактические teamfight/purchase/ward source pointers по задаче; descriptive feature distance из GPM/LH/deaths/wards/participation открыто сообщает missingness и scales. S05 теперь имеет измеримый descriptive comparison, но **не проверенную устойчивую style similarity**. S06 связывает подтверждённую пользовательскую learning preference с task episodes; автоматически выявленная validated issue по-прежнему отсутствует. Реальная личная цель/журналы не вымышлены: `out/training-live` показывает unavailable/unconfirmed и отсутствие baseline. Подробности — `2026-10-06-training-cycle.md`.
