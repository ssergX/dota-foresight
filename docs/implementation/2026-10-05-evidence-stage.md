# Реализация доказательного этапа, 5 октября 2026

По поручению «продолжай» после архитектурного аудита выполнен первый кодовый этап S0–S2. Проверка реальных данных S1 и включение evaluator S3/S4 остаются открытыми gates.

## Изменённое поведение

- NETWORTH_SWING больше не получает MISTAKE/HIGH. Heuristic incident priority отделён от оценки; t−5 не назначается временем выбора.
- Legacy explain_note/explain_scored/run_coach возвращают детерминированный manual-review/описательный результат. LLM не вызывается и не может дописать недоказанный диагноз. Транспорт LLM сохранён для будущего ClaimSet.
- Поиск карточек/заметок/клипов переведён с game_time на episode_id. Неподдержанный incident создаёт unresolved boundary и insufficient_evidence, сохраняя ретроспективный срез отдельно.
- Новый KnowledgeSnapshot включает только allowlist собственных полей и unknown observability. Полное состояние врагов/будущие агрегаты не проходят в DecisionInput. Projection hash не зависит от hidden/future payload полного replay.
- Fact сохраняет null и причину неизвестности, source/locator, время и перспективу. ReplayManifest разделяет implementation и validation; непроверенный JSONL не может объявить себя validated.
- Replay v2 имеет float timestamps, entity generations, nullable reads, pregame wards и snapshot после обновлений tick. Identity/clock assumptions явно unverified. Python ingest проверяет структуру, значения, порядок и время; кеш публикуется атомарно только после проверки, namespace учитывает fingerprint экстрактора. Старый импорт получает предупреждение.
- Радиусная модель исправлена для prefix ward lifecycle, stale frames и отсутствующего героя. Она остаётся приблизительной, отделённой от входа оценки.
- Ручные/benchmark-сигналы LOW и описательные; sample denominator относится к целевой метрике. Исчезновение сигнала, неизвестная сопоставимость, overlap и смена версии не доказывают прогресс. Повторный анализ тех же матчей обновляет тот же период истории.
- HTML dossier раскрывает evidence, причины отказа, unknown feasibility, отдельные outcome-данные, недоступность clips/history/recommendations и тип набора. Экспортирует analysis.json. В карточке нового dossier произвольный accusing brief игнорируется.

## Проверки

Весь Python suite: **260 passed**. Дополнительные проверки покрывают hidden/future invariance, nullable facts, forbidden world predicates и вложенные payload, time uncertainty/cutoff, unresolved boundary, отсутствие активации при неполном логе, ward index reuse, stale samples, одинаковые секунды, outcome independence, неподдержанные обвинения LLM, кеш при смене parser binary и повторный анализ истории.

Go 1.24.13: `go test -mod=readonly ./...` и `go build -mod=readonly -o replay_tool.exe .` выполнены успешно. Четыре Go-теста проверяют missing-versus-zero, non-finite values, полноту координаты и null serialization. Это проверяет программу, не соответствие extraction реальной игре. Переносимый runtime скачан с официального go.dev с проверкой опубликованного SHA256, зависимости зафиксированы go.mod/go.sum. Системная установка Go не менялась.

Отчёт `out/evidence-demo/index.html` создан offline из fixtures с явной маркировкой synthetic. Проверены две карточки, пять локальных ссылок, sidecar JSON, assessed_decisions=0 и opportunity_coverage=null. Визуальная/клиентная аттестация реальной аналитики не проводилась.

## Воспроизведение

Обычная установленная Python-среда:

```powershell
python -m pytest -q
python scripts/run_local.py dossier --match-json tests/fixtures/opendota_match_sample.json --replay-jsonl tests/fixtures/replay_sample.jsonl --account-id 111 --synthetic --out out/evidence-demo
```

В этой локальной среде, где Python отсутствует в PATH:

```powershell
python scripts/run_local.py dossier --match-json tests/fixtures/opendota_match_sample.json --replay-jsonl tests/fixtures/replay_sample.jsonl --account-id 111 --synthetic --out out/evidence-demo
```

Для tests bundled Python: добавить абсолютный путь `.runtime/python-packages` в PYTHONPATH, затем вызвать тот же Python с `-m pytest -q`. Для Go выставить GOPATH/GOCACHE в `.runtime/go-work` и `.runtime/go-cache`, вызвать `.runtime/go/bin/go.exe` из `replay_tool`.

## Что ревьюить Astro

Сначала `evidence/contracts.py`, `evidence/knowledge.py`, `decisions/contracts.py`, `decisions/dossier.py`; затем ingest/replay.py/main.go; затем интеграцию episode_card/match_review/report/CLI и legacy safety/history. Новые invariance tests находятся в `tests/test_evidence_boundary.py`, `test_dossier.py`, `test_replay_foundation.py`, `test_info_state.py`, `test_history_revision.py`.

Архитектурный snapshot и старые `audit-results.json` сохраняют исходный аудит, а не текущие результаты тестов. Изменения локальные: папка не имеет собственного Git checkout, branch/commit/push не выполнялись. `.runtime`, `out` и собранный бинарник игнорируются.

## Открытые ограничения

Нет реального .dem, клиентной записи, expert annotation или locked holdout. Точная observability, предметы/касты/control, реактивный сигнал, player mapping, clock mapping и patch mechanics не аттестованы. Evaluator, profile habits, учебные матчи, билды и ward utility не включены. Opportunity discovery unavailable; ноль оценок не трактуется как хорошая игра.

Следующий этап: выполнить [ограниченный data spike](../data-spike/defensive-activation-v1.md). До Gate B/C система не должна выдавать механические обвинения или оценку альтернативного результата.
