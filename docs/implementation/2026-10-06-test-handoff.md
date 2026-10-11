Текущий прогон 9 октября после расширения графа единиц: 1686 Python / 21 Go passed. [Текущий модуль и пределы](2026-10-09-unit-control.md). Финальные archive/install/browser receipts берутся из `out/verification/release-readiness.json`; остальные числа ниже описывают предыдущие этапы.

Актуальная передача: [снаряды и source prefix, 9 октября](2026-10-09-projectile-source.md). Текущий общий suite 1642 Python / 21 Go; окончательные SHA и browser proof в release-readiness.json. Ниже исторические этапы.

# Foresight: передача исходников и внешняя проверка

Дата: **6 октября 2026 года**. Исходники подготовлены к установке и проверке. Это инженерный этап, не разрешение публиковать сервис как проверенного игрового тренера. Git commit/push/deploy не выполнялись: текущая папка не является самостоятельным checkout; родительский Git не использован.

## Рабочие потоки

Актуальная передача: [интегрированная аналитика 8 октября](2026-10-08-integrated-analytics.md), **1576 Python / 18 Go**, новый final proof после archive/installed/browser проверки. Прежние counts и перечни отсутствующих generic переходов относятся к прошлым исходникам. Подтверждённых реальных игровых выводов 0.

**Последнее расширение 8 октября:** [условный критерий одного удара и default-closed gate](2026-10-08-single-impact-stage.md). Финальная общая проверка: **1359 Python-тестов, 18 Go-тестов**, Go modules/build; итоговый source/installed/archive/browser proof — `out/verification/release-readiness.json`. Последующие числа относятся к предшествующим этапам. Реальные labels и игровые вердикты по-прежнему отсутствуют.

**Финальная передача 8 октября:** [единая актуальная матрица ТЗ](2026-10-08-tz-closure.md). Подключены exact raw command→entity/handle links, поток механических условий и условная модель маршрута. На реальном replay: 1314 item/ability links, 38 raw BKB references, 117019 изменений собственных условий. Проверены **1223 Python-теста и 18 Go-тестов**; игровой вердикт не допускается автоматически. Хеши пакетов, installation smoke, независимое инженерное review и свежий browser result находятся в локальном `out/verification/release-readiness.json`. Следующие абзацы сохраняют историю этапов, а не заменяют эту матрицу.

Последнее исполнение: [реальные источники приказов, изменений ресурсов и видимости событий](2026-10-07-replay-source-stage.md). Добавлены raw extractor/streaming readers, strict source receipts и `replay-sources.json` в отчёте. Прежние утверждения ниже об отсутствии любых raw command/constraint sources относятся к прошлому этапу: источники получены, но попытки/стадии/continuous truth/attention ещё не проверены. Актуальные тесты и archive SHA — в release-readiness.

Последующее исполнение: [continuous/command stage](2026-10-07-continuous-command-stage.md). Добавлены типизированные потоки, монитор непрерывных constraint spans, attempt/stage census, strict loaders, exact manifests и отзыв допусков latest revisions. Финальный повторный read-only инженерный review подтвердил устранение выявленных ложных grants. Актуальное число тестов и архивные SHA — в release-readiness;939 ниже относятся к предыдущему этапу. Реальные command/cue sources и game quality не аттестованы.

Актуальное продолжение **7 октября**: [вычисляемая аналитика выбора, знаний и вардинга](2026-10-07-choice-knowledge-ward-stage.md). Добавлены choice resolver на отдельных samples, operand feasibility, observation TTL/conflict projection, objective prefix и ward callback/attribution analysis. **939 Python tests и 9 Go tests**; fresh wheel/sdist и installed smoke фиксируются в release-readiness. Ни continuous opportunity census, ни real FoW/POV, ни tactical quality этим не аттестуются. Следующие абзацы описывают предыдущие этапы и их собственные проверки.

Финальное расширение **7 октября**: [TP/smoke intervals, sampled inventory census, задача варда и исправления предположений](2026-10-07-remaining-analytics-stage.md). [Недостающие внешние входы и критерии допуска](2026-10-07-external-validation-inputs.md) отделены от выполненных программных проверок. На реальном replay readiness не определяется из непроверенного `m_fCooldown`; legacy flags также демотируются.

Обновление **7 октября 2026**: [новый сквозной этап](2026-10-07-semantic-review-stage.md) добавляет прямые TP/smoke/buyback/objective events, source-local историю, ресурсный план в карточке и форму слепого human review. Deep lifecycle/visibility/quality validation по-прежнему не завершены.

