"""Source-bound resource arithmetic over own raw action prefixes.

No ready-item flag, health fraction or successful cast implies decision quality.
Full trace hashes are retained as receipts, excluded from analytical input hashes.
"""
from __future__ import annotations

import math

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.action_state import unverified_cooldown_check


def _number(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None


def review_resource_prefix(snapshot: dict, *, item_id: str) -> dict:
    """Only the requested own inventory member and own resources enter claims."""
    hero=snapshot.get('hero') or {}
    own=hero.get('fields',{})
    candidates=[i for i in snapshot.get('inventory',[]) if i.get('item_id')==item_id and i.get('relation_status')=='resolved_exact_handle']
    item=candidates[0] if len(candidates)==1 else None
    fields=item.get('fields',{}) if item else {}
    def projected(f):
        return {k:f.get(k) for k in ('value','status','source_record_index','net_tick','wire_type')}
    mana_fact=projected(own.get('m_flMana',{}))
    cost_fact=projected(fields.get('m_iManaCost',{}))
    mana=_number(mana_fact.get('value')) if mana_fact.get('status')=='raw_observed' else None
    cost=_number(cost_fact.get('value')) if cost_fact.get('status')=='raw_observed' else None
    remainder=mana-cost if mana is not None and cost is not None else None
    refs=tuple(sorted({f['source_record_index'] for f in (mana_fact,cost_fact) if type(f.get('source_record_index')) is int}))
    checks=[dict(c) for c in snapshot.get('checks',[]) if item is not None and c.get('item_id',item_id)==item_id]
    # Snapshot builders can store per-item checks; do not infer extra mechanics.
    if item is not None and item.get('checks') is not None:
        checks=[dict(c) for c in item['checks']]
    cutoff=snapshot.get('cutoff_record_index')
    for fact,value in ((mana_fact,mana),(cost_fact,cost)):
        if value is not None and (type(fact.get('source_record_index')) is not int or fact['source_record_index']<0 or type(fact.get('net_tick')) is not int or fact['net_tick']<0):
            raise ValueError('raw numeric resource requires exact source record and tick')
    if type(cutoff) is not int or any(r>=cutoff for r in refs):
        raise ValueError('own resource evidence must precede the observation cutoff')
    codes={'exact_inventory_handle_resolves','raw_mana_at_least_reported_cost','raw_cooldown_end_not_after_clock',
        'control_allows_activation','inventory_slot_allows_activation','target_and_command_constraints_satisfied'}
    feature_checks=[]
    normalized_checks=[]
    for c in checks:
        if c.get('code') not in codes or type(c.get('value')) not in (bool,type(None)):
            raise ValueError('unsupported own activation condition')
        rs=c.get('evidence_record_indices',[])
        if not isinstance(rs,list) or any(type(r) is not int or r>=cutoff for r in rs):
            raise ValueError('condition proof must precede the cutoff')
        if c.get('code')=='raw_cooldown_end_not_after_clock':
            c=unverified_cooldown_check(fields,snapshot.get('clock',{}),snapshot.get('sampled_net_tick'),cutoff)
        normalized_checks.append(c)
        feature_checks.append({k:c.get(k) for k in ('code','value','status','evidence_record_indices',
            'raw_cooldown_fact','raw_constraint_facts','interpretations','chosen_interpretation') if k in c})
    if not any(c['code']=='raw_cooldown_end_not_after_clock' for c in normalized_checks):
        c=unverified_cooldown_check(fields,snapshot.get('clock',{}),snapshot.get('sampled_net_tick'),cutoff)
        normalized_checks.append(c)
        feature_checks.append({k:c[k] for k in ('code','value','status','evidence_record_indices',
            'raw_cooldown_fact','raw_constraint_facts','interpretations','chosen_interpretation')})
    checks=normalized_checks
    projection={'action_id':snapshot.get('action_id'),'item_id':item_id,
        'cutoff_record_index':cutoff,'cutoff_policy':snapshot.get('cutoff_policy'),
        'mana':mana_fact,'cost':cost_fact,'item_handle':item.get('handle') if item else None,
        'item_generation':item.get('generation') if item else None,'checks':feature_checks}
    return {'schema_version':'foresight.resource-prefix-review.v1','action_id':snapshot.get('action_id'),
        'input_hash':content_hash(projection),'item_id':item_id,'own_mana_raw':mana,
        'activation_mana_cost_raw':cost,'mana_after_cost_arithmetic':remainder,
        'mana_source':mana_fact,'cost_source':cost_fact,
        'resource_evidence_records':refs,'inventory_identity':'unique_exact_handle' if item else 'unknown_or_ambiguous',
        'checks':checks,'feasibility':'unknown','verdict':'insufficient_evidence',
        'calculation_status':'arithmetic_on_unverified_raw_prefix' if remainder is not None else 'insufficient_resource_fields',
        'reason_codes':('historical_field_semantics_not_client_verified','choice_and_observed_threat_not_resolved'),
        'claim':(f"В предшествующей записи собственной маны {mana:g}; поле стоимости предмета {cost:g}. "
                 f"Арифметический остаток {remainder:g}. Это расчёт по непроверенным полям, не точный баланс на момент выбора."
                 if remainder is not None else 'Собственная мана или стоимость предмета в допустимом префиксе неизвестна.'),
        'next_question':'Какое конкретное действие ты хотел сохранить доступным после активации? Сравни его стоимость с остатком; отдельно проверь замеченную угрозу и ограничения каста.',
        'strategic_quality':'not_established','training_eligible':False}
