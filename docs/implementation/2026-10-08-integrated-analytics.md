# Сквозной аналитический контур и финальная передача

Дата: 8 октября 2026 года. Этот документ дополняет матрицу исходного ТЗ и заменяет прежние утверждения об отсутствии программных переходов forecast→case→history. Полная игровая приёмка не выполнена: реальная клиентная сверка, исторические правила и независимые эксперты отсутствуют. Код не подделывает эти свидетельства.

## Законченный программный поток

`ingest/impact_prefix.py` принимает типизированный префикс клиента/replay: точные поколения актёра, предмета, снаряда и цели, момент запуска, расстояние до неподвижной цели, интервалы постоянной скорости и параметров урона, собственные HP/ману и отдельный screen cue. После проверки match/SHA/patch/build выбирается ровно одно историческое правило из caller-owned registry. Прогноз времени получается из времени запуска и distance/speed, damage — из уровня каста и параметров правила. Произошедший после выбора урон не является входом. Это конечная модель уже committed снаряда: неподвижная цель, прямой путь, отсутствие homing, ускорения, отражения, уничтожения, других ударов и восстановления. Встроенных подтверждённых правил Dota нет.

Все causal dependencies участвуют в доступности производного факта: поздно доступное правило нельзя приписать раннему сообщению о снаряде. Manifest receipts сохраняются в фактах и модели; ни один receipt не отбрасывается ради лимита DTO. Совпадение нижней границы arrival с верхней границей выбора закрывает forecast: приоритет этих событий не установлен. Экранная экспозиция не означает внимание. Без точной текущей проверки источников compiler возвращает unavailable, отдельно сохраняя допустимые raw own candidates.

`decisions/impact_pipeline.py` соединяет настоящий mint критерийного release из `criterion_gate` с точным случаем, ограниченным `ImpactAdmission`, источником выбранного действия и пятью отдельными case review passes. Пропуск действия не трактуется как hold. Accepted command относится к самой границе решения; completed activation требует отдельного времени в интервале модели. Все model/goal/facts/action/review receipts должны оставаться разрешёнными. Case packet связывает replay hash, версию, цель и вычисленные альтернативы. Программный вердикт good/reasonable_options/confirmed_error_within_criterion относится только к ограничениям явно заданной цели одного удара; стратегическое качество, обучение и общая сертификация остаются не установлены.

Case witness — точный process-local объект. Копия, JSON или вручную собранный DTO не сохраняют допуск. Testing context и известные synthetic/fixture/testing источники не входят в реальную историю даже при внешнем названии registry. Настоящая независимость людей остаётся обязанностью внешнего authenticated caller, а не строкой provider или количеством тестов.

`learning/verified_history.py` потребляет текущие minted case witnesses, точный replay/time/context и полный opportunity census каждого матча. Учитываются подходящие, исключённые, неизвестные и неоднозначные случаи; отделяются noticed, observable_attention_unknown и unreal cue. Группы требуют одинаковые account/hero/role/patch/opponent-level proxy/criterion/model/evaluator и HP/mana цели. Повторный случай или копия replay не увеличивают знаменатель. Для упражнения нужны повторение в нескольких матчах, контрпримеры, отдельная подтверждённая цель, policy и exact coaching scope. Изменение источника, coverage, release или case admission отзывает cached profile.

Стиль описывается измеренными частотами действий и собственными ресурсами. Значение признака должно быть доступно до выбора, с одинаковым способом измерения и масштабом. Редкость действия не становится ошибкой; declared style action не может противоречить наблюдаемому case choice. Baseline/followup сравниваются только при хронологическом порядке, disjoint матчах/replay и сопоставимом контексте/цензе. Изменение доли — описательный результат, не доказательство причинного эффекта тренера.

Study retrieval выбирает конкретные существующие source-backed decision episodes по тому же допущенному критерию и контексту. Проверяются replay, MatchSource, expertise/availability и текущий case. Дистанция — явное среднее нормированных различий одинаковых измеренных признаков. Собственный эпизод, копия целевого replay, неполный feature inventory или изменённый scale исключаются; forged target features не переиспользуют прежний exact target admission. Результат не утверждает win utility или сходство стиля без измерений.

`decisions/terrain.py` строит cardinal navigation graph и трёхзначный обзор по конечной исторической сетке. Supercover ray включает обе клетки при касании угла; opaque/height/radius semantics задаются явно. Неизвестная клетка не заменяется проходимой или прозрачной. Prefix blockers учитывают subject/observer/time; будущие или скрытые данные не создают обзор. Пересечение обзора считается для любых пар предложенных точек, а не только для общего пересечения всех. Derived graph сохраняет карту, все влияющие препятствия и exact prefix lineage; available_at равен границе компиляции, так что граф нельзя переиспользовать раньше. При переполнении лимита receipts граф не строится. Встроенной карты Dota нет: фактический game vision, route safety и ward utility всегда обозначены как не установленные.

## CLI и интерфейс