Дополнение: [план покупки](2026-10-07-contextual-build-plan.md) связывает собственный prefix, явно указанную цель, выбранные предметы и заявленные остаточные расходы. Редакции сохраняются с SHA-chain и датой, переход между эпизодами обозначается как сценарий, а не прогресс. После reload результат восстанавливается; новая цель и подтверждение остаются пустыми. Проверить отказ без подтверждения, пустую цену как unknown, различие full/remaining cost, смену goal/anchor и отклонение устаревшей редакции.

1. Реальный публичный replay **9030822324** → Go v3 trace → компактное извлечение → проверка SteamID/hero/source hashes → 5 наблюдаемых защитных активаций → собственные inventory prefixes → карточки, карта, покупки, профиль и слепой пакет разметки. Реальные ward events: 262; own inventory samples: 2999. Подробная сырая мана перед первой активацией: **691.0007**, поле стоимости BKB: **50**, арифметический остаток: **641.0007**. Это другой, более точный префикс относительно 1Hz-среза; ни один из них не выдан за подтверждённый момент выбора.
2. Явный выбор личной цели → конкретное упражнение → существующие учебные матчи под задачу → журнал всех подходящих/исключённых/неизвестных случаев → проверка сравнимости → описательная дельта. Черновик, заметки, экспорт, ошибки ввода и отсутствие истории поддержаны. Самооценка не превращается в экспертный эталон или диагноз.
3. `declared-mana-reserve.v1` вычисляет ограниченную проверку ресурсного плана из собственных mana/cost facts. Пользователь заранее задаёт резервируемое действие, число применений и запас. Требование `cost × repetitions + margin` сравнивается с немедленным остатком после активации и удержания. Нет future regeneration, скрытых врагов, utility numbers от автора JSON или прогнозов альтернативного исхода.
4. OpenDota/Valve источники имеют hash/time/body/identity receipts; ошибки сети/кеша и отсутствие подходящих матчей представлены отдельно. Подбор задачи использует реальные teamfight/purchase/ward pointers и GPM/LH/deaths/wards/participation с missingness. Это описательное сравнение, не доказанный устойчивый стиль.

## Запуск тестировщиком

Чистая установка и сборка описаны в `INSTALL.md`; Python3.12, Go1.24. CI `.github/workflows/tests.yml` запускает Windows/Linux contracts, Go module verification/tests/build, wheel/sdist audit и smoke установленного wheel вне checkout. CI ещё не запускался на GitHub: workflow подготовлен локально.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -c constraints-python312.txt -e ".[dev]"
.venv\Scripts\python scripts/check_project.py
.venv\Scripts\python scripts/build_synthetic_demo.py
```

Открыть `out/full-demo/index.html`; данные этого потока синтетические. Реальный локальный корпус в `out/real-*` не входит в архив. В текущей подготовленной папке `python scripts/real_workbench.py` открывает рабочую область на `http://127.0.0.1:8765/`; статический реальный отчёт — `out/real-review/index.html`. На новой машине получить собственный replay/source snapshot и выполнить команды `INSTALL.md`.

Архив исходников содержит src/tests/scripts/Go source/assets/CI и актуальный архитектурный пакет markdown. Не содержит replay, бинарников, локальных runtimes, временных данных, private caches или metadata чужого Git. Wheel — только приложение и необходимые package resources. Перед импортом на GitHub используйте собственный checkout и отдельную ветку с префиксом `codex/`; локальные `out` и `.runtime` не добавлять.

## Что проверять в интерфейсе

- Отчёт создаётся для выбранного аккаунта; одинаковый герой не заменяет SteamID join. Чужой или повреждённый own-prefix artifact отклоняется.
- Активация, момент выбора, доступность команды и замеченная угроза разделены. Два разных временных среза показывают свои источники; состояние после каста не подставляется вместо предшествующего.
- В упражнении цель пустая и checkbox подтверждения выключен по умолчанию. Без явного выбора упражнение не назначается.
- В журнале False и unknown различаются. Include все возможности, не только успешные. Пересечение матчей/дат, другая роль/герой/patch/source или неполный учёт отменяет сопоставимую дельту. Нет новых подходящих случаев — недостаточно данных.
- Desktop/mobile не имеют горизонтального overflow, ссылки таймлайна открывают скрытую карточку, map seek меняет время, feedback сохраняется с hash контекста. Файлы и пользовательские строки не становятся executable HTML.
- Host/token/size/path guards защищают локальные endpoints. Это loopback workbench, не публичный multiuser backend.

## Допуск mana-reserve для независимого исследования

