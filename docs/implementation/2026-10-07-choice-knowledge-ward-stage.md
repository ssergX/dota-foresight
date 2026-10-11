# Вычисляемая аналитика выбора, знаний и вардинга

Документ фиксирует этап с939 тестами. Следующее исполнение: [continuous/command stage](2026-10-07-continuous-command-stage.md) добавляет conditional continuous monitor и command-attempt census; фактические source extractors и игровая проверка по-прежнему открыты.

Это продолжение реализации ТЗ от 7 октября 2026 года. Добавлены алгоритмы поверх исходных операндов и точных префиксов, переносимые команды проверки и интеграция в реальный отчёт. Полное качество игрового тренера ещё не установлено: программные проверки и внешняя игровая проверка учитываются отдельно.

## Что работает

`decisions/choice_window.py` вычисляет ограниченную механическую выполнимость: точное поколение предмета, alive, mana ≥ cost, допустимый слот, интерпретируемые control bits, cooldown, charges и ограничения цели. Для unit/point проверяются доступные distance/range; для unit также поколение, alive и команда цели. Это конечный перечень условий указанной версии механики, а не универсальная модель всех Dota restrictions. Неизвестный обязательный операнд не становится разрешением. Независимо допущенное ложное условие исключает действие; все условия должны быть известны для положительного результата. Оценка стратегического качества здесь не производится.

Resolver использует явно переданный screen cue, доступность до sample, паузу, погрешность часов, срок действия cue и заданную политику реакции. Строятся возможный и гарантированный временные интервалы. Team knowledge не устанавливает увиденный на экране сигнал. Future/foreign validity не допускается даже при наличии review receipt. Материальное изменение условий меняет следующий sample, сохраняя прежний результат. Поддержанный sample не означает непрерывную готовность между наблюдениями. Поле `stable_until` само по себе не даёт такого вывода; continuous monitor и полный census игровых возможностей остаются открытыми.

Весь supplied inventory stream обрабатывается независимо от нажатий. Конкретный handle, который встретился только позднее, больше не задаёт scope предыдущего sample. Полные SHA источника остаются receipts для проверки целостности; analytical feature hash опирается на наблюдённые операнды и source locator, поэтому изменение будущего содержимого не меняет ранние признаки.

`evidence/temporal.py` разрешает наблюдения только при установленной доступности до cutoff. Политика явно задаёт TTL каждого predicate. Поздно доставленный старый факт не заменяет более новое наблюдение. Перекрывающиеся противоречия и entity generations остаются conflict; истёкший TTL даёт stale, граница TTL при неопределённости — unknown. Last-known не объявляется текущей видимостью или вниманием. World/foreign/future observations не добавляют subjects, counts или hashes. Это projection engine, а не extractor реального FoW/POV.

`learning/ward_analysis.py` обрабатывает отдельный source prefix каждой постановки: фактические callback counts, original clock missingness, поколения, orphan/conflict refs и равенство сырых координат с ранее наблюдёнными объектами. Равенство координат не является пересечением обзора. Для отдельно переданного и точно размеченного observation/attribution corpus вычисляются novel/duplicate/conflicting сведения, joint attribution и соответствие явно запрошенному predicate/entity. Novelty требует полного предшествующего supplied history. Для альтернатив сохраняются pairwise известные условия и неизвестности; utility/rank не выдумываются. Safety/route conditions пока являются отдельно проверяемыми входами: расчёта навигационной достижимости и безопасности пути нет.

Текущая подтверждённая цель в форме не становится намерением игрока при прошлой постановке. Аналитика callback prefix теперь входит в сохранённый план. В интерфейсе срез включает выбранный callback; предшествующие объекты считаются отдельно строго до него. При более позднем cutoff информация помечается ретроспективной и не используется для утверждения о безопасности исходной постановки.

`ingest/objective_state.py` строит историю зданий/Roshan/buyback отдельно для trace, combat-names и provider. Точные имена дают наблюдаемые субъекты, но не поколения или ownership. Повторные уничтожения одного имени сохраняют неоднозначность. Respawn, текущая готовность buyback и постоянный контроль карты неизвестны. Source-local API возвращает objective prefix строго до выбранной записи; provider timeline остаётся ретроспективой.

## Входы и независимая проверка

`choice-review --input-json INPUT --out RESULT` принимает strict schema `foresight.choice-evidence.v1`: `scope`, `semantics`, `cues`, опционально `samples`. Вложенные TimeRef/Fact/EntityRef/PrefixFact типизированы; duplicate JSON keys, outcome/utility/admission fields запрещены. Без отдельной разметки candidate calculation сохраняет admitted feasibility unknown.

