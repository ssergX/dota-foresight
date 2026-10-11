# Data spike: defensive_activation.v1

Статус: настоящий replay и raw source artifacts получены; клиентная/экспертная сверка отсутствует. Live evaluator disabled. [Реальное source extraction](../implementation/2026-10-07-replay-source-stage.md) добавляет spectator orders, непрореженные собственные operand changes и optional combat-event visibility. [Экспериментальная инфраструктура](../implementation/2026-10-05-completion.md) принимает строго переданные факты/рубрики и независимую разметку; проверенные mechanical conditions или utility bounds ещё не установлены. Этот спайк остаётся исследованием, а не пройденным data gate.

## Цель и ограничение

Выбрать один подтверждённый patch/build и одну пару защитного предмета и наблюдаемой угрозы. BKB — кандидат для исследования; конкретная ability не назначена без данных. Не искать оправдание заранее выбранному обвинению «BKB готова, значит должен нажать».

## Входные артефакты

| Вход | Что зафиксировать | Сейчас |
|---|---|---|
| Replay | Существующий match ID, .dem hash, доступ/источник, build | Публичный9030822324, SHA55d582de…; rawbuild6943, historical mapping не проверен |
| Клиентная проверка | Командный POV, игровые часы/паузы, своё состояние | Не предоставлена |
| Reaction cue | Конкретный видимый/слышимый сигнал субъекту, канал и интервал доступности | Не подтверждён |
| Raw trace | Entity/player mapping, предмет, cast, control, attempt/accepted/commit | trace.v3, own prefixes, spectator orders собраны; attempt/accepted/commit и семантика ещё не допущены |
| Механика | Patch-scoped первичный источник и клиентные пограничные случаи | Не выбрана/не проверена |
| Экспертный rubric | Feasibility, tradeoffs, другие цели, acceptable labels без outcome | Не предоставлен |

Fixture match 8001 и fixture JSONL не считать такими артефактами.

## Процедура

1. Проверить десять primary heroes и player mapping. Противоречие raw `m_iPlayerID` и деления на 2 разрешить фактическими traces, не догадкой. Проверить clocks/паузы/pregame.
2. Сопоставить raw поля выбранного предмета и угрозы с клиентом: ownership, resources, cooldown/charges при применимости, disable states и взаимодействия. Каждому отсутствующему обязательному полю назначить отдельную gap-задачу.
3. Подтвердить, когда конкретный reaction cue мог дойти до субъекта. Team visibility не доказывает реактивную доступность. POV не доказывает внимание.
4. Различить попытку команды, принятую команду, активацию и эффект. Журнал одних successful casts не позволяет обвинять в отсутствии попытки.
5. Найти все поддержанные окна, включая успешные исходы и непойманные ошибки. Для v1 — один стабильный шаг до commit/deadline; неизвестные изменения контекста и order → abstain. Конечный snapshot не объясняет раннее действие.
6. Эксперты сначала видят только префикс и action observation. После фиксации rubric/label отдельно открывают outcome. Сохранить исключения, несколько разумных вариантов и counterexamples.
7. Подготовить extraction calibration и независимый holdout согласно `docs/architecture/2026-10-05/04-validation.md`. Не называть несколько удачных примеров подтверждённой точностью.

## Выход

Версионированные corpus manifest, raw trace table, клиентные evidence refs, patch mechanics registry, rubric, capability validation reports, error analysis и решение `admit within scope | reject candidate pair | remain data-blocked`.

Неудовлетворительные данные — допустимый итог спайка. В таком случае текущий evidence dossier остаётся рабочим, evaluator не включается и scope не расширяется до слабой эвристики ради числа карточек.
