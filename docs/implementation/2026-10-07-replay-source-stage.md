# Реальные источники приказов, изменений ресурсов и видимости событий

Продолжение от 7–8 октября 2026. Реализовано фактическое извлечение трёх потоков, подключённых к CLI, локальной очереди и HTML-отчёту. Это следующий программный этап после [монитора условий и census команд](2026-10-07-continuous-command-stage.md). Фактическое наличие raw сообщений отделено от допуска их игровой интерпретации.

## Что извлечено

На сохранённом публичном replay **9030822324** Go/Manta `--orders` получил **161568** сообщений `CDOTAUserMsg_SpectatorPlayerUnitOrders`. Четыре других зарегистрированных callback — `QueuedOrderRemoved`, `SpectatorPlayerClick`, `HudError`, `CDemoUserCmd` — дали ноль. Это census конкретных callback всего матча, а не число действий выбранного аккаунта. Client `ExecuteOrders` protobuf существует, но его dispatch в Manta v1.5.0 не подключён.

Sidecar `9030822324.orders.jsonl`: 89258922 байта; SHA256 `dc4c03d7baa9c57cb062a484baa37823ae8b6254349feb2ededfde76cf6088f7`. Источник replay: 126864874 байта; SHA256 `55d582de8fc9eb85d51becf0c38c28522f1277701e4bad8f053d1c0d7f6e9b47`. Parser завершён, raw game build 6943. Build пока не связывается с проверенной исторической механикой.

`ingest/constraint_source.py` использует общий prefix decoder `action_state.py`. Он сохраняет изменения конечного набора собственных hero/item/ability/clock/identity полей между секундными срезами, включая удаление, смену serial и потерю связи. Полные состояния сохраняются на границах идентичности; промежуточные изменения — точными `set/remove` дельтами. Reader воспроизводит один текущий срез и проверяет receipts. Связь Steam/account устанавливается в обработанном префиксе; поздняя финальная identity не переносится назад. Все значения, часы и механические трактовки остаются непроверенными. Полнота записей projected operands не является полнотой переходов истинности игровых условий.

Реальный проход сохранённого полного trace дал **117019** наблюдений, **117014** префиксов с hero, **489** полных проекций и **116530** дельт. Есть7 удалений связанных сущностей;117018 записей имеют exact prefix account match, одна — неизвестный account. Остальные ранние hero-проекции неизвестны до primary mapping. Это число source transitions, не число возможностей или решений. Дополнительный проход71865 clock records подтвердил отсутствие исчезновения прежде полученных clock operands и удаления выбранного Steam identity на этом конкретном replay.

Финальный `raw-constraints.jsonl`: 139848634 байта, SHA256 `5e5d4bc6e4c54c59eb0910a0844f49e44f269d8b3865a89b3b491340dc9641f7`. 8 октября окончательный writer заново обработал весь исходный trace, проверил полный source SHA и опубликовал файл атомарно. Ранее нормализованный промежуточный sidecar заменён свежим результатом; перенос или ручное исправление его строк в финальный файл не выполнялись. Census сохранился, но ранние mapping receipts и transition reasons изменились: теперь есть один `resource_selected_hero_changed` и один `primary_mapping_changed`. Reader проверяет весь поток и полный digest. Проверка неизменённых receipts опирается на уже проверенный префикс и монотонность record/tick; новые delta parents проверяются целиком. На предыдущем артефакте эта оптимизация сократила чтение с 268 до 64 секунд; время окончательного чтения фиксируется отдельно в `raw-constraints-summary.json`.

`ingest/event_visibility.py` извлёк **115576** записей из полного combat-names sidecar. Radiant: explicit true 77540, explicit false 0, отсутствует 38036. Dire: true 82265, false 0, отсутствует 33311. Пропущенное proto2 optional поле остаётся unknown. Производный файл: 131485916 байт; SHA256 `89e9061b400fbe16939cd025bc1d944ab97409cead0af998a07f61ae055796af`. Эти флаги относятся к payload боевого события; они не устанавливают непрерывный FoW конкретного поколения сущности или доступность сигнала на экране.

## Исправленные предположения