Для exact extraction review команда принимает `--dataset-jsonl DATASET --annotations-jsonl LABELS --replay-sha256 SHA`. DatasetRecord создаётся API `choice_evidence_record(scope, sample, cues, semantics, replay_sha256=...)`. Он привязан к subject/match/replay/patch, sample и только предыдущим cues. Два разных declared human extraction reviewers должны согласованно проверить correctness и availability operand facts. Контекстные FactCheck IDs: `sample:<content_hash(sample)>`, `cue:<content_hash(cue)>`, `mechanics:<content_hash(semantics)>`. Они отдельно связывают clock/pause/expiry и трактовку механики. Последние revisions могут отозвать согласие. Self-evaluation, один reviewer или изменённый вход не открывают расчёт.

Заявленные reviewer IDs не аутентифицируют людей и доступ к клиенту. Даже после такого binding результат остаётся conditional research, strategic_quality=not_established, training_eligible=False. Он не становится игровым gold label или production criterion.

Для raw stream использовать `choice-review --extraction-json EXTRACTION --action-states-json STATES --out RESULT`; optional `--replay-sha256` сверяет независимый expected SHA. Raw world extraction не выдаётся за POV; default scope и clock semantics не аттестованы. Разметка для допуска требует typed reviewed input, а не автоматического повышения сырых кадров.

`ward-review --source-json WARDS --ward-id ID --out RESULT` вычисляет callback context без вымышленной цели. `--goal-json GOAL` допускает только явно подтверждённую текущую задачу. Дополнительные `--evidence-json`, `--dataset-jsonl`, `--annotations-jsonl`, `--cutoff-record-index` подключают exact reviewed corpus. Шаблон схемы и edge cases находятся в `tests/test_ward_analysis.py`; manifest API — `ward_evidence_record`.

`knowledge-review --input-json INPUT --out RESULT` принимает strict schema `foresight.temporal-input.v1`: `subject_player`, `cutoff`, `policy {version,predicate_max_age_ms}`, `facts`, `dataset_kind`, optional `entity_bindings` и `queries`. TTL pairs имеют вид `[predicate, ttl_ms]`, null разрешён только для явно статического predicate. Output сохраняет policy, states, факты, hash и unverified status.

## Реальная проверка и поставка

На публичном матче 9030822324 обработаны **2999** inventory samples: 0 supplied cues, 0 supported/excluded choices, 2999 unknown. Это честное отсутствие входа для выбора, а не 2999 плохих решений. Из 262 ward callbacks доступны **69** собственных командных постановок для анализа. В objective history: trace — 3 события/3 субъекта; provider — 24/23; combat-names — 3/3. Источники не суммируются как уникальные игровые события.

Полная suite после окончательных исправлений: **939 Python tests**, **9 Go tests**, Go module verification/build. Проверены arithmetic disproof, target generations, pauses, uncertain clocks, future cue validity, stale facts, late delivery, source hash invariance, review binding/revisions, orphan lifecycle, ward attribution и CLI overwrite guards. Это contract/engineering tests; синтетическая разметка в тестах не входит в реальные expert labels.

Browser QA реального отчёта проверяет новые sections, unknown first ward time, явно тестовую цель, сохранение callback analysis, восстановление результата с пустой новой целью, desktop/mobile, anchors и JS errors. QA declaration исключена из пользовательской истории и quality cohort. После QA создан отдельный свежий отчёт без сохранённого плана.

Wheel/sdist пересобраны, проверены по allowlist и установлены в новый venv вне checkout без PYTHONPATH/PYTHONHOME. Точные SHA и результаты находятся в `out/verification/release-readiness.json`; JUnit — `out/verification/python-tests.xml`. Локальные replay, QA journals, runtimes и приватные данные в архивы не включены. GitHub/CI Linux ещё не выполнялись.

## Незакрытые требования

Программные части: извлечение настоящих cues и visibility, непрерывный stable-step monitor и command census; полная cast/target/control semantics; TP arrival/interruption и smoke-break causes; историческая геометрия/ownership/навигация и вычисляемая route safety; проверенная item/threat rubric, полезность альтернатив, contextual build rule registry и admission привычек на проверенном критерии. Реализованные conditional algorithms не закрывают эти зависимости.

Внешние данные: client/POV сверка clocks/identity/mechanics/availability, historical build↔patch mapping, реальные независимые labels и sealed mixed-outcome holdout, настоящее измерение понимания совета и неперекрывающихся baseline/followup. Реальных expert labels и проверенных игровых verdicts всё ещё **0**. Конкретные обязательства: [пакет внешней проверки](2026-10-07-external-validation-inputs.md).

Следующий наиболее ценный шаг — client/POV-проверенная пара patch/item/threat, доступный до choice screen cue и независимые extraction/decision labels. Она позволит проверить действующий resolver и механические вычисления на игре, затем определить переносимое упражнение и измерить его пользу.
