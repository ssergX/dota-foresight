# Момент выбора: точные временные границы и отказ при потерянной наблюдаемости

Дата: 9 октября 2026 года. Выполнен дополнительный аудит ключевой аналитики (§3–§6 ТЗ). Изменения исправляют ошибки действующего evaluator/monitor, а не вводят новые неподтверждённые игровые классы.

## Воспроизведённые ошибки и итоговое поведение

1. **Clock `unknown` с флагом verified.** Совпадающая строка clock mapping и typed review раньше могли дать `feasible` и `supported_choice`. Теперь пустые/reserved/неправильно типизированные mapping и unverified order не создают численных bounds. False cue при неизвестном sample order не исключает действие.
2. **Uncertainty меньше float ULP.** Expiry `1800 ± 1e-14` раньше округлялся до точного1800 и разрешал sample1800. Comparisons, freshness, reaction policy, continuity duration и guard clipping теперь используют точные десятичные rational bounds. Неопределённость сохраняется, sample1800 остаётся unknown.
3. **Неподтверждённая доставка operands.** Mana или extended guard с `available_at=None`, чужими/непроверенными часами раньше участвовали в candidate arithmetic/disproof. Общий `_readable_fact` требует verified same-clock validity/delivery/sample, строгую causal relation valid≤available и доступность до sample. Неизвестный operand не превращается в ноль или disproof. Raw числа остаются в source receipts; `mana_after_cost_arithmetic` не выдаётся из недоступных operands.
4. **Исчезновение поля.** Следующий sample без mana/control/cooldown/item identity раньше продлевал supported span до его timestamp. Теперь отсутствие любого использованного material operand делает предыдущую continuity unknown с `material_operand_removal_time_unknown`. Доказанного момента утраты поля нет; TTL не заменяет его.
5. **Будущий sample возвращался в outer adapter.** Main choice monitor исключал sample после time cutoff, но mechanical adapter повторно включал его в checks, finite transitions и prefix hash. Теперь обе части используют один выбранный prefix. Добавление/изменение future mana не меняет текущий output.
6. **Неопределённый sample скрывался за cutoff.** Sample1200±300 при query1300 нельзя считать полностью прошлым, но нельзя и игнорировать как доказанно будущий. Новый отдельный `unresolved_transition_boundaries` хранит только source ordinal/time, без будущих values. Manifest completeness обязан учитывать overlapping samples; противоречивый manifest отклоняется, а exact re-review не даёт continuity через неразрешённую границу.
7. **Сигнал с неизвестной доставкой выпадал из coverage.** Unknown/overlapping cue delivery также формирует отдельную границу. Полнота cue-transition manifest проверяется с такими сообщениями; их включение не удостоверяет точную видимость или uninterrupted reaction span. Доказанно будущие сообщения не входят в текущие features.
8. **Future whole-artifact identities в features.** Аналитические projections исключают archive/content hashes source receipts, derived fact IDs, derived_from и sample aliases. Они сохраняют реальные prefix operands, source locators, времена и их допуск. Exact caller registry всё ещё связан с полными исходными receipts. Переиздание архива не меняет semantic input/window/prefix hashes, но требует актуального exact review.

9. **Значение недоступного cue меняло hash и reason codes.** Для future/ambiguous/unverified/causally impossible cue теперь используется projection без значения и недоступных operands. Изменение True↔False такого cue не меняет окна, причины, arithmetic и semantic prefix hash. Unknown delivery создаёт ровно одну unresolved boundary и один manifest witness.

## Числовой контракт

`evidence/clock_math.py` реализует `verified_bounds`, decimal arithmetic и conservative numeric exports. Guaranteed region округляется внутрь, possible region — наружу. Exported supported duration не может стать больше exact guaranteed duration. Непредставимые finite float bounds дают контролируемый отказ вместо infinity. В JSON нет Fraction-объектов; большие целые bounds сохраняются как точные integers. Внутренние comparisons не вычисляются обратно через округлённые floats.

`choice_window.py`, `choice_monitor.py` и `mechanics_adapter.py` используют эти правила. Требования к continuity truth transitions и отдельному review сохраняются. Default raw source, typed research review и software tests не дают production/game-quality/training admission.

## Реальные данные и проверка

На доступном replay9030822324/account904131336 пересчитаны все2999 inventory frames. Supported choices0, excluded0, unknown2999; readable mana arithmetic0. Нет клиентной/POV сверки часов, cue или review; эти нули не означают отсутствие ошибок или возможностей. Итог `training_eligible=false`.

Обновлены `out/real-analysis/choice-windows.json`, соответствующие JSON/HTML choice sections сохранённого job993443de057a590d0605d4e5 и `out/real-review`. Остальные ранее проверенные replay/source/unit artifacts переиспользованы. Это частичный пересчёт исправленной аналитики, не новая полная декодировка replay и не новая игровая сертификация. Proof: `out/verification/choice-temporal-real.json`.

Regression corpus: `tests/test_choice_temporal_boundaries.py`. Покрыты causal delivery, float ULP, stale boundary, source/prefix invariance, removed fields, future adapter leakage и ambiguous sample/cue continuity. Все fixtures synthetic, даже когда тип reviewer указан в исследовательском контракте. Финальные counts, independent probes, архивы и clean installation proof берутся из `out/verification/release-readiness.json` текущего релиза; исторические числа не подменяют текущие проверки.

## Оставшиеся требования

Этот аудит закрывает ошибочные предположения в реализованной оценке доступности. Он не добывает реальные client attempts/POV cues, не создаёт historical item/control/channel rules, terrain/FoW adapters, strategic criterion для всех классов или независимые human labels. Полный продуктовый статус и оставшиеся алгоритмы: [матрица ТЗ](2026-10-08-tz-closure.md). Польза упражнений и игровая точность требуют отдельной проверки.
