# Непрерывные интервалы условий и журнал попыток действия

Следующий этап: [реальные raw источники](2026-10-07-replay-source-stage.md). Spectator orders, непрореженные prefix operands и event visibility теперь извлекаются. Описанное ниже отсутствие источников фиксировало прошлый этап; проверенная полнота attempts/constraint truth/cues остаётся неизвестной.

Продолжение ТЗ от 7 октября 2026. Реализованы два недостающих алгоритма и переносимые команды: `choice-monitor` и `command-review`. Это исполнение поверх отдельно проверяемых источников, а не автоматическое подтверждение raw replay fields.

## Монитор изменений

`decisions/choice_monitor.py` вычисляет ограниченные непрерывные интервалы из типизированных операндов, cue и отдельно размеченного потока переходов. Для каждого sample используется уже вычисляемая conjunction условий `choice_window.py`. Свежесть/TTL и поле `stable_until` сами по себе не доказывают неизменность состояния.

Положительный интервал требует exact-reviewed `ContinuityCoverage` с режимом `complete_constraint_truth_transitions_with_cue_and_pause`. Он связывает historical scope, механическую интерпретацию, все condition codes, точный manifest samples, полный manifest cue transitions, часы и источник. Это проверка полноты изменений **истинности условий** с учётом динамики; полнота entity callbacks или сырых field writes её не заменяет. Реальный extractor такого потока ещё не подключён.

Sweep ограничивает интервал гарантированным временем реакции, концом покрытия, freshness каждого используемого операнда, cutoff и началом материального перехода. Применяется нижняя граница фактического `valid_at` изменения, а не время позднего sample. Изменение контроля в1300, доставленное в sample1400, закрывает прежний интервал в1300. Смена paused без отдельного установленного времени перехода не даёт поддержки. Unknown/conflict/false cue того же scope консервативно закрывает прежний cue; без persistent cue identity это может излишне ограничивать охват. Неизвестное время/отсутствие exact review такого перехода даёт отказ.

Результат `supported_constraint_span` означает только условно подтверждённый интервал конечного набора условий. Он не устанавливает, что игрок заметил угрозу, должен был нажать предмет, мог исполнить любую команду Dota или допустил ошибку. Minimum action duration и reaction policy явно исследовательские. Эти spans не являются полным игровым denominator и не используются для обучения.

Spans реконструируются **на момент cutoff**. Их поздние transitions/coverage не входят в `decision_start_hash` раннего sample. Будущие source records и будущие известные timestamps исключаются из исторического prefix. Whole-file receipts хранятся для проверки целостности, отдельно от analytical hashes.

## Попытки и стадии исполнения

`decisions/command_census.py` различает attempt, accepted, committed, effect и rejected, связывает их с exact actor/item generation, attempt ID, source records, time/availability и schema version. Effect не превращается в попытку. Повторные, пропущенные и противоречивые стадии остаются отдельными неизвестностями. Game time, replay tick и same-tick sequence проверяются вместе; противоречивый порядок отклоняется, неопределённый блокирует полноту.

`observed_no_attempts` возможен только для конкретного проверенного полуоткрытого интервала при независимом покрытии **command channel**: exact source/subject/item, полный attempt manifest, clocks/order/pause, доставленные receipts и отдельно размеченные команды. Пустой inventory или отсутствие combat marker такого вывода не даёт. Даже полный пустой журнал не означает ошибку игрока. Orphan stages и недостоверные stage semantics не сертифицируются как полная цепочка.

Coverage не может предшествовать своему концу либо доставке покрываемой команды, даже при возрастающем числовом game time и противоречивых ticks. Будущие и недоставленные records не меняют prefix counts/hash. Внешняя честность источника и независимость людей остаются отдельными обязательствами.

## Запуск и разметка

```powershell
python -m dota_coach.cli choice-monitor --input-json STREAM.json --out MONITOR.json
python -m dota_coach.cli command-review --input-json COMMANDS.json --out CENSUS.json
```

