# Граф основного героя и raw связей единиц

9 октября 2026. Реализовано расширение §4 исходного ТЗ, а не сертификация полной модели управления Dota.

`ingest/unit_control.py` читает полный `replay-trace.v3` с ограничением размера записи, проверяет consecutive records, metadata/replay SHA, завершённый footer, полный census, actual trace SHA и build/manifest binding. Результат записывается только после проверки всего источника. CLI: `unit-control-source`. В отчёте и Workbench: `--unit-control-trace`; передаётся настоящий исходный trace, portable JSON не используется как достоверный источник.

Для заданных source-local границ граф строится строго до callback record. Whole-trace SHA находится только в общем source receipt, не в графе или его prefix hash. Равный границе callback и будущие события не участвуют в графе. Последняя ретроспективная проекция по завершению файла сохранена отдельно. Source callback ordinal не является моментом выбора или игровым clock.

Текущий PlayerResource связывается по точному SteamID, затем по текущему selected-hero handle с точным generation. Resource slot не используется как PlayerID: только raw `m_iPlayerID` выбранного героя. Несколько подходящих ресурсов дают ambiguity без выбранного героя. Полный snapshot заменяет старые поля; удаление Steam/selected handle отзывает binding. Изменение generation, Deleted и Left/Entered обрабатываются отдельно. Старое удаление не снимает новую сущность того же индекса; удалённая lifetime не воскрешается старым snapshot. Left не интерпретируется как FoW игрока.

Отдельно публикуются:

- точный selected-primary handle;
- равенство raw PlayerID и raw owner PlayerID;
- арифметическое наличие бита PlayerID в raw 64-bit control mask;
- пути через `m_hOwnerEntity`/`m_hOwnerNPC` с source receipt каждого ребра;
- присутствующий raw `m_bIsIllusion`, включая явный false, и raw replication handle.

Owner path обходится с ограничением глубины/числа посещений; циклы, отсутствующий baseline, неразрешённый или неактивный handle остаются неизвестными. Исходные bool/int32/uint32/int64/uint64 проверяются по правилам Go projection: 64-bit значения сохраняются каноническими decimal strings. `fields`/`field_types` должны иметь одинаковые ключи, а `removed_fields` не может пересекаться с добавляемыми полями или содержать дубликаты.

Граф не смешивает owner, raw mask и доступное управление. `control_available=None`, `player_visibility=None`, `validation=unverified`, `training_eligible=False`. Hero class не доказывает, что это основной герой, иллюзия или конкретный тип клона. Историческая семантика полей, управляющий controller, command agency, client visibility и поведение отдельных типов клонов остаются требованиями игрового interpreter. Source relation нельзя использовать как диагноз ошибки или персональной привычки.

## Настоящий источник

Матч 9030822324, аккаунт 904131336, replay build 6943. Использован исходный named trace 1 793 096 860 bytes из bound extraction. Пять callback границ защитных активаций: 2244708, 3232224, 3402808, 3580781, 3895340. До первых четырёх границ raw признаки связывают Kez, Courier и Poogie (3 узла); до последней — Kez и Courier (2 узла). Это исходные ассоциации, не подтверждённая управляемость или полезность единиц. Сам extractor выполнен за 161.89 seconds в текущем окружении до дополнительной проверки wire types.

В последней ретроспективной проекции 9 raw связанных узлов: в конце матча маски нескольких героев/курьеров принимают значение 31. Это существенный контрпример предположению «установленный бит автоматически доказывает собственную контролируемую единицу». Последнее состояние не переписывает пять prior graphs. Source содержит 15015 Deleted callbacks; этот count не означает смерти юнитов.

## Проверки и запуск

Focused tests покрывают primary/illusion различия, resource slot ≠ PlayerID, нулевой/неизвестный mask, canonical types, handle generations, delayed deletion, Left/Entered, retired lifetime, resource replacement/removal, ambiguous resources, циклы, future mutation invariance, byte mutation, truncation, CLI overwrite guard и отчёт без повышения качества решения. Независимый инженерный reviewer воспроизвёл две ошибки malformed projection (removed/set collision и wire/value mismatch); обе исправлены с регрессиями. Итог общего прогона, независимого review, final actual report и пакетов фиксируется в `out/verification/release-readiness.json`; предыдущие stage counts исторические.

```powershell
python -m dota_coach.cli unit-control-source --source-jsonl out/real-data/9030822324.trace.named.jsonl --extraction-json out/real-analysis/extraction.json --account-id 904131336 --cutoff-record-index 2244708 --out out/real-analysis/unit-control-prefix.json
python scripts/real_workbench.py
```

Обычный локальный запуск по-прежнему использует 8765. Во время проверки этого расширения отдельный текущий Workbench запущен на 8767, чтобы не вмешиваться в уже открытый процесс. Переносимые пакеты не содержат replay, raw trace или runtime. Полное продуктовое ТЗ остаётся неполным; это конкретное сокращение пробела в source identity/controllable entities, а не замена отсутствующих игровых правил и внешнего review.


Полный прогон финального исходного кода: **1686 Python tests passed**, 0 failures/errors/skips; Go: **21 tests**, `mod verify`, test/build passed. Focused новые проверки: 44 tests. Счётчики относятся к этой версии; это инженерные проверки, не клиентная или экспертная игровая приёмка.


Независимое final engineering review: 50 unit-control/trace tests и 45 дополнительных probes passed; оставшихся существенных замечаний не найдено. Отчёт ограничивает число explicit prior graphs первыми 128 защитными source anchors и явно сообщает число omitted anchors; тест на 129 actual source markers проверяет отсутствие аварийного завершения. Это ограничение полноты не является opportunity census. В свежем реальном отчёте все 5 anchors включены. После UI-генерации unit-control JSON/section обновлены текущим renderer для явной selection metadata и отсутствия фиктивной owner цепочки у самого primary hero; ранее проверенные source graphs и их prefix hashes сохранены.
