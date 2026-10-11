# Реальный сквозной этап Foresight

Этап проверен на публичном профессиональном матче **9030822324**, герой **Kez / ID145**, account **904131336**. Это демонстрация на существующем матче, не персональный разбор пользователя. Работа локальная: исходная папка не является собственным Git checkout; родительский Git-корень не использовался. Коммиты, push и публикация не выполнялись.

## Что исполняется

Финальные расширения и переносимая сборка описаны в [передаче на тесты](2026-10-06-test-handoff.md): own inventory prefixes, resource arithmetic, mana-reserve research criterion, выбранные пользователем упражнения/журналы, task matching и CI. Это дополнение к исходной фиксации ниже; ни raw state, ни число программных тестов не включают игровой validation gate.

| Поток | Реальная проверка | Граница вывода |
|---|---|---|
| Replay acquisition | Valve replay получен через URL OpenDota, распакован по zstd magic; `.dem` 126864874 bytes, SHA-256 `55d582de8fc9eb85d51becf0c38c28522f1277701e4bad8f053d1c0d7f6e9b47` | Транспорт/hash подтверждены; проигрывание и поля в клиенте не проверены |
| Go v3 trace | 3988112 records, completed footer и counts; selected-hero handles/generations, SteamID, resources, item/ability entities, raw modifiers/game events | Raw extraction не означает валидированные mechanics/control/visibility |
| Name resolution | 115576 combat callbacks сверены между проходами по replay hash, ordinal, payload и ticks; имена берутся из StringTables в callback prefix | Это не команда игрока и не доказательство внимания |
| Time reconstruction | server tick interval `0.033333335`, game start `879.10004`, end `3877.567`; combat timestamps нормализованы из engine clock | Нет клиентной сверки пауз; отсутствие пауз в этом матче не проверяет все случаи |
| Compact extraction | 2999 frames, 262 ward events, 2646 inventory deltas, 12589 combat observations selected types | Срезы 1Hz — навигация и контекст, не точный decision state |
| Activation notebook | 5 защитных активаций Kez; собственный строгий pre-event prefix, source references, цели-гипотезы, activate/hold tradeoffs | Choice boundary unresolved; non-activation census неизвестен; 0 проверенных вердиктов |
| Study examples | Матчи **9031046793** и **9030693809**, hero145, provider patch60, estimated position1, registered pro, binary replay prefix receipts | Goal/style/problem suitability и правильность действия не доказаны; текущая доступность cached probe не гарантирована |
| Builds | 544 item /127 hero Valve catalog, raw/receipts/hash; вопросы по цели, стоимость/cooldown/mana из живого источника, alternatives/revisit | Исторический patch bundle отсутствует; выполнимость и оптимальность неизвестны |
| Series/profile | Descriptive resources/participation/items, hero/role/provider patch/opponent rank proxy groups; missing/observed denominators | Medal proxy не numeric MMR; небольшая серия не устанавливает риск-стиль, привычку или исправление |
| Wards | Generation-aware lifecycle, prefix map/timeline, optional retrospective world hero positions | Нет точной fog geometry; raw visibility не выдаётся за player knowledge |
| Ward information | Исполнимый алгоритм novel/duplicate/joint attribution/task alignment для supplied verified prefix | Реальный verified attributed observation stream пока отсутствует; lifecycle не равен полезности |
| Review/feedback | Bound context hash, unreviewed responses, real-case blinded packet, dataset identity/split audit, fact-error consensus отдельно от verdict metrics | 0 независимых human labels, нет holdout/benefit/longitudinal validation |
| Local workbench | Loopback queue/loading/error/complete, identity checks, generated artifacts, responsive UI | Сервис анализирует заданные локальные artifacts; новый fetch/parse выполняется CLI-командами |

`out/real-analysis/extraction.json` сохраняет payload hash; importer проверяет целостность, identity и не допускает повышения capability до validated. Hash локального файла не аутентифицирует источник. Исторический patch ID OpenDota, wire patch/build и live catalog не отождествляются.

## Открыть

```powershell
python scripts/real_workbench.py
```

Адрес `http://127.0.0.1:8765/`. Выбрать игрока и создать отчёт. При отсутствии нужного файла UI покажет ошибку, при недостатке сведений — конкретный пробел. Сохранённый отчёт без сервера: `out/real-review/index.html`.

Без Python в PATH доступен установленный runtime:

```powershell
python scripts/real_workbench.py
```