`reserve-review --input-json INPUT --dataset-jsonl DATASET --annotations-jsonl LABELS --out REPORT` принимает strict schema `foresight.mana-reserve-input.v1`. Поля: decision/match/subject/patch, boundary, action, goal, dataset_kind и ровно пять Fact:

`self.mana`, `self.selected_mana_cost:<selected action ID>`, `self.reserve_mana_cost:<reserved action ID>`, `self.activation_feasible`, `self.hold_feasible`.

Весь input привязан к DatasetRecord input hash/target/match/patch/replay identity. Два разных human extraction reviewers должны проверить correctness и availability каждого факта. Отдельные decision-blinded reviewers проверяют `boundary:<boundary ID>`, `goal:<goal ID>`, decisive boundary refs и action-cost links через ActionCheck. Их labels должны считать конкретный контекст assessable; `insufficient_evidence` не включает расчёт. Последние revisions могут отозвать допуск. Legacy/unknown clock, будущие/несвежие сведения, неверные action links, неизвестные operands и overflow приводят к отказу. Файл INPUT не содержит самоприсвоенного validation status.

Даже при достаточных reviewed declarations output остаётся **unverified research**, strategic_quality=not_established, training_eligible=False. `good`/`probable_error` относятся исключительно к заявленному запасу, не к качеству драки: цель сама может требовать пересмотра. Независимость людей, клиентная проверка, historical costs и provenance review — отдельные внешние обязательства.

## Чего пока нельзя утверждать

Независимых экспертных labels на реальных случаях **0**, игровых вердиктов с проверенным критерием **0**. Не выполнены клиентная сверка, запись игрока/POV, проверенные control/visibility semantics, полный nonactivation opportunity census и валидация одного предмета против конкретной угрозы на историческом патче. Из этого следуют ограничения на actual cast feasibility, confirmed habits, tactical ward usefulness и optimal contextual builds. Глубокие TP/smoke/objective/visibility semantics пока не закончены; raw fields не заменяют соответствующие алгоритмы.

Автоматическая browser QA использует явно помеченную тестовую цель и вымышленные journal records только для проверки формы. Эти записи не являются историей пользователя, human labels, измерением полезности или реального изменения поведения и не входят в quality cohort.

Полное ТЗ не объявляется закрытым. Максимально полезный следующий внешний тест: клиентная сверка own-state/clock/action prefixes и два независимых слепых reviewer для одного patch/item/threat criterion; затем настоящий пользовательский baseline/followup. Это позволит отделить полезный совет от правдоподобного интерфейса.

## Свидетельства проверки

После финального расширения пройдены **850 Python tests, 9 Go tests**, Go module verification/build. Архивный аудит и чистая установка свежего wheel фиксируются в release-readiness; предыдущий wheel также успешно проверялся вне checkout без PYTHONPATH/PYTHONHOME. GitHub/CI Linux ещё не выполнялись; конфигурация подготовлена.

Финальные программные проверки и архивные SHA записываются в `out/verification/release-readiness.json`; Python JUnit — `out/verification/python-tests.xml`. Go tests: 9. Browser QA: создание реального отчёта, пустые данные/ошибка формы, явный выбор цели, сохранение черновика, отправка/сравнение журналов, desktop/mobile и отсутствие JS errors. Независимый review выявил шесть ошибок новой аналитики; исправления и regression tests описаны в `2026-10-06-resource-independent-review.md`.

### Дополнение 9 октября: exact callback → conditional command stage

[Command-stage bridge](2026-10-09-command-stages.md) реализован в `ingest/command_stages.py`, CLI `command-stages-source`. Проверены exact point/root receipts, match/account/build/patch/clock, duplicate aliases, revocation и separate cast_started. На реальном sealed source выделено 1314 own raw roots из 161568 callbacks; проверенных стадий 0, attempt coverage unknown. Передача модуля на engineering tests допустима после актуального release-readiness; игровые client/POV/historical interpreters и human validation остаются требованиями. Whole-file source и review archive hashes не входят в аналитические stage features.

### Дополнение 9 октября: temporal evaluator исправлен

[Аудит момента выбора](2026-10-09-choice-temporal-audit.md): exact decimal comparisons и conservative numeric exports, strictly-readable operands/guards, causal delivery, material-removal barrier, единый prefix outer/base adapters, overlap sample/cue manifests и semantic hashes без future artifact identities. Реальные2999 resource frames пересчитаны;2999unknown,0supported/0excluded,0readable mana arithmetic. Обновлена только соответствующая JSON/HTML аналитика сохранённого отчёта. Это не клиентная или экспертная проверка.
