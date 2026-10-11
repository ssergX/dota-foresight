"""Inventory-stream discovery without equating availability with a decision.

Compact action-state timelines omit unresolved and non-defensive inventory
members. Their empty lists cannot prove absence. Every supplied frame is audited;
neither frame completeness nor an apparent ready item grants game opportunity
coverage, command absence, historical feasibility, or a coaching diagnosis.
"""
from __future__ import annotations

from collections import Counter
import math

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.action_state import (
    DEFENSIVE_ITEMS, ITEM_ALIASES, INDEX_MASK, STEAM_ACCOUNT_BASE, unverified_cooldown_check,
    validate_action_states,
)
from dota_coach.ingest.trace import TraceResult, _integer


def _numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _fact(raw, cutoff, *, boolean=False):
    if not isinstance(raw, dict) or raw.get('value') is None:
        return {'value': None, 'status': 'unknown', 'source_record_index': raw.get('source_record_index') if isinstance(raw, dict) else None,
                'net_tick': raw.get('net_tick') if isinstance(raw, dict) else None}
    value, rid, tick = raw.get('value'), raw.get('source_record_index'), raw.get('net_tick')
    valid = (raw.get('status') == 'raw_observed' and type(rid) is int and 0 <= rid < cutoff
             and type(tick) is int and tick >= 0)
    valid = valid and (type(value) is bool if boolean else _numeric(value) is not None)
    return {'value': value if valid else None, 'status': 'raw_observed' if valid else 'corrupt',
            'source_record_index': rid, 'net_tick': tick}


def _condition(code, facts, value):
    states = {f['status'] for f in facts}
    status = 'corrupt' if 'corrupt' in states else ('unverified_candidate' if value is not None else 'unknown')
    return {'code': code, 'value': value if status == 'unverified_candidate' else None,
            'status': status, 'evidence_record_indices': sorted({f['source_record_index'] for f in facts
                if type(f['source_record_index']) is int})}


def _inventory_observation(sample, item):
    cutoff = sample['cutoff_record_index']
    fields = item.get('fields', {})
    hero = sample.get('hero') or {}
    mana = _fact(hero.get('fields', {}).get('m_flMana'), cutoff)
    cost = _fact(fields.get('m_iManaCost'), cutoff)
    cooldown = _fact(fields.get('m_fCooldown'), cutoff)
    frozen = _fact(fields.get('m_bFrozenCooldown'), cutoff, boolean=True)
    indefinite = _fact(fields.get('m_bInIndefiniteCooldown'), cutoff, boolean=True)
    handle_fact = _fact(item.get('handle_fact'), cutoff)
    handle = _integer(item.get('handle'))
    exact = (item.get('relation_status') == 'resolved_exact_handle' and handle is not None and handle >= 0
             and (handle & INDEX_MASK, handle >> 14) == (item.get('entity_index'), item.get('generation'))
             and _integer(handle_fact['value']) == handle)
    availability = _condition('exact_inventory_handle_resolves', [handle_fact], True if exact else None)
    if item.get('relation_status') == 'resolved_exact_handle' and not exact:
        availability.update(value=None, status='corrupt')
    mana_check = _condition('raw_mana_at_least_reported_cost', [mana, cost],
                            mana['value'] >= cost['value'] if mana['value'] is not None and cost['value'] is not None else None)
    clock = sample.get('clock', {})
    interval, paused_ticks = _numeric(clock.get('tick_interval')), clock.get('paused_ticks')
    tick = clock.get('pause_start_tick') if clock.get('paused') is True else sample.get('sampled_net_tick')
    refs = clock.get('evidence_records', [])
    clock_valid = (interval is not None and interval > 0 and type(paused_ticks) is int and paused_ticks >= 0
                   and type(tick) is int and tick >= paused_ticks and type(clock.get('paused')) is bool
                   and clock.get('semantic_validation') == 'unverified' and isinstance(refs, list) and bool(refs)
                   and all(type(r) is int and 0 <= r < cutoff for r in refs))
    # Recompute instead of trusting legacy stored candidate-ready flags.
    cooldown_check = unverified_cooldown_check(fields, clock, sample.get('sampled_net_tick'), cutoff)
    if any(f['status'] == 'corrupt' for f in (cooldown, frozen, indefinite)):
        cooldown_check['status'] = 'corrupt'
    cooldown_check['clock_status'] = 'unverified_candidate' if clock_valid else 'unknown'
    if clock_valid:
        cooldown_check['evidence_record_indices'] = sorted(set(cooldown_check['evidence_record_indices'] + refs))
    checks = [availability, mana_check, cooldown_check]
    raw = {'handle': item.get('handle'), 'entity_index': item.get('entity_index'),
           'generation': item.get('generation'), 'slot': item.get('slot'), 'item_id': item.get('item_id'),
           'mana': mana, 'cost': cost, 'cooldown': cooldown, 'frozen': frozen, 'indefinite': indefinite,
           'handle_fact': handle_fact, 'checks': checks,
           'clock_operand': {'tick_interval': interval, 'paused_ticks': paused_ticks,
               'sampled_or_pause_start_tick': tick, 'paused': clock.get('paused'),
               'evidence_records': refs, 'status': 'unverified_candidate' if clock_valid else 'unknown'}}
    # Even agreement of raw arithmetic hypotheses never emits a ready status.
    raw.update(candidate_status='corrupt_observation' if any(c['status'] == 'corrupt' for c in checks) else (
        'raw_check_failed' if any(c['value'] is False for c in checks) else 'unknown_requirements'),
        feasibility='unknown', eligibility='unknown', verdict='insufficient_evidence', training_eligible=False)
    return raw


