# Переносимая установка и внешняя проверка

Актуальный сквозной запуск и backend review API: [интегрированная аналитика](docs/implementation/2026-10-08-integrated-analytics.md). Новые CLI доступны в установленном wheel; schemas и пример ограничений указаны в документе. Portable proposals остаются без права выдавать игровые советы.

Последнее расширение: [один удар и gate допуска](docs/implementation/2026-10-08-single-impact-stage.md). Команды `defensive-impact-review --help` и `criterion-gate-review --help` доступны также в установленном пакете. Первая вычисляет условные альтернативы по typed proposal, вторая пересчитывает quality из dataset/predictions/annotations. Portable JSON не открывает release или inference. Для `trace-review`/`serve` предусмотрен `--defensive-impact-json PATH`; отсутствие входа показано в отчёте явно.

Последний этап: [реальное source extraction](docs/implementation/2026-10-07-replay-source-stage.md). Команды `orders-source`, `constraint-source`, `event-visibility-source` извлекают и проверяют raw receipts. Отчёт и `serve` принимают три новых optional sidecar; непроверенные значения не становятся игровыми вердиктами. Примеры запуска приведены в документе.

Новое исполнение: [choice-monitor и command-review](docs/implementation/2026-10-07-continuous-command-stage.md). Команды принимают strict typed input, экспортируют DatasetRecord через `--manifest-json` и выполняют reviewed calculation через `--dataset-jsonl/--annotations-jsonl/--replay-sha256`. Без отдельно проверенного покрытия результат неизвестен. Процедура и schemas приведены в документе этапа.

Актуальное расширение: [choice/knowledge/ward analytics](docs/implementation/2026-10-07-choice-knowledge-ward-stage.md). Реальный отчёт содержит `choice-windows.json`, `objective-state.json`, `ward-analysis.json`; форма варда сохраняет вычисленный callback context. Новые команды доступны через `python -m dota_coach.cli choice-review --help`, `knowledge-review --help`, `ward-review --help`.

Для имеющихся локальных входов:

```powershell
python scripts/run_local.py choice-review --extraction-json out/real-analysis/extraction.json --action-states-json out/real-analysis/action-states.json --out out/choice-review.json
python scripts/run_local.py ward-review --source-json out/real-review/ward-observations.json --ward-id ward:9030822324:219:107:record:58347 --out out/ward-review.json
```

На чистой машине нужны собственные входы. Схемы typed choice/temporal inputs и exact reviewed binding описаны в документе этапа. Candidate arithmetic без independent binding не выдаёт положительную admitted feasibility. Полный игровой критерий ещё не проверен.

Последнее расширение добавляет `semantic-lifecycles.json`, `resource-opportunities.json` и `ward-observations.json` в реальный отчёт. Через `serve` раздел «Задача варда» принимает явно подтверждённую текущую цель и сохраняет редакции в `ward-plan-history.jsonl`. Статический HTML не записывает планы. [Результаты и границы](docs/implementation/2026-10-07-remaining-analytics-stage.md).

Этап от 7 октября: `trace-review` и `serve` принимают `--combat-names-jsonl PATH` для прямых TP/smoke/modifier events. В локальном отчёте доступны план запаса маны и слепая форма разметки; [правила и ограничения](docs/implementation/2026-10-07-semantic-review-stage.md).

В отчёте через `serve` раздел «Контекстный план покупки» принимает явно подтверждённую цель, эпизод и выбранные предметы. Введите остаточную цену только если знаете её: текущая полная цена каталога её не заменяет. Последняя редакция восстанавливается после обновления страницы, текущий JSON можно скачать. История хранится в `build-plan-history.jsonl` соответствующей задачи. После перезапуска сервера старые сессионные jobs не восстанавливаются. [Описание API и границ проверки](docs/implementation/2026-10-07-contextual-build-plan.md).

Используйте Python **3.12** и Go **1.24**. Эти версии входят в CI для Windows и Linux. Другие версии Python не проверены; ограничение `numpy<2` может потребовать сборки из исходников на новых интерпретаторах. Никакая команда ниже не требует локальной `.runtime`, пользовательских путей или чужого virtualenv.

## Чистая среда

Из корня исходников:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -c constraints-python312.txt -e ".[dev]"
.venv\Scripts\python -m pip check
.venv\Scripts\python scripts/check_project.py
```

Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints-python312.txt -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python scripts/check_project.py
```

Если Go пока нет, `scripts/check_project.py --python-only` проверяет только Python и явно пропускает Go. Параметр `--go PATH` выбирает конкретный Go executable. Зависимости Go закреплены `go.mod`/`go.sum`; проверка использует `-mod=readonly`. Файл `constraints-python312.txt` закрепляет протестированное разрешение Python dependencies; это не lock с хешами всех платформ и не сертификат безопасности. Обновления зависимостей нужно отдельно проверять.

