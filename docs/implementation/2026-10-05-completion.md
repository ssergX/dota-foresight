# Завершение доступного локального этапа Foresight

> Исторический отчёт на 5 октября. В следующем этапе получен реальный `.dem`, source-backed учебные примеры и каталог Valve, добавлен сквозной trace report. Актуальное состояние: [реальный этап](2026-10-06-real-pilot.md) и [покрытие ТЗ](2026-10-06-tz-coverage.md). Отсутствие `.dem` ниже описывает прежнее состояние, не текущую папку.

Этот пакет продолжает S0–S2, зафиксированные в `2026-10-05-evidence-stage.md`. Добавлены исполнимые экспериментальные S4, инфраструктура S5/S6 и независимой проверки. **S3 и допуск реального критерия не завершены:** в рабочей папке нет корпуса `.dem` + клиентных traces + независимых экспертных labels. Ни синтетика, ни тесты не заменяют эти входы.

Работа осталась локальной. Git revision не заявляется: у папки нет собственного корректного checkout, внешний родительский корень не использован. Коммиты, публикация и сообщения другим чатам не выполнялись.

## Что действительно работает

| Часть | Реализовано и проверено | Практическая граница |
|---|---|---|
| Экспериментальный evaluator | Строгий ActivationInput; boolean prerequisites и scalar bounds; точный ordered anchor; cue субъекта; альтернативы, невозможность, отказы; чистая функция и claims | Не извлекает механические условия или диапазоны пользы из replay. Действительные предмет/угроза/патч не допущены |
| Admission | Disabled по умолчанию; только явно включённый experimental; validated переключателем запрещён; input/scope/assessment hashes | Нет зарегистрированного independently validated игрового критерия |
| Ledger | Все переданные решения + неизвестные/исключённые возможности; раздельные counts; population coverage null | Это полный учёт предоставленной партии, не доказательство полного discovery в матче |
| Habits | Eligibility/assessed/unknown, примеры/контрпримеры, repeated evidence across matches; gated plan | В поставке нет реальных validated assessments. Пороги 5/3 — продуктовая политика без эмпирической проверки |
| Progress | Непересекающиеся match sets, роль/patch/criterion/evaluator/coverage, rebaseline | Дельта частоты описательная; причинный эффект тренера не установлен |
| Study | Typed catalog, real match/source linkage, replay/expertise/context/task gates; strict import | JSON declarations демотируются. Нужен provenance adapter реальных источников; рекомендованных матчей в поставке нет |
| Builds | Purchase sequence с locators; pure contextual rule API, alternatives/tradeoffs/revisit conditions | Нет проверенной patch-scoped rule registry; оптимальность не установлена |
| Ward surface | Prefix fold, pregame, generation reuse, lifecycle conflicts, censoring, interactive time slider | Схема координат, а не точная карта обзора. Utility/задача варда/безопасность установки неизвестны |
| Profile | Raw missingness, medians со знаменателями, отдельные hero/estimated-role/patch groups | Не устойчивый стиль и не диагноз; соперники/точность источника не подтверждены |
| Feedback | Три отметки, локальное хранение/JSON export, hash связи с assessment и dossier, idempotent atomic import | Unreviewed материал; никакого автоматического обучения или экспертного gold label |
| Expert validation | Blind packs, typed JSONL annotations, hash/revision binding, split audit, disagreement, confusion/coverage/false accusations/abstention metrics | Реальная статистика исключает synthetic/self labels, учитывает missing predictions. Identity/independence экспертов и закрытость holdout требуют отдельной проверки |

## Ошибочные предположения, найденные при завершении

1. Совпадение миллисекунд не означает доступность факта до выбора. Проверяются replay tick/sequence, совместимая clock mapping и интервалы неопределённости. Более поздний sequence того же tick отклоняется. Mechanical anchor должен быть ordered и exact; unverified legacy остаётся только dossier.
2. Пересечение диапазонов пользы означает отсутствие строгого доминирования, но не подтверждает разумность обеих альтернатив. Без отдельного порога приемлемости результат `insufficient_evidence`.
3. Показать экспертам utility bounds системы — значит подсказать им её ответ. Blind pack скрывает их полностью; для независимой оценки нужно отдельно предоставить доступный до выбора context/POV. Четыре boolean conditions сами по себе недостаточны для человеческого анализа.
4. Будущее не должно менять прошлую карту. Масштаб схемы фиксирован, slider сворачивает только prefix событий. Конфликт поколения остаётся конфликтом после удаления; lifetime в этом случае неизвестна.
5. Версия вердикта недостаточна для обратной связи о цели. Feedback дополнительно связан с полным dossier hash, поэтому изменение evidence не переносит старую отметку в новый контекст.
6. `lane_role` OpenDota не доказывает carry/support позицию. В portfolio роль остаётся unknown; profile явно отделяет provider `position_est` как estimated.
7. Ссылка, timestamp или статус verified в импортированном JSON не доказывают происхождение. Import никогда не присваивает verified/pro/replay available сам себе.