```powershell
python scripts/run_local.py impact-prefix-review --input-json PREFIX.json --out out/impact-prefix.json
python scripts/run_local.py case-review --input-json IMPACT.json --out out/case-assessment.json --html out/case.html
python scripts/run_local.py verified-history-review --input-json HISTORY.json --out out/verified-history.json --html out/history.html
python scripts/run_local.py terrain-review --input-json TERRAIN.json --out out/terrain-support.json --html out/terrain.html
```

Strict схемы: `foresight.impact-prefix-input.v1`, `foresight.defensive-impact-input.v1`, `foresight.verified-history-input.v1`, `foresight.terrain-input.v1`. Portable input не импортирует registry, release, case witness, validated status, future outcome или готовые metrics. Поля DTO и структурные ограничения находятся рядом с `load_*_input`; fixtures проверяют формат, не являются историческим корпусом.

`trace-review` и `serve` принимают `--impact-prefix-json`, `--terrain-input-json`, `--history-input-json`. Prefix и прямое `--defensive-impact-json` выбираются взаимоисключающе. Report binding проверяет выбранные match/account/replay/source kind/patch/build; чужое предложение отклоняется до записи. История относится к выбранному аккаунту, не превращая публичный пример в пользовательскую серию.

Backend может передать только типизированный `AnalyticsReviewContext` из `analytical_workflow.py`. `Workbench.analytical_review_provider(account_id)` получает текущие caller-owned registries при построении и повторном чтении статуса. Никакая HTTP-форма не создаёт этот context. `/api/analytics-status/<job>` повторно проверяет сохранённые process-local case/history witnesses и prefix admissions. Открытый отчёт проверяет статус при загрузке и каждые 10 секунд, пока видим; отказ или недоступный backend закрывают показ текущего вердикта/упражнения. JSON остаётся снимком и не переносит разрешение в другой процесс. Для durable reuse пакет пересчитывается.

Отчёт экспортирует `impact-prefix.json`, `case-assessment.json`, `terrain-support.json`, `verified-history.json` отдельно от исходных activation cards и global quality. Их отсутствие объясняется интерфейсом. При отзыве допуска сохраняется условная арифметика, но она не становится игровым советом.

## Проверка текущих исходников

Общий suite: **1576 Python-тестов**, без ошибок/пропусков; **18 Go-тестов**, module verification и build. Новые интеграции проверяют default refusal, source/account/patch/build mismatch до записи, запрет перезаписи входов, portable authority rejection, runtime revocation и JSON asset routes.

Независимый инженерный review проверил prefix/pipeline и terrain. Исправлены causal availability производных фактов, simultaneous arrival и потеря динамической provenance графа. Дополнительно: 625 centre rays против независимого exact Fraction intersection reference, 27 tri-state navigation enumerations, 28 отдельных pipeline probes. Ранее выполненные 216000 scalar impact alternatives и 27 criterion-gate probes сохраняют свою узкую область. History прошла тесты и review основным агентом после остановки подагентов; отдельный независимый history reviewer в этом запуске не завершился. Это явно не клиентная или человеческая игровая приёмка.

Финальные archive SHA, clean-installed smoke, package/source byte equality и browser QA фиксируются после завершения в `out/verification/release-readiness.json`. Предыдущий proof не относится к этим новым исходникам. Wheel/source находятся в `out/release-build`; локальные replay, runtimes и demo outputs в пакет не входят.

## Что можно посмотреть

```powershell
python scripts/real_workbench.py
```

Реальный матч 9030822324: пять наблюдаемых активаций, source receipts, 1314 связей item/ability и 38 raw BKB references. Клиентный projectile/POV prefix, исторический rulebook и настоящий допуск не предоставлены, поэтому новые игровые assessments отсутствуют; подтверждённых реальных советов и привычек 0.

`out/compiled-example/index.html` — отдельно обозначенный синтетический сквозной пример. Launch800ms + distance300/speed1000 даёт arrival1100ms; model damage600…640, protection multiplier0,25. Активация даёт HP340…350 / mana100, ожидание HP−140…−100 / mana150 при цели HP100 / mana50. HP — арифметический баланс, не death forecast. Это придуманный предмет/патч/снаряд и 3×3 сетка, не механика BKB и не настоящая карта. Case остаётся insufficient_evidence, history отсутствует, training запрещён.

## Честная граница завершения

Программная цепочка одного ограниченного сценария теперь исполняется, включая review→inference→history и отзыв. Нельзя объявить закрытым весь проверенный игровой продукт: нужны реальные client-prefix/POV observations, independently проверенный historical patch/item/threat rulebook и карта, authenticated reviewers, mixed heldout corpus и эксперимент полезности/поведения. Помимо этих входов, для расширения охвата остаются Dota-specific decoders/правила полных command/FoW/TP/smoke/build/ward классов из матрицы ТЗ. Generic conditional compiler не обещает, что эти декодеры уже реализованы.

Первоначальный §12 требует закончить максимально полный первый этап в доступном окружении и указать отсутствующие входы. Этот этап выполнен кодом; основной критерий проверенного понимания реального выбора пока не достигнут. GitHub не публиковался; в папке нет собственного Git checkout. Передавать архив в отдельную ветку и выполнять внешний CI.