OpenCV используется без GUI. Внешний Tesseract нужен только для OCR через `pytesseract`; офлайн-отчёт, контрактные тесты и template OCR не требуют установленного Tesseract. Доступность видеокодека может отличаться; тест синтетического MJPG отмечает отсутствие кодека как skip. FFmpeg предоставляется зависимостью `imageio-ffmpeg`.

## Демо без сети и реальных данных

```powershell
.venv\Scripts\python scripts/build_synthetic_demo.py
```

Открыть `out/full-demo/index.html`. Все входы этого примера синтетические. Он проверяет работу программы и состояния интерфейса, не качество оценки реальной Dota.

Минимальный установленный CLI:

```powershell
.venv\Scripts\python -m dota_coach.cli dossier --match-json tests/fixtures/opendota_match_sample.json --replay-jsonl tests/fixtures/replay_sample.jsonl --account-id 111 --synthetic --out out/evidence-demo
```

## Реальные входы

Файлы `out/real-*` из локальной инженерной проверки **не входят в исходный архив или wheel**. Команда `scripts/real_workbench.py` — удобство только для подготовленного локального корпуса; на чистой копии его нужно подготовить.

Сначала получить публичный replay и source receipt:

```powershell
.venv\Scripts\python scripts/acquire_public_replay.py --match-id MATCH_ID --out out/real-data
```

Доступность конкретного replay ограничена источником и сроком хранения. Отсутствующий replay не заменяется данными другого матча. Полученный source receipt описывает транспорт и хеш, а не экспертную проверку. Сетевые ответы OpenDota/Valve могут измениться или оказаться недоступны.

Для нового v3 trace собрать Go source:

```powershell
go -C replay_tool build -mod=readonly -o replay_tool.exe .
.venv\Scripts\python scripts/extract_trace.py --dem out/real-data/MATCH_ID.dem --trace out/real-data/trace.jsonl --names out/real-data/combat-names.jsonl --enriched out/real-data/trace-enriched.jsonl
```

Wrapper пишет stdout байтами и атомарно публикует завершённый файл, поэтому PowerShell не меняет encoding JSONL. Он печатает SHA-256 исходного `.dem`. Режим `--combat-names` отдельно извлекает разрешения имён из callback prefix; объединение проверяет replay hash, порядок и payload. Три trace-файла могут занимать много места; они остаются в игнорируемом `out`. Передавайте в `trace-review` соответствующие `--match-json`, `--trace-jsonl out/real-data/trace-enriched.jsonl`, напечатанный `--replay-sha256`, `--account-id` и source snapshot каталога. Для уже сохранённого компактного извлечения используйте `--extraction-json`. Пример списка механик:

```powershell
.venv\Scripts\python -m dota_coach.cli catalog --item-id 116 --item-id 37 --item-id 102 --item-id 254 --cache out/valve-catalog --out out/valve-catalog.json
.venv\Scripts\python -m dota_coach.cli trace-review --match-json out/real-data/match-MATCH_ID.json --extraction-json out/real-analysis/extraction.json --catalog-json out/valve-catalog.json --catalog-raw-dir out/valve-catalog/raw --account-id ACCOUNT_ID --out out/review
.venv\Scripts\python -m dota_coach.cli serve --match-json out/real-data/match-MATCH_ID.json --extraction-json out/real-analysis/extraction.json --catalog-json out/valve-catalog.json --catalog-raw-dir out/valve-catalog/raw --out out/workbench
```

`serve` слушает только `127.0.0.1`. Выберите игрока, создайте отчёт и дождитесь статуса готовности. Сервер показывает только перечисленные артефакты созданных задач, а не дерево файлов компьютера. Эта рабочая область предназначена для локального пользователя; не выставляйте её через proxy или публичный tunnel. Вердикты остаются `insufficient_evidence` до клиентной и экспертной проверки; передача проекта тестерам не открывает этот gate.

Для подробных собственных предметов и ресурсов:

```powershell
python -m dota_coach.cli action-states --trace-jsonl out/real-data/trace-enriched.jsonl --extraction-json out/review/extraction.json --resource-slot RESOURCE_SLOT --actor npc_dota_hero_HERO --out out/action-states.json
```

`RESOURCE_SLOT` — replay resource slot 0–9, не OpenDota player_slot128–132 и не m_iPlayerID. Actor и slot проверяются по выбранному герою extraction. Затем передайте `--action-states-json out/action-states.json` в `trace-review` или `serve`. Raw properties сохраняются с точным handle/generation и prefix references; неизвестные control/patch semantics не превращаются в True/False feasibility.

В `serve` блок «Выбрать упражнение» требует вашей явно подтверждённой цели. На странице упражнения заполните два периода и каждую подходящую ситуацию. Черновик хранится в этом браузере; журналы можно скачать. Отправка проверяет context/assignment/disjoint periods и сохраняет отчёт. Импорт через `training --goal-json ... --scope-json ... --baseline-json ... --followup-json ... --out ...` поддерживает те же проверки. Входной JSON не может сам подтвердить экспертную проблему, независимое наблюдение или verified completeness: такие declarations по умолчанию demoted.