Остановить Ctrl+C. Синтетический пример по-прежнему воспроизводится `python scripts/build_synthetic_demo.py`; его данные явно помечены synthetic и не входят в реальные метрики.

## Пересоздать сохранённый отчёт

```powershell
python scripts/run_local.py trace-review --match-json out/real-data/match-9030822324.json --extraction-json out/real-analysis/extraction.json --account-id 904131336 --catalog-json out/valve-catalog/snapshots/5d6998d74adf64c2b1e8ba44ff928d1e11da1e17a93edea0a75d13e0e467d136/catalog.json --catalog-raw-dir out/valve-catalog/raw --study-json out/study-live/discovery.json --out out/real-review
```

`--trace-jsonl` вместо `--extraction-json` выполняет streaming reconstruction. `--replay-sha256` связывает trace с независимо вычисленным `.dem` hash. Команда `catalog --item-id 116 --item-id 37 --item-id 102 --item-id 254` получает только read-only Valve datafeed; `study --hero-id 145 --patch opendota_patch_id:60` запускает bounded GET поиск. Availability probe читает заголовок, а не скачивает файл целиком.

Новый исходный trace:

```powershell
python scripts/acquire_public_replay.py --match-id MATCH_ID
replay_tool/replay_tool.exe --trace out/real-data/MATCH_ID.dem > out/real-data/MATCH_ID.trace.jsonl
```

Go trace напрямую включает prefix-resolved combat names. Для уже имеющегося trace доступны `--combat-names` и `ingest.trace.enrich_trace_names`; join отвергает другой replay, другое событие/порядок или неполный footer. При перенаправлении в старом Windows PowerShell следует писать stdout через бинарный stream, поскольку стандартное `>` может изменить кодировку; parser принимает UTF-8 JSONL. Полученные runtime-файлы находятся в игнорируемом `out`.

## Независимая проверка

Первоначальный этап проверял **443 Python tests**, **9 Go tests**; актуальный итог после расширений — в `out/verification/release-readiness.json`, JUnit `out/verification/python-tests.xml`. Успешен `trace-review` на сохранённом реальном извлечении. В браузере проверены queue→ready, 5 карточек, 262 ward events, переключение времени, context-bound feedback, ссылки источников/JSON, профиль и desktop/mobile без горизонтального overflow и ошибок JavaScript. Скриншоты: `out/verification/real-review-desktop.png` и `real-review-mobile.png`. Это не игровая экспертная валидация.

`out/real-review/independent-review/blinded/` содержит случаи без system verdict, utility bounds, hidden positions, outcome и raw artifact links. Датасет реальный, но находится в development. Player prefix recording ещё нужен для полноценного слепого decision review. `annotations.jsonl` пуст: шаблоны не посчитаны разметкой.

Quality CLI после получения настоящих независимых ответов:

```powershell
python scripts/run_local.py review-quality --dataset-jsonl out/real-review/independent-review/dataset.jsonl --annotations-jsonl out/real-review/independent-review/annotations.jsonl --predictions-jsonl out/real-review/independent-review/system/predictions.jsonl --split development --out out/real-review/independent-review/reviewed-quality.json
```

Не переименовывать development в holdout. В holdout должны войти новые матчи и игроки, исключённые из обучения, подбора примеров и разработки. Два annotator ID не подтверждают независимость двух людей. Фактические ошибки считаются отдельно среди однозначно проверенных facts; disagreement, missing checks и единичный reviewer не превращаются в нулевой error rate.

## Что не закрыто

Главный пробел — настоящий оценщик одной конкретной пары item/threat/patch: cue, legal actions, stable choice boundary, goal-specific utility и полный поиск supported opportunities ещё не вычисляются из валидированных replay/POV. Experimental evaluator сравнивает переданные диапазоны; это математический контракт, не модель последствий игры.

Для честного включения нужны: клиентная сверка identity/clock/inventory/control/visibility; POV/доступный cue; историческая механика; два независимых экспертных прохода на balanced corpus и отдельный holdout. После этого можно назначать criterion-specific упражнения и измерять поведение в новых сопоставимых матчах. Рекомендации под подтверждённую проблему, measured style matching, реальная ward information utility и причинная польза коучинга пока не доказаны.

Полное ТЗ не объявляется выполненным только потому, что интерфейс работает. [Постатейное покрытие](2026-10-06-tz-coverage.md) сохраняет эти пробелы. Следующий шаг с максимальной ценностью — client/POV calibration именно пяти полученных активаций и независимая разметка; новый UI или дополнительные карточки не заменят его.
