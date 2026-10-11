# Независимое ревью mana-reserve и resource-prefix

Это фиксация обнаруженных дефектов **до исправления родительским исполнителем**. Проанализированы `decisions/mana_reserve.py`, `decisions/resource_review.py`, `reserve-review` CLI, Annotation/TimeRef admission semantics и текущие tests. Этот reviewer не менял проверяемые runtime modules.

**Обновление после исправлений:** все шесть пунктов ниже закрыты в коде родительским исполнителем. Добавлены nonlegacy clock/goal/availability gates, action-scoped predicates, extraction и отдельный decision-blinded admission, строгая provenance/allowlist ресурсов, finite derived arithmetic. Regression tests находятся в `tests/test_mana_reserve.py` и `tests/test_resource_review.py`. Это программные исправления; повторное независимое игровое review и реальные human labels всё ещё отсутствуют. Исходные findings сохранены как история проверки.

## Подтверждённые наблюдения

1. `evaluate_mana_reserve` допускает anchor с `clock_mapping_version='legacy/unverified'`, если поля order/tick/sequence/uncertainty помечены verified/exact. Одинаковая legacy mapping у fact/goal проходит `definitely_available_before`. Repro заменяет только mapping у synthetic fixture и получает `probable_error`. Нужен explicit nonlegacy/nonunknown clock gate и аттестация temporal scope, а не один status string.
2. `self.selected_mana_cost` не имеет структурной связи с `action.action_id`; `self.reserve_mana_cost` не связан с `goal.reserve_action`. Repro меняет только выбранный action ID на unrelated-action; verdict остаётся `probable_error`. Два extraction reviewer могут подтвердить, что число стоимости существует и доступно, без проверки стоимости **именно выбранного/зарезервированного действия**. Нужны action-scoped cost facts/identities и checks соответствия.
3. `resolve_reviewed_facts` допускает исследовательскую оценку по двум correct/available votes только для scalar facts. Наличие двух extraction declarations с exact input hash не проверяет resolved boundary evidence, identity/stage выбранного action, coverage complete noactivation, историческую доступность user goal. Эти объекты влияют на verdict, поэтому нужна отдельная review evidence/admission для них. Identity/independence экспертов остаётся внешним gate даже после добавления ссылок.
4. `review_resource_prefix` выкидывает missing/bool/non-int `source_record_index` из refs, но продолжает вычислять известную raw value. Repro удаляет source record у own mana; результат всё ещё arithmetic636. Каждый известный operand должен иметь допустимый nonnegative record strictly before cutoff; отсутствие provenance даёт unknown/abstention, а не вычисление по неразрешённому значению.
5. Resource projection хеширует целые входные fact/check dicts. Repro добавляет `future_hp:0` внутри mana fact: значение/арифметика не меняются, но input hash меняется. Это канал произвольного future/hidden metadata. Нужна allowlist projected fields/check scalar contracts; input hash инвариантен к всем отсутствующим в разрешённой схеме данным.
6. Все scalar operands проходят finite check, но `reserve_cost * repetitions + margin` может overflow до infinity. Repro finite1e308 reserve ×2 даёт `required_mana=inf`. `reserve-review` записывает с allow_nan=False и не сможет сериализовать такой результат. Проверять finite derived quantities; overflow — явный отказ/invalid-input reason.

## Семантическая граница

Immediate mana balance как отдельный conditional criterion полезнее caller-supplied utility bounds: он вычисляет величины и не притворяется прогнозом исхода драки. Однако label good/probable_error ограничен заявленным reserve-policy constraint и не устанавливает стратегическую разумность самой цели, защиты или ожидания. Эта граница уже описана в explanation/strategic_quality/training_eligible и должна сохраниться в любом UI. Пока historical costs/resources/action/timing/goal не допущены, выход только insufficient_evidence. Даже admitted research result не production/release validation.

## Отдельная интеграционная проверка training CLI

`tests/test_training_cli.py`: **10 passed**; вместе с `test_training.py` — **31 passed**. Проверены:

* подтверждённая цель без журнала не создаёт history/progress/validated diagnosis;
* unconfirmed goal не получает упражнение;
* known False и unknown null остаются разными, eligible/observed/unknown знаменатели сохраняются;
* empty followup не resolved;
* comparable journals помечаются self-report, delta не causal;
* foreign assignment/scope запрещают импорт периода;
* followup требует baseline;
* inputs с именами `index.html`/`training.json` защищены от output overwrite;
* partial study arguments и source account/hero/patch mismatch не создают фиктивный результат.

CLI/live_report/modules родителя не изменены этим reviewer. Подтверждённые repro были отправлены ему для исправления; этот документ не утверждает, что дефекты остаются после дальнейших правок.