Критерий `reserve-review --input-json ... --dataset-jsonl ... --annotations-jsonl ...` описан в передаче на тесты. Отсутствие независимой разметки возвращает объяснённый отказ, а не случайный игровой вердикт.

## Проверить исходный архив и wheel

Дополнительные источники и модель маршрута:

```powershell
python scripts/extract_orders.py --dem out/real-data/MATCH_ID.dem --out out/real-data/orders-context.jsonl --context
python -m dota_coach.cli commands-source --source-jsonl out/real-data/orders-context.jsonl --extraction-json out/real-analysis/extraction.json --account-id ACCOUNT_ID --out out/commands-summary.json
python -m dota_coach.cli mechanics-source --source-jsonl out/raw-constraints.jsonl --extraction-json out/real-analysis/extraction.json --account-id ACCOUNT_ID --out out/mechanics-summary.json
python -m dota_coach.cli movement-review --input-json route-proposal.json --out out/movement-review.json
```

Передайте `--command-binding-jsonl out/real-data/orders-context.jsonl` в `trace-review` или `serve`. `--movement-input-json route-proposal.json` принимает типизированный контекст собственной команды. Переносимый JSON не содержит допуска источников/механики; без него результат остаётся unknown. Модель вычисляет условные границы пути, но не утверждает фактическое прибытие или безопасность. Поток orders-context содержит только links, совпадающие с raw ability index, а не полный census инвентаря; отсутствующий link остаётся unknown. [Финальная матрица требований](docs/implementation/2026-10-08-tz-closure.md) отделяет исполнение от реальной игровой проверки.

```powershell
.venv\Scripts\python -m build --no-isolation
.venv\Scripts\python scripts/check_package.py dist
.venv\Scripts\python scripts/check_installed.py dist
```

Build использует явный allowlist, независимый от родительского Git checkout. Проверка отсекает runtime, replay, большие файлы, executable, links/traversal и персональные абсолютные пути. Затем wheel устанавливается в новый temporary virtualenv и запускает CLI/отчёт **вне исходной папки**, без `PYTHONPATH` и `.runtime`. Для полностью офлайн-установки передайте `--wheelhouse DIRECTORY` с заранее загруженными dependencies. Эта проверка не скачивает API-данные.

Wheel содержит Python-модули и текстовые resources; Go source, tests, scripts, CI и актуальный архитектурный пакет Markdown входят только в sdist. Runtime Go binary, видео, публичный corpus и source receipts не распространяются. Старые документы `docs/superpowers` остаются в проектной папке и не включаются в source distribution.

Git checkout, commit, push и публикация здесь не создаются. Если проект находится внутри постороннего Git checkout, не выполняйте команды Git до выбора собственного репозитория. Для внешней проверки можно передать проверенный sdist и отдельно согласованный набор входных данных. У проекта пока нет явно заданной лицензии; автоматическая подготовка архива не назначает лицензию и не публикует пакет.

Источник снарядов: `replay_tool --projectiles replay.dem`; загрузчик `projectiles-source --source-jsonl FILE --extraction-json EXTRACTION --account-id ACCOUNT --out OUT` поддерживает `--cutoff-record-index`. `trace-review`/`serve` принимают `--projectiles-jsonl`. Подробности: [проверка источника и границы](docs/implementation/2026-10-09-projectile-source.md).


Для source graph единиц добавьте `--unit-control-trace <полный replay-trace.v3.jsonl>` к `trace-review`/`serve`. Это потоковая полная проверка большого файла; cold report занимает больше времени. Отдельная команда: `unit-control-source --source-jsonl <trace> --extraction-json <extraction> --account-id <id> --cutoff-record-index <record> --out <summary.json>`. Несколько границ передаются повторением `--cutoff-record-index` в возрастающем порядке. Границы source-local; command agency и player visibility не устанавливаются.

### Аудит стадии команды

`python -m dota_coach.cli command-stages-source --source-jsonl <orders-context.jsonl> --extraction-json <extraction.json> --account-id <positive-account> --cutoff-record-index <source-local-cutoff> --out <command-stages.json>`

Cutoff относится к orders-context, а не к entity trace. CLI не принимает registry JSON и не превращает raw приказ, queue removal или HUD error в попытку/отказ. Условия typed API и ограничения: [command-stage bridge](docs/implementation/2026-10-09-command-stages.md).

## Локальная запись для реального отчёта

`trace-review` и `serve` принимают `--video PATH --video-offset SECONDS`, а `scripts/real_workbench.py` передаёт эти опции готовому локальному серверу. Offset обязателен при записи: video time = source game time + offset. Это заявленная пользователем приблизительная навигация; она не подтверждает POV, simulation clock или момент выбора. Извлекаются только короткие clips с проверкой кадра и hashes; исходная запись не обслуживается HTTP. При недоступном FFmpeg, неизвестном времени или отсутствии кадра карточка сообщает причину и аналитика продолжает работать. `--ffmpeg PATH` задаёт инструмент явно; по умолчанию используется imageio-ffmpeg/PATH. Запись не входит в архивы.