Strict schema `foresight.choice-stream.v1`: `choice_input` (схема `foresight.choice-evidence.v1` с samples/cues/semantics/scope), `cutoff`, `cutoff_record_index`, `minimum_duration_ms`, `coverages`. Strict schema `foresight.command-input.v1`: `scope`, `events`, `coverage`, `interval_start`, `interval_end`, `cutoff`, `cutoff_record_index`. Вложенные типы находятся в соответствующих модулях; fixtures полного roundtrip — `tests/test_choice_monitor.py` и `tests/test_command_census.py`. Это синтетические engineering inputs, не игровые примеры.

Для создания exact DatasetRecord JSONL добавить `--manifest-json DATASET.jsonl --replay-sha256 SHA`. Для reviewed calculation добавить `--dataset-jsonl DATASET.jsonl --annotations-jsonl LABELS.jsonl --replay-sha256 SHA`. Нельзя перезаписывать INPUT/labels/dataset через output или manifest; такой запрос отклоняется до записи. Manifest exporter не создаёт экспертные ответы.

Continuity требует минимум двух **последних** declared human extraction проверок `continuity-context:<record.input_hash>` и `continuity-coverage:<content_hash(coverage)>`. Для operand/cue/mechanics admission отдельно требуются sample records и их checks из предыдущего этапа. API `monitor_input_record` и `choice_evidence_record` создают точные records; для dataset объединить records каждого sample и record monitor query.

Command census требует два latest extraction checks контекста `command-context:<record.input_hash>`, покрытия `command-coverage:<content_hash(coverage)>` и событий `command-event:<content_hash(event)>`. Record API — `command_input_record`; resolver — `resolve_reviewed_command_registry`. Наличие самообъявленных `verified/admission/registry` в portable файле запрещено, повторные JSON keys отклоняются.

Сначала выбирается последняя ревизия annotator, затем проверяется её квалификация. Новая self-evaluation revision не оставляет старый expert голос действующим. Negative/unknown correction отзывает конкретный допуск. Два declared IDs не удостоверяют реальных людей, client access или production certification. Все результаты остаются conditional research, `strategic_quality=not_established`, `training_eligible=False`.

## Инженерный review и проверка

Отдельный read-only reviewer воспроизвёл и затем повторно проверил исправления: future operand tick, unknown cue order, unknown expiry order, unknown target index, поздняя expiry как hindsight, late control transition, cue retraction, coverage/query/command tick contradictions, future sample и отзыв экспертной ревизии. Конкретные regressions добавлены; прежние false grants больше не воспроизводятся. Это независимый инженерный review, не независимая экспертная оценка игры.

Полная suite и актуальные SHA свежих wheel/sdist записаны в `out/verification/release-readiness.json`; JUnit — `out/verification/python-tests.xml`. Installed smoke проверяет новые модули и CLI вне checkout без PYTHONPATH/PYTHONHOME. Go extractor этим этапом не менялся; предыдущие 9 Go tests/module verification/build сохранены. GitHub/Linux CI здесь не запускался.

Реальный локальный отчёт пересобран. В нём остаются2999 inventory samples и0 validated choices; command channel и constraint transition stream не получены, что отдельно показано в UI. Реальные command/cue records, reviewer labels и measured coaching benefit не выдумываются.

## Открытые требования

Теперь имеются continuous constraint reconstruction и exact command census, но **нет их реального source extractor/клиентно проверенного корпуса**. Нужны actual command events и полнота канала, непрерывные constraint/cue/pause transitions и исторически проверенная семантика. Sampled replay не повышается до этих capabilities.

Также остаются полные cast/control/target rules (включая intended point binding), настоящий FoW/POV extractor, TP arrival/interruption и smoke break cause, historical map ownership/geometry/navigation, вычисляемая route safety, проверенный item/threat rubric и utility alternatives, contextual build rule registry и привычки на проверенном критерии. Client/POV/historical patch mapping, реальные независимые labels/holdout и настоящий baseline/followup остаются внешней работой.

Полное ТЗ игрового тренера не объявляется закрытым. Следующий результат с наибольшей ценностью — реальный independently checked transition/command corpus для одной пары patch/item/threat, чтобы проверить эти вычисления на игре и определить применимое упражнение.
