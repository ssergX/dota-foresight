# Command-stage bridge: пределы raw приказов и проверяемая привязка стадий

Дата: 9 октября 2026 года. Это дополнительное исполнение §3/§6 исходного ТЗ, а не приёмка полного игрового тренера.

`ingest/command_stages.py` связывает строго предыдущие сообщения sealed `replay-orders-context.v1` с отдельно переданными типизированными сведениями о стадиях команды. При обычном запуске выводятся raw callbacks и точные source-local ссылки выбранного героя; стадии остаются неизвестными. Сопоставление `sequence_number`, `order_id`, близких времён или номеров записей разных sidecar запрещено.

## Контракт

- Для каждой условной стадии `StageReceipt` связывает точный root callback и наблюдаемый callback по их индивидуальным SHA256, source-local record indices, actor/action generation, transaction ID, stage и версии семантики. `StageRegistry` связывает match/account/replay/build/patch. Известные build/patch extraction проверяются; нулевой account не считается собственным игроком.
- Обязательны отдельные claims field semantics, actor/action identity, transaction link, stage semantics, clock mapping и player availability. Это caller-owned research contract, который не аутентифицирует клиента или человека. Portable JSON не загружается как registry.
- Root должен содержать уникальную own Steam/resource/selected-handle ассоциацию, selected hero в raw units и exact handle link к raw ability index. Auxiliary HUD/queue callbacks привязываются только по explicit receipt к этому root. Структурный валидатор отклоняет конфликт поколения или класса одного индекса во всех field/resource/hero/link receipts одного callback.
- Cutoff задаётся в пространстве records этого orders-context source. Поздняя доставка, будущая запись и пересечение uncertainty с cutoff не допускаются. Raw demo/net ticks, ping и latency не создают game time. Clock comparisons используют точные десятичные интервалы, включая uncertainty меньше float ULP.
- `cast_started` сохраняется отдельно. Он не превращается в `committed` и не попадает в старый пятистадийный `CommandEvent` под чужим названием. Остальные отдельно reviewed stages передаются в существующий command census; отсутствие coverage сохраняет `status=unknown`.
- Точное повторение одного receipt учитывается один раз. Другой review ID для той же semantic stage point и повторный attempt одного transaction отклоняются. Один transaction не объединяет разные roots/поколения; один exact root не переименовывается в несколько transactions.
- `prefix.input_hash` связывает только исходный raw prefix и доступные stage operands. Display example cap и archive/content hashes review не меняют аналитический хеш. Point callback hashes сохраняются. Полные review receipts и их `review_manifest_sha256`, а также полный source digest находятся отдельно. Rebuild с отозванным registry удаляет стадии; архив JSON не даёт допуск.

Raw prefix обозначен `raw_replay_source_not_player_knowledge`. Это аудит replay source, а не информационное множество игрока. Полный файл проверяется до выдачи результата; extra callback fields, разорванный footer, неверные digest/identity/build и source scope дают отказ. Размер examples ограничен 256, receipts — 512; число пропущенных примеров явное.

## Исполняемый интерфейс

```powershell
python -m dota_coach.cli command-stages-source `
  --source-jsonl out/real-data/9030822324.orders-context.jsonl `
  --extraction-json out/real-analysis/extraction.json `
  --account-id 904131336 --cutoff-record-index 161570 `
  --out out/real-analysis/command-stages.json
```

CLI читает source без registry и не принимает JSON validation flags. Для caller-owned research receipt API: `bridge_command_stages(..., cutoff=TimeRef(...), registry=StageRegistry(...))`; `StageBridge.events` содержит только условные typed stages. Проверки игровой стратегии и attempt coverage этот API не выдаёт. Выходы защищены от перезаписи входного файла.

## Реальный replay

Матч 9030822324, account 904131336, build 6943. Весь orders-context source проверен: 203763801 bytes, SHA256 `9c00ec0ce4d3fe665ecc5a7b35bc96cf926e2bca944ab9d06b1c3967619107e1`. Строгий cutoff 161570 предшествует terminal footer.

161568 SpectatorPlayerUnitOrders callbacks; зарегистрированных HUD/queue/click/CDemoUserCmd callbacks — 0. Выделено 1314 raw own linked roots, показано 256, явно пропущено 1058 примеров. Отдельных настоящих stage reviews нет: условных стадий 0, `attempt_count=null`, `attempt_coverage=null`, `training_eligible=false`. Число 1314 не является числом attempts или ошибок; нулевой auxiliary callback census не доказывает отсутствие клиентных отказов. Доказательство: `out/verification/command-stages-real.json`; audit view: `out/real-analysis/command-stages.json`.

## Проверка и остаток

Независимый инженерный аудит воспроизвёл и исправлениями покрыты: reserved clocks, duplicate review aliases, review artifact leakage в analytical hash, mismatch известного extraction build, zero-account scope и обратное соответствие root→transaction. Canonical uint32 footer build проверяется без bool/string coercion. Дополнительно исправлены row-global generation/class конфликт и округление tiny uncertainty в query/coverage command census. Тесты покрывают revocation, generation reuse, separate cast stage, explicit auxiliary roots, prefix/future invariance, source sealing и CLI overwrite guard. Фикстуры являются synthetic protocol checks, не authentic client/expert validation.

Остаются Dota-specific интерпретаторы исторических сообщений/стадий и controller agency, настоящая клиентная попытка/coverage, independently verified simulation/player clocks и POV delivery, правила исторических patch/build и внешняя игровая проверка. Typed receipt bridge закрывает программную границу между exact reviewed callback и supplied stage; он не заменяет эти интерпретаторы. TP/smoke/objective/target/channel/build классы и подтверждённая полезность тренера остаются частью полного ТЗ.
