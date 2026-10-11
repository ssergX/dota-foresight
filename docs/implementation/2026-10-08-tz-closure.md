# Foresight: единая матрица ТЗ и приёмка доступного этапа

Актуализировано 9 октября 2026. Основание — исходное вложение `72ab3159-89a5-4b5f-aec0-83a7e8af1ee6/Вставленный текст.txt`, все 12 разделов. [Текущая архитектура и передача Sol/Astro](../architecture/2026-10-09-handoff.md) заменяет устаревшее задание повторно реализовать S0–S2.

## Область результата

Поручение архитектору — архитектура аналитики, оценка решений, аудит неверных предположений — выполнено. Исходное ТЗ требует начать с ограниченного класса (§5), выполнить первый законченный этап (§12), не реализовывать все функции одновременно и при отсутствии внешних данных закончить доступную работу с точным перечнем входов. Оно не требует выдумывать клиентную сверку или универсальное понимание всех героев.

Первый доступный инженерный результат — собственные защитные активации, evidence dossier, вычисление условных альтернатив/отказ, exact prefix и временные границы, интерфейс, реальные raw источники, разметка и проверки. Дополнительные profile/study/build/ward поверхности уже существуют. Это существенно шире первоначального S0–S2. Приёмка текущих архивов и тестов фиксируется в `out/verification/release-readiness.json`; неподтверждённая проверка не становится passed заранее.

**Главный пользовательский критерий проверенной игровой полезности пока не подтверждён. Полный validated тренер не принят.** Остаток ниже разделяет реализованные общие алгоритмы, недостающие Dota interpreters и внешние свидетельства. Честный unknown не считается доказательством качества решения или полного охвата.

## Все 12 разделов

| Раздел | Доступная работа и проверяемый результат | Граница и дальнейшая приёмка |
|---|---|---|
| **1. Главная цель** | Карточка связывает активацию, prior source, гипотезы цели, альтернативы, unknown и отдельный outcome. `defensive_impact` вычисляет ограниченные HP/mana alternatives; `impact_pipeline` выдаёт case только при текущих exact witnesses. | На реальном replay нет admitted gameplay cases. Нужен один item/threat/patch case и независимая проверка понимания/применимости совета. |
| **2. Аудит существующего кода** | Восемь зон исходного аудита прочитаны; исходные probes/snapshot сохранены. NETWORTH_SWING не получает автоматическое MISTAKE/HIGH; death incident не заменяет boundary; hidden grounding ограничен; thresholds/benchmarks описательны; отсутствие detector не означает correction. | Исходный аудит от5октября исторический. Generic сравнение решений есть, но агрегатные метрики не превращаются в подтверждённую ошибку; legacy visibility остаётся явным приближением. |
| **3. Факты/оценки/объяснение** | Fact/SourceRef/TimeRef/EntityRef, manifest/digests, world/team/screen/intent, temporal last-known/stale/conflict/unknown, strict prefix allowlists. LLM не выбирает verdict; outcome отделён. Mutation tests проверяют hidden/future values, derived/source identities и semantic hashes. | Реальная FoW/POV/cue интерпретация не подключена. У недоступного operand нет candidate arithmetic. Material claims требуют источника и текущего критерия; свободное объяснение не сертифицирует себя citations. |
| **4. Replay основа** | Go/Manta извлекает deltas, exact callbacks, combat/semantic/objective/ward events, orders-context, projectiles. Python проверяет account/Steam/selected handles/generation/lifetime; unit graph сохраняет owner/PlayerID/control-mask. Версии schema/parser/build/patch и nullable поля явны. | Проверена возможность raw extraction, не все игровые значения. Spectator order не доказывает attempt/agency/stage; callback order не simulation clock. Client identity/time/control/visibility mapping и историческая семантика остаются unverified. |
| **5. Оценка решений** | Исполняются `choice_window`, `choice_monitor`, `mechanics_adapter`, `command_census`, `mana_reserve`, `movement`, `defensive_impact`, `impact_prefix`, `impact_pipeline`. Раздельные sampled/continuous support, exact decimal uncertainty, reaction/freshness, conjunctive guards, trace-local stage bridge, HP/mana bounds и route lower/upper. | Generic finite модели работают; real pre-choice operands и historical threat exceptions не получены. Ready BKB/смерть/выживание не verdict. Полнота census и feasible альтернативы требуют отдельной проверки. |
| **6. Coaching/стиль** | `verified_history` уже исполняет full manifest→current cases→examples/counterexamples→habit/exercise, measured features, study episodes и comparable disjoint progress. История и case/source revocation перепроверяются. User-selected training/journal работают отдельно; нет self-training. | Не отсутствует generic алгоритм, а отсутствует реальная admitted история пользователя и verified census. Нужны пользовательская цель, сопоставимые baseline/followup и проверка benefit/behavior; один публичный match не является личной историей. |
| **7. Учебные матчи** | Source-backed discovery, реальные IDs/links, отдельно pro/high-rank/unknown, проверяемая availability и task matching. `select_verified_study_episodes` использует measured style/context и exact reviewed episode sources. Unavailable не заменяется выдумкой. | Два внешних учебных матча не удостоверяют стиль пользователя или superiority. Реальные measured decision episodes и независимое подтверждение transfer нужны для сильных рекомендаций. |
| **8. Билды** | Own purchase prefix, explicit goals, contextual questions, alternatives/tradeoffs, cost arithmetic, revision/reconsideration в UI/CLI. Current catalog snapshot хранит provenance. | Это scenario planning, не доказанная историческая оптимальность. Нужны historical threat→item/exception rules, actual purchase feasibility и build rubric; популярность не причинная польза. |
| **9. Карта/вардинг** | Seek/lifecycle/generations, объекты/ward events и отдельный полный replay режим. `ward_analysis` различает novel/duplicate/joint attribution; supplied-grid terrain visibility/navigation исполнимы; task/alternative revisions работают. | Real historical terrain/trees/height/FoW и безопасный маршрут не построены. Lifetime не utility; круги не точная геометрия. Typed attribution не добывает сам verified observed information. |
| **10. Интерфейс** | Локальный workbench, очередь/error/partial/source-unavailable, таймлайн, evidence cards, отдельные alternatives/outcome, study/build/ward/training/history и feedback. Supplied video navigation — дополнительный источник просмотра; отсутствие или ошибка клипа показаны отдельно. Mobile/desktop/layout и backend отказ проверяются. | Unverified source time/manual offset не POV proof и не найденный choice. Snapshot отчёта не текущая admission; default history/goals/confirmation пусты. Новый feedback не gold label. |
| **11. Качество** | Fact-quality, blinded review pack/workspace, split/holdout/patch scope, mixed good/bad outcome/alternatives/insufficient cases, false accusations/coverage/abstentions/fact errors. `criterion_gate` реально исполняет release→inference и отзыв; tests mutation/revocation проверяют default-closed behavior. | Реальные независимые labels0. Synthetic contracts не authentic corpus. Люди/клиент/holdout/benefit не удостоверяются caller flags. Вероятностных confidence claims нет. |
| **12. Первый этап/передача** | Исходный аудит, один defensive класс, данные/границы, executable evaluation+abstention, законченный dossier/workbench, реальный raw replay и edge cases, переносимые archives/install/tests и одно конечное следующее задание S3. | Доступная инженерная работа завершена при финальном proof. Product quality gate остаётся открытым. GitHub run/публикация не выполнялись; чужой parent Git не использован. |

