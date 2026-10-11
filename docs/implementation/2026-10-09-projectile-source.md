# Источник снарядов и строгий callback prefix

Дата пользователя: 9 октября 2026 года. Продолжение [сквозной аналитики](2026-10-08-integrated-analytics.md).

## Реализовано

Go `replay_tool --projectiles <replay.dem>` извлекает семь callback-семейств manta v1.5.0: TE_Projectile, TE_ProjectileLoc, TE_DestroyProjectile, CreateLinearProjectile, DestroyLinearProjectile, DodgeTrackingProjectiles, UpdateLinearProjectileCPData. Сохраняются присутствующие proto2 поля, явно переданные нули и false, unknown wire bytes верхнего сообщения, raw demo/net ticks и локальный callback order. Поток закрывается footer с SHA replay, размером, build, counts и parser_completed. Это census зарегистрированных callbacks, а не полнота всех игровых угроз.

Контекст каждой записи хранит source/target/ability/entindex как независимые index/handle candidates. Generation проверяется только при совпадении текущего serial. Pool handle снаряда не интерпретируется как EntityRef. Ссылки на выбранного героя связываются с текущим PlayerResource, selected handle, resource slot и Steam ID. Raw HP/mana/позиционные поля сохранены с исходными путями и типами. Имена каталога не заменяют ability entity.

`ingest/projectile_source.py` проверяет полный поток, границы размеров, optional wire types, exact schemas, counters/footer/build/replay и контекст. Все receipts одного entity index в одном callback должны совпадать по generation/class/операндам; selection не может противоречить им. Неподдержанные top-level поля, включая arbitrary future outcome, отклоняются до prefix hashing. Полный digest хранится отдельно как provenance; raw_callback_prefix_hash зависит только от выбранных предшествующих сообщений, не от будущих сообщений/footer/digest.

`--cutoff-record-index N` включает строго записи < N в собственном domain `projectiles`. Он не принимает индекс entity trace, orders или combat_names как эквивалентный. Будущая mutation меняет whole-file receipt, но сохраняет prior prefix. Source-message brackets раздельны для tracking/linear pool families; повторное создание без закрытия и orphan closure/update учитываются явно. Это не жизненный цикл истинного игрового объекта и не прогноз попадания. TE_ProjectileLoc не трактуется как location-update предыдущего TE_Projectile.

Сквозное подключение: CLI `projectiles-source`, `trace-review`/`serve --projectiles-jsonl`, Workbench и `replay-sources.json`. В отчёте добавлен раздел `projectile-sources`. Новые данные не открывают impact/case/training gate и не подменяют пять ранее наблюдаемых активаций. Чужой replay/build, truncated source и перезапись входа отвергаются до output.

## Реальный replay

Матч 9030822324, выбранный аккаунт 904131336, build 6943. В локальном `.dem` извлечено **23 267 сообщений**: TE_Projectile 21 968; TE_ProjectileLoc 179; CreateLinearProjectile 240; DestroyLinearProjectile 240; DodgeTrackingProjectiles 640; TE_DestroyProjectile и UpdateLinearProjectileCPData по 0. Raw target associations выбранного героя: 381; source: 108; entindex: 8. Это counts исходных ссылок, не 381 доказанная входящая угроза или попадание.

Источник: `out/real-data/9030822324.projectiles.jsonl`, 58 413 274 bytes, SHA256 `19adf70b071dfcc094b115b64895c36d1a157f4f93e8b45d6241e08eca0529e4`. Полная сводка: `out/real-analysis/projectiles-summary.json`; пример prior cutoff100: `out/real-analysis/projectiles-prefix-100.json`.

Удаления tracking callbacks не наблюдаются в этом файле: 22 147 незакрытых message brackets не объявляются активными снарядами. Отсутствие callback не доказывает отсутствие попадания, dodging или завершения.

## Проверки и найденные предположения

Общий прогон: **1642 Python-теста**, 0 failures/errors/skips; **21 Go-тест**, mod verify и build. Новые тесты проверяют optional zero/false, strict prefix boundary, future mutation, generation-zero dual candidate, отсутствие own association при неоднозначном resource, pool separation, raw nonfinite wire values, чужие receipts и сквозную интеграцию. Все fixtures являются программными сценариями, не независимой разметкой игры.

Независимый read-only review: 51 focused тест и 8 дополнительных probes. Исправлены противоречия сущностей между reference fields и возможность arbitrary future fields попасть в prefix hash. Финальный review не нашёл материальных блокеров в этой ограниченной области.

Manta dispatch обрабатывает projectile user-message callbacks до PacketEntities того же пакета. Поэтому same-callback snapshot может предшествовать текущему entity update. Он не подтверждает simulation state на запуске; отсутствие candidate не опровергает существование объекта. Это ограничение сохранено в источнике и интерфейсе.

## Дополнительный независимый аудит истории

Независимая проверка ранее оставалась незавершённой; продолжена в этом запуске. Найдены и исправлены два ошибочных предположения. Сложение float могло округлить uncertainty1e-14 у границы1000ms и допустить признак, чей верхний interval edge ещё после выбора. `TimeRef.definitely_available_before` теперь сравнивает явные decimal interval bounds через Fraction; equality и callback order сохраняются. Добавлены прямой boundary regression и history-style mutation regression.

Идентичные неизвестные role/opponent proxy labels не устанавливают сопоставимость baseline/followup. Один общий guard проверяет verified role и известный нормализованный контекст для coaching, comparator и study transfer. Unknown/estimated quality и reserved/whitespace role/proxy не выпускают measurements даже при текущих case/coverage receipts. Шесть вариантов проверяют отказ без изменения чисел решений. Наличие exercise не требуется для описательного сравнения; известный контекст требуется.

Final independent post-fix review и актуальные результаты сохраняются в release-readiness.json. Это инженерная проверка протокольных fixtures, не реальные эксперты или игровой критерий.

## Что остаётся для игрового применения

Raw launch_tick не является проверенным game-time/pause mapping. Move speed не задаёт урон, а tracking target может двигаться. Particle и pool handles не устанавливают item/threat model. Source data не удостоверяют client screen exposure или внимание. Нужны проверенные historical patch/build field semantics, clock/availability receipts, соответствующий rulebook и реальные current reviewer admissions. Новый decoder даёт реальные исходные наблюдения для этих проверок; автоматически выдать из них достоверный single-impact forecast нельзя.

Общий полный продукт по матрице ТЗ остаётся незавершённым. Final package SHA, clean installed wheel, current report и browser receipts записываются в `out/verification/release-readiness.json` после завершения текущей упаковки. Предыдущий proof не относится к новым исходникам.

## Воспроизведение

```powershell
replay_tool/replay_tool.exe --projectiles path/to/replay.dem > projectiles.jsonl
python scripts/run_local.py projectiles-source --source-jsonl projectiles.jsonl --extraction-json extraction.json --account-id ACCOUNT --out out/projectiles-summary.json
python scripts/run_local.py projectiles-source --source-jsonl projectiles.jsonl --extraction-json extraction.json --account-id ACCOUNT --cutoff-record-index 100 --out out/projectiles-prefix.json
python scripts/real_workbench.py
```

В PowerShell старых версий перенаправление бинарного stdout может менять кодировку. Для canonical bytes используйте Python subprocess с output.open('wb'), как в локальном verification, либо современный byte-preserving redirect. Parser проверяет digest фактического файла.