- В replay имеется raw источник spectator orders; прежняя формулировка «источника команд вообще нет» слишком широкая. Полнота собственных attempts/accepted/commit всё ещё неизвестна.
- `ability_id` нельзя соединять с catalog item ID. Среди 4632 no-target orders значение116, соответствующее текущему catalog BKB, встречается ноль раз; семантика связи отдельно требует проверки.
- `entindex`, raw `m_iPlayerID` и resource slot не взаимозаменяемы. Используется prefix mapping по exact handle/index/serial, без арифметической догадки.
- Cached primary mapping не доказывает текущую связь аккаунта с героем. Удаление или замена поколения `PlayerResource`, смена/удаление Steam identity и смена/удаление selected-hero handle отзывают связь. Она восстанавливается только по текущему ресурсу, его собственному exact selected handle и соответствующему mapping. Поздний baseline уже удалённого поколения не восстанавливает прежний аккаунт; полный baseline текущего ресурса без Steam identity также отзывает аккаунт. Эти усиления действуют в raw transition callback; прежний sampled dossier contract проверен отдельно.
- `last_order_latency=4294966296` нельзя выдавать за измеренную задержку в миллисекундах.
- Manta сортирует messages внутри packet по priority: callback sequence не доказывает simulation/subtick или полный исходный wire order.
- Отсутствие hero FoW поля в ограниченном audit sample не доказывает отсутствие поля во всём replay. Vision radius и selection ring не являются FoW.

## Переносимые команды

```powershell
go run . --orders MATCH.dem
python -m dota_coach.cli orders-source --source-jsonl ORDERS.jsonl --extraction-json EXTRACTION.json --out ORDERS-SUMMARY.json
python -m dota_coach.cli constraint-source --source-jsonl TRACE.jsonl --extraction-json EXTRACTION.json --resource-slot 0 --actor npc_dota_hero_kez --account-id ACCOUNT --out CONSTRAINTS.jsonl
python -m dota_coach.cli event-visibility-source --source-jsonl COMBAT-NAMES.jsonl --extraction-json EXTRACTION.json --source-sha256 SOURCE_SHA --replay-sha256 REPLAY_SHA --out VISIBILITY.jsonl
```

Go-команда запускается из `replay_tool`; stdout записывать как бинарный UTF-8 поток, без изменения encoding PowerShell. Для Python доступны также `scripts/run_local.py` и установленный CLI. Writer constraints/visibility публикует результат атомарно только после проверки целого входа и footer. Orders reader требует полный завершающий census, версии, wire types, диапазоны clocks и совпадение replay manifest/audit. Ни один reader не принимает self-promotion до verified gameplay.

`trace-review` и `serve` принимают `--orders-jsonl`, `--constraint-source-jsonl`, `--event-visibility-jsonl`. В HTML появляется «Полученные данные replay» и `replay-sources.json`. Счётчики orders и event flags ретроспективны и отделены от notebook/оценки выбора. Реальные labels, POV и quality grants не создаются. Локальный helper подключает существующие sidecars автоматически; пути и исходные replay исключены из релизных архивов.

## Проверки и оставшаяся работа

Регрессии проверяют future identity/receipts, exact generation/deletion, отсутствие hidden enemy projection, hash/footer/count mismatch, wire type/range violations, oversized records, atomic preservation и неизменность notebook после подключения ретроспективного census. Независимый инженерный review проверяет source admission; это не экспертная оценка Dota. Актуальные результаты полной suite, UI, archive audit и installed smoke фиксируются в `out/verification/release-readiness.json`.

Финальные исходники: **1144 Python tests,14 Go tests**; full suite, module verification и сборка прошли. Независимый повторный инженерный review после исправления resource/mapping lifecycle выполнил 73 focused tests и пять отдельных проверок смены аккаунта, stale baseline, missing/mismatched handle и восстановления связи; новых существенных замечаний в этом ограниченном scope нет. Полный audit сохранённого trace нашёл один resource baseline и ни одной замены/удаления `PlayerResource`; усиленный контракт ранних mapping receipts всё равно проверен новым полным извлечением финального sidecar. Wheel проверен после установки в чистый временный venv вне checkout, без PYTHONPATH/PYTHONHOME; новые source модули, CLI и офлайн fixture report входят в smoke check. Все 105 упакованных project files совпали байт в байт с финальными исходниками. Sdist/wheel исключают runtime, replay, corpus, out и личные пути. Windows-проверки выполнены локально; GitHub/Linux CI ещё не запускался.

Полное ТЗ не объявляется выполненным. Следующие программные требования: проверяемый join orders с собственным actor/item generation и стадиями исполнения; conversion raw operands в finite constraint truth transitions с исторической механикой; cue/POV и actual FoW/last-seen; полные cast/control/target rules; TP arrival/interruption, smoke break; исторические map/navigation/safety; item/threat/utility и contextual build rubric. Клиентная сверка, независимые реальные labels/holdout и baseline/followup остаются внешними входами. Полный список — [external validation inputs](2026-10-07-external-validation-inputs.md).