def discover_resource_opportunities(action_states: dict, extraction: TraceResult) -> dict:
    """Process every supplied own sample; emit candidate windows, never verdicts.

    Window IDs depend on their first observation, not their future end or whole
    trace receipts. Input hashes for individual observations use only their own
    prefix. A changed future receipt still requires a correctly rebound artifact.
    """
    validate_action_states(action_states, extraction)
    slot, actor = action_states.get('resource_slot'), action_states.get('actor')
    if type(slot) is not int or not 0 <= slot <= 9 or not isinstance(actor, str) or not actor.startswith('npc_dota_hero_'):
        raise ValueError('explicit own actor and resource slot required')
    hero_class = extraction.replay.heroes.get(slot)
    if not isinstance(hero_class, str) or hero_class.removeprefix('CDOTA_Unit_Hero_').replace('_', '').lower() != actor.removeprefix('npc_dota_hero_').replace('_', '').lower():
        raise ValueError('actor/resource hero binding mismatch')
    steam_fact = action_states.get('resource_steam_id') or {}
    steam = _integer(steam_fact.get('value'))
    identity = extraction.audit.get('resource_identities', {}).get(str(slot), {})
    source_steam = _integer(identity.get('m_iPlayerSteamID'))
    account = action_states.get('account_id_verified_by_resource')
    if (steam_fact.get('status') != 'raw_observed' or type(steam_fact.get('source_record_index')) is not int
            or steam_fact['source_record_index'] < 0 or type(steam_fact.get('net_tick')) is not int
            or steam_fact['net_tick'] < 0 or steam is None or steam != source_steam or type(account) is not int or not 0 < account <= 0xffffffff
            or steam - STEAM_ACCOUNT_BASE != account):
        raise ValueError('account/resource steam binding mismatch')
    binding = {'match_id': extraction.replay.match_id, 'actor': actor, 'resource_slot': slot,
               'account_id': account, 'dataset_kind': extraction.replay.manifest.dataset_kind}
    timeline = action_states.get('timeline')
    if not isinstance(timeline, list):
        raise ValueError('own inventory timeline must be a supplied list')
    proofs = extraction.audit.get('timing_provenance', [])
    expected = {p['prefix_record_index']: p for p in proofs}
    if len(expected) != len(proofs):
        raise ValueError('extraction timing prefixes must be distinct')
    ordinals = {p['prefix_record_index']: i for i, p in enumerate(proofs)}
    samples, windows, active, gaps = [], [], {}, []
    previous_prefix = None
    previous_time = None
    previous_ordinal = None
    counts = Counter()

    def close(key, reason):
        window = active.pop(key)
        window['right_censoring'] = reason
        windows.append(window)

    for ordinal, sample in enumerate(timeline):
        prefix = sample.get('prefix_record_index')
        proof = expected.get(prefix)
        if (type(prefix) is not int or proof is None or sample.get('cutoff_record_index') != prefix + 1
                or sample.get('cutoff_policy') != 'prefix_record_inclusive'
                or sample.get('game_time') != proof.get('frame_time')
                or (previous_prefix is not None and prefix <= previous_prefix)):
            raise ValueError('timeline sample must match ordered extraction timing prefix')
        game_time = sample.get('game_time')
        if game_time is not None and (type(game_time) not in (int, float) or not math.isfinite(game_time)):
            raise ValueError('invalid sample game time')
        hero = sample.get('hero')
        if hero is not None and hero.get('class') != hero_class:
            raise ValueError('sample own hero class binding mismatch')
        if hero is not None and (type(hero.get('mapping_source_record_index')) is not int
                or not 0 <= hero['mapping_source_record_index'] < prefix + 1):
            raise ValueError('own hero mapping must precede sample cutoff')
        if hero is None and sample.get('inventory'):
            raise ValueError('inventory cannot establish own membership without own hero')
        clock_refs = sample.get('clock', {}).get('evidence_records', [])
        if (not isinstance(clock_refs, list) or any(type(r) is not int or not 0 <= r < prefix + 1 for r in clock_refs)):
            raise ValueError('clock evidence must precede sample cutoff')
        current_ordinal = ordinals[prefix]
        if ordinal == 0 and current_ordinal:
            gaps.append({'kind': 'missing_leading_extraction_frame_samples',
                         'before_prefix_record_index': prefix, 'missing_sample_count': current_ordinal,
                         'availability_during_gap': 'unknown'})
        discontinuity = previous_ordinal is not None and current_ordinal != previous_ordinal + 1
        if discontinuity:
            gaps.append({'kind': 'missing_extraction_frame_samples', 'after_prefix_record_index': previous_prefix,
                         'before_prefix_record_index': prefix, 'missing_sample_count': current_ordinal - previous_ordinal - 1,
                         'availability_during_gap': 'unknown'})
            for key in tuple(active):
                close(key, 'missing_frame_sample_gap')
        interval = game_time - previous_time if game_time is not None and previous_time is not None else None
        if interval is not None and interval < 0:
            raise ValueError('timeline game clock regressed')
        observations = [_inventory_observation(sample, item) for item in sample.get('inventory', [])]
        if any(i['item_id'] not in DEFENSIVE_ITEMS for i in observations):
            raise ValueError('timeline contains unsupported defensive item alias')
        if any(ITEM_ALIASES.get(item.get('class')) != item.get('item_id')
               for item in sample.get('inventory', []) if item.get('relation_status') == 'resolved_exact_handle'):
            raise ValueError('defensive item class/alias binding mismatch')
        identities = [(i['handle'], i['generation']) for i in observations]
        if len(identities) != len(set(identities)):
            raise ValueError('duplicate exact inventory member in sample')
        sample_projection = binding | {'prefix_record_index': prefix, 'game_time': game_time,
            'cutoff_policy': sample['cutoff_policy'], 'observations': observations,
            'own_hero_identity_status': 'raw_observed' if hero else 'unknown'}
        sample_id = 'resource-sample:' + content_hash(sample_projection)
        state = 'own_hero_unavailable' if hero is None else ('defensive_members_observed' if observations else 'no_defensive_member_in_compact_projection')
        counts[state] += 1
        samples.append({'sample_id': sample_id, 'input_hash': content_hash(sample_projection),
            'ordinal': ordinal, 'prefix_record_index': prefix, 'cutoff_record_index': prefix + 1,
            'game_time': game_time, 'time_status': 'extraction_clock_unverified' if game_time is not None else 'unknown',
            'sample_status': state, 'interval_from_previous_sample_seconds': interval,
            'continuous_availability_between_samples': 'unknown', 'observations': observations})
        present = set()
        for observation in observations:
            signature = tuple((c['code'], c['status'], c['value']) for c in observation['checks'])
            key = (observation['handle'], observation['generation'], observation['item_id'], observation['slot'], signature)
            present.add(key)
            if key not in active:
                window_id = 'resource-window:' + content_hash({'binding': binding, 'start_sample_id': sample_id,
                    'handle': observation['handle'], 'generation': observation['generation'], 'item_id': observation['item_id'],
                    'slot': observation['slot'], 'check_signature': signature})
                active[key] = {'opportunity_id': window_id, 'window_id': window_id,
                    'decision_class': 'defensive_item_activation', 'item_id': observation['item_id'],
                    'handle': observation['handle'], 'generation': observation['generation'], 'slot': observation['slot'],
                    'start_sample_id': sample_id, 'start_prefix_record_index': prefix, 'start_game_time': game_time,
                    'sample_count': 0, 'candidate_status': observation['candidate_status'], 'checks': observation['checks'],
                    'eligibility': 'unknown', 'feasibility': 'unknown', 'boundary_status': 'unresolved',
                    'verdict': 'insufficient_evidence', 'training_eligible': False,
                    'activation_absence': 'not_established', 'continuous_availability': 'unknown',
                    'left_censoring': 'sampling_gap' if discontinuity else 'first_sample_of_observed_state',
                    'reason_codes': ['control_and_command_constraints_unverified', 'decision_boundary_and_goal_unresolved',
                                     'compact_projection_not_full_inventory', 'sampling_does_not_resolve_nonactivation']}
            active[key].update(end_sample_id=sample_id, end_prefix_record_index=prefix, end_game_time=game_time,
                               sample_count=active[key]['sample_count'] + 1)
        for key in tuple(active):
            if key not in present:
                close(key, 'next_sample_has_different_state_or_member_unobserved')
        previous_prefix, previous_time, previous_ordinal = prefix, game_time, current_ordinal
    for key in tuple(active):
        close(key, 'end_of_supplied_stream')
    trailing = len(proofs) - (previous_ordinal + 1 if previous_ordinal is not None else 0)
    if trailing:
        gaps.append({'kind': 'missing_trailing_extraction_frame_samples',
                     'after_prefix_record_index': previous_prefix, 'missing_sample_count': trailing,
                     'availability_during_gap': 'unknown'})
    windows.sort(key=lambda w: (w['start_prefix_record_index'], w['window_id']))
    missing = len(expected) - len(timeline)
    complete = missing == 0
    result = {'schema_version': 'foresight.resource-opportunity-discovery.v1', 'source_binding': binding,
        'source_receipts': {k: action_states[k] for k in ('payload_sha256', 'trace_sha256', 'replay_sha256', 'source_extraction_hash')},
        'account_link_validation': 'arithmetic_resource_link_not_client_validated',
        'selection': 'every_supplied_own_inventory_frame_not_logged_cast_selection',
        'samples': samples, 'observed_windows': windows, 'sampling_gaps': gaps, 'sample_status_counts': dict(counts),
        'supplied_stream_coverage': {'status': 'all_supplied_samples_processed', 'supplied_sample_count': len(timeline),
            'processed_sample_count': len(samples), 'expected_extraction_frame_count': len(expected),
            'missing_extraction_sample_count': missing, 'extraction_frame_coverage': len(timeline) / len(expected) if expected else None,
            'extraction_frame_stream_status': 'complete' if complete else 'partial'},
        'game_opportunity_coverage': None, 'scope_status': 'sampled_raw_candidates_not_full_game_opportunity_census',
        'assessed_count': 0, 'eligible_count': 0, 'ineligible_count': 0, 'unknown_window_count': len(windows),
        'strategic_quality': 'not_established', 'training_eligible': False,
        'limitations': ['all_item_fields_and_absolute_cooldown_clock_interpretation_unverified',
            'player_visible_threat_attention_and_intent_unavailable', 'command_attempt_log_completeness_unknown',
            'absence_from_compact_inventory_does_not_prove_absence_or_infeasibility',
            'no_interpolation_between_observed_frames', 'zero_assessed_windows_is_not_zero_game_opportunities']}
    result['payload_sha256'] = content_hash(result)
    return result