## Фактический corpus

Публичный replay **9030822324**, выбранный account **904131336**, герой Kez, raw build6943/provider patch60. Это пример системы, не история владельца. Replay/source SHA и actual archive SHA записаны в receipts; input features отделены от whole-file admission hashes.

- 161568 match-level spectator orders; 1314 own raw links:700item+614ability. 38 BKB references и5activation/effects не являются 38attempts и33ошибками.
- 117019 constraint samples, 56297 raw linked BKB samples; field/control/cooldown semantics и verified feasibility не установлены.
- 2999 own inventory frames пересчитаны: supported0, excluded0, unknown2999, readable choice mana arithmetic0, training false.
- 23267 raw projectile messages; source/target/index associations извлечены. Impact/cue/visibility/arrival не доказаны этими counts.
- Unit/source graph generation-scoped; raw controller masks и удаления не превращаются в agency или смерти.
- Реальные expert labels0, validated real game verdicts0. Exact source questions и blinded forms доступны; пустые формы не считаются ответами людей.

Local `out/real-data`, `out/real-analysis`, `out/real-review`, `out/workbench` содержат runtime artifacts и исключены из переносимых архивов. Последний choice refresh обновляет соответствующий JSON/HTML section; остальные source decodings reused. Это не новая полная декодировка replay.

## Конечный остаток для игрового пилота

1. **Client source interpreter:** exact account/controller/action transaction, attempted/accepted/cast_started/committed/rejected и clock/pause/order/delivery. Программный stage bridge уже есть; нужно доказать смысл raw полей, а не создать ещё DTO.
2. **Historical one-pair registry:** authoritative build/patch/class/item/threat mapping, costs/cooldown/control/channel/target exceptions и prior cue/forecast operands. Finite solver/prefix compiler уже есть.
3. **Реальный criterion corpus:** extraction и blinded decision checks от независимых людей, sealed mixed match/player holdout и patch transfer. Release/inference/revocation code уже есть, а authentic input не добывается synthetic tests.
4. **Личная история и польза:** verified census/cases пользователя, подтверждённая цель, new disjoint periods и comprehension/actionability/behavior measurement. Generic habit/style/study/progress code уже есть.

Эти четыре задачи — конечный следующий пилот, с исходами admit / reject pair / data-blocked. [Передача Sol/Astro](../architecture/2026-10-09-handoff.md) задаёт конкретные шаги, modules и acceptance. [Data-spike](../data-spike/defensive-activation-v1.md) и [external inputs](2026-10-07-external-validation-inputs.md) уточняют forms и ограничения.

Расширения полного продукта после пилота: дополнительные TP/smoke/objective/target/control/channel/build decision classes; authenticated historical map/FoW/camera/trees builder и route safety; contextual build/ward utility rules. Они требуют кода и данных, но не подменяют ограниченный первый этап требованием реализовать всё одновременно.

## Воспроизведение и статус

Чистая машина: [INSTALL.md](../../INSTALL.md). Подготовленная папка: `python scripts/real_workbench.py`, затем `http://127.0.0.1:8765/`, выбрать account и создать отчёт. Offline: `out/real-review/index.html`. Подробные video inputs и их unverified navigation scope — в актуальном handoff/CLI help.

Source archive и wheel: `out/release-build`. Финальные tests/JUnit, Go verify/test/build, clean installation, package audit и byte matches берутся только из текущего `out/verification/release-readiness.json`. Исторические counts из stage-documents не являются текущим результатом. Внешний Windows/Linux GitHub CI не объявляется выполненным локальным прогоном.

Полная validated продуктовая приёмка остаётся false, пока не выполнены реальные gates. Архитектурная передача и available-first-stage completion — отдельные статусы; они не бесконечно открываются из-за запланированных будущих decision classes.