## Воспроизведение

Обычный Python 3.12+ с установленными dependencies:

```powershell
python scripts/build_synthetic_demo.py
python -m pytest -q --junitxml=out/verification/python-tests.xml
```

В этой рабочей среде Python не в PATH. Проверенный launcher:

```powershell
python scripts/build_synthetic_demo.py
```

`out/full-demo/index.html` содержит ссылки на пять готовых артефактов. Все данные явно synthetic. В рубрике 6 supplied opportunities: 3 experimental assessed, 2 unknown и 1 not actionable, **0 validated**. Реальный quality cohort пустой, rates null. Labels экспертов не вымышлены: файл annotations пустой, template остаётся template_only.

Offline команды по своим входам:

```powershell
python scripts/run_local.py dossier --match-json MATCH.json --replay-jsonl REPLAY.jsonl --account-id ACCOUNT_ID --out out/match
python scripts/run_local.py evaluate --batch-json ACTIVATION_BATCH.json --out out/disabled
python scripts/run_local.py evaluate --batch-json ACTIVATION_BATCH.json --experimental --out out/experimental
python scripts/run_local.py profile --match-json MATCH1.json MATCH2.json --account-id ACCOUNT_ID --out out/profile
python scripts/run_local.py review-export --batch-json ACTIVATION_BATCH.json --dataset-jsonl DATASET.jsonl --out out/blind
python scripts/run_local.py review-quality --dataset-jsonl DATASET.jsonl --annotations-jsonl LABELS.jsonl --predictions-jsonl PREDICTIONS.jsonl --out out/quality.json
python scripts/run_local.py feedback --report-json out/match/analysis.json --feedback-json EXPORTED_FEEDBACK.json --store out/feedback.json
```

Для synthetic inputs в dossier/profile добавлять `--synthetic`. `evaluate --experimental` не доказывает соответствие условий игре. Generated outputs не могут перезаписывать переданные input paths. Формат activation batch виден в `out/full-demo/inputs/activation-batch.synthetic.json`; DatasetRecord и Annotation описаны в `src/dota_coach/validation/contracts.py`. Completed annotation требует fact/action checks, evidence refs и основания недостатка данных; пустой template не принимается как label.

## Фактическая проверка

- **343 Python tests passed**, полный suite; XML `out/verification/python-tests.xml`.
- **4 Go tests passed**, pinned dependencies, `go test -mod=readonly -v ./...`.
- Сквозная интеграция генерирует dossier/evaluation/profile/blind pack/quality, проверяет все local HTML links, отсутствие derived utility в blind case, исключение synthetic из real metrics, feedback import.
- Playwright: JavaScript без ошибок в финальных страницах, desktop и viewport 390×844, нет horizontal overflow или сломанных anchors; facts закрыты на первом уровне.
- Ward slider: `t=-10/0/2/4` возвращает соответственно `1/1/0/1` наблюдаемую установку, включая pregame и новое поколение.
- Browser feedback сохраняется и связан с assessment/context hashes. Снимки интерфейса: `out/verification/match-desktop.png`, `match-mobile.png`.
- Независимый сабагент проверил новые границы. Его конкретные дефекты времени/ward conflict/JSON types исправлены; семантическое замечание о разумности при пересечении bounds принято.

Эти результаты устанавливают корректность проверенных контрактов/веток на fixtures, а не точность player identity, clocks, игровой видимости, rubric или пользы coaching на реальной игре.

## Что принять Astro и что не принимать

Принять для независимого code review: новые `decisions/evaluator.py`, `decisions/batch.py`, `learning/`, `validation/`, `wards.py`, `profile.py`, `feedback.py`, `surface.py`, CLI/report интеграцию, tests и demo script. SHA inventory относительно исходного audit snapshot находится рядом в `change-inventory.json`; это перечень изменений, не Git diff и не архив старых contents.

Не включать live verdicts по `defensive_activation.v1` до прохождения data spike из `docs/data-spike/defensive-activation-v1.md`. Сейчас остаются неподтверждёнными `m_iPlayerID/2`, tick/30 и паузы, inventory/control/cast/cue extraction, exact visibility, patch mechanics, goal-scoped utility bounds, полный opportunity census и real blind holdout. Произвольные поля batch/DTO не являются разрешением считать это проверенным.

Release gate нужен отдельный: reviewer подтверждает источники/patch scope/corpus integrity и независимую проверку. В текущем runtime такого grant нет. Так сохраняется законченный рабочий локальный этап без фиктивного объявления всей игровой аналитики готовой.
