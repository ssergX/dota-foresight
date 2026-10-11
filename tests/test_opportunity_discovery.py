from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from dota_coach.decisions.opportunity_discovery import discover_resource_opportunities
from dota_coach.evidence.contracts import ReplayManifest, content_hash
from dota_coach.ingest.trace import TraceResult
from dota_coach.models import ParsedReplay


def artifact():
    proofs = [{'prefix_record_index': p, 'frame_time': t, 'clock_evidence_records': [1]}
              for p, t in ((10, 1), (20, 2), (30, 3))]
    extraction = TraceResult(ParsedReplay(7, 0, {0: 'CDOTA_Unit_Hero_Axe'}, [],
        manifest=ReplayManifest('a'*64, 7, dataset_kind='synthetic')), (),
        {'trace_sha256': 'b'*64, 'replay_sha256': 'a'*64, 'timing_provenance': proofs,
         'resource_identities': {'0': {'m_iPlayerSteamID': '76561197960265739'}}}, ())
    def fact(value):
        return {'value': value, 'status': 'raw_observed' if value is not None else 'unknown',
                'source_record_index': 2, 'net_tick': 5}
    handle = 2 + (3 << 14)
    member = {'slot': 0, 'handle': str(handle), 'entity_index': 2, 'generation': 3,
        'class': 'CDOTA_Item_Black_King_Bar',
        'handle_fact': fact(handle), 'item_id': 'item_black_king_bar',
        'relation_status': 'resolved_exact_handle', 'fields': {
            'm_iManaCost': fact(50), 'm_fCooldown': fact(0),
            'm_bFrozenCooldown': fact(False), 'm_bInIndefiniteCooldown': fact(False)}}
    samples = []
    for proof in proofs:
        samples.append({'cutoff_record_index': proof['prefix_record_index'] + 1,
            'prefix_record_index': proof['prefix_record_index'], 'cutoff_policy': 'prefix_record_inclusive',
            'sampled_net_tick': 100, 'game_time': proof['frame_time'], 'feasibility': 'unknown',
            'hero': {'class': 'CDOTA_Unit_Hero_Axe', 'mapping_source_record_index': 1,
                     'fields': {'m_flMana': fact(300)}}, 'inventory': [deepcopy(member)],
            'clock': {'tick_interval': 0.1, 'paused_ticks': 0, 'paused': False,
                'pause_start_tick': 0, 'evidence_records': [1], 'semantic_validation': 'unverified'}})
    states = {'schema_version': 'foresight.action-states.v1', 'validation': 'unverified',
        'match_id': 7, 'resource_slot': 0, 'actor': 'npc_dota_hero_axe', 'account_id_verified_by_resource': 11,
        'resource_steam_id': fact('76561197960265739'), 'trace_sha256': 'b'*64, 'replay_sha256': 'a'*64,
        'source_extraction_hash': content_hash(asdict(extraction)), 'snapshots': [], 'timeline': samples}
    seal(states)
    return states, extraction


def seal(states):
    states['payload_sha256'] = content_hash({k: v for k, v in states.items() if k != 'payload_sha256'})


def discover(states, extraction):
    seal(states)
    return discover_resource_opportunities(states, extraction)


def test_unpressed_ready_item_is_discovered_without_any_logged_cast():
    states, extraction = artifact()
    assert not extraction.actions and not states['snapshots']
    result = discover(states, extraction)
    window, = result['observed_windows']
    assert window['candidate_status'] == 'unknown_requirements' and window['sample_count'] == 3
    assert window['activation_absence'] == 'not_established'
    assert window['eligibility'] == window['feasibility'] == 'unknown'
    assert result['game_opportunity_coverage'] is None and result['assessed_count'] == 0
    assert result['supplied_stream_coverage']['extraction_frame_coverage'] == 1
    assert not result['training_eligible'] and not window['training_eligible']


def test_empty_inventory_and_missing_hero_cannot_become_negative_opportunities():
    states, extraction = artifact()
    states['timeline'][1]['inventory'] = []
    states['timeline'][2].update(hero=None, inventory=[])
    result = discover(states, extraction)
    assert [s['sample_status'] for s in result['samples']] == [
        'defensive_members_observed', 'no_defensive_member_in_compact_projection', 'own_hero_unavailable']
    assert result['ineligible_count'] == 0
    assert result['observed_windows'][0]['sample_count'] == 1
    assert result['observed_windows'][0]['continuous_availability'] == 'unknown'


@pytest.mark.parametrize('value,status', [(None, 'unknown_requirements'), (-1, 'corrupt_observation'),
                                        (True, 'corrupt_observation'), ('50', 'corrupt_observation')])
def test_missing_and_corrupt_mana_cost_remain_distinct(value, status):
    states, extraction = artifact()
    states['timeline'][0]['inventory'][0]['fields']['m_iManaCost']['value'] = value
    result = discover(states, extraction)
    assert result['samples'][0]['observations'][0]['candidate_status'] == status
    assert result['samples'][0]['observations'][0]['feasibility'] == 'unknown'


def test_zero_mana_is_a_raw_negative_comparison_not_infeasibility():
    states, extraction = artifact()
    states['timeline'][0]['hero']['fields']['m_flMana']['value'] = 0
    result = discover(states, extraction)
    obs = result['samples'][0]['observations'][0]
    assert obs['checks'][1]['value'] is False
    assert obs['candidate_status'] == 'raw_check_failed' and obs['feasibility'] == 'unknown'


def test_missing_frame_breaks_window_and_exports_censoring_gap():
    states, extraction = artifact()
    del states['timeline'][1]
    result = discover(states, extraction)
    assert len(result['observed_windows']) == 2
    assert result['sampling_gaps'][0]['missing_sample_count'] == 1
    assert result['supplied_stream_coverage']['missing_extraction_sample_count'] == 1
    assert result['supplied_stream_coverage']['extraction_frame_stream_status'] == 'partial'


def test_leading_trailing_and_empty_stream_missing_coverage():
    states, extraction = artifact()
    states['timeline'] = states['timeline'][1:2]
    result = discover(states, extraction)
    assert [g['missing_sample_count'] for g in result['sampling_gaps']] == [1, 1]
    states['timeline'] = []
    result = discover(states, extraction)
    assert result['supplied_stream_coverage']['extraction_frame_coverage'] == 0
    assert result['sampling_gaps'][0]['missing_sample_count'] == 3


def test_future_state_and_full_receipt_changes_leave_earlier_ids_unchanged():
    states, extraction = artifact()
    first = discover(states, extraction)
    states['timeline'][-1]['inventory'][0]['fields']['m_iManaCost']['value'] = 999
    changed_extraction = replace(extraction, audit=extraction.audit | {'trace_sha256': 'c'*64})
    states['trace_sha256'] = 'c'*64
    states['source_extraction_hash'] = content_hash(asdict(changed_extraction))
    later = discover(states, changed_extraction)
    assert later['samples'][:2] == first['samples'][:2]
    assert later['observed_windows'][0]['window_id'] == first['observed_windows'][0]['window_id']
    assert later['samples'][-1]['input_hash'] != first['samples'][-1]['input_hash']


def test_reused_entity_index_different_complete_handle_starts_new_window():
    states, extraction = artifact()
    member = states['timeline'][-1]['inventory'][0]
    member['generation'] = 4
    member['handle'] = str(2 + (4 << 14))
    member['handle_fact']['value'] = int(member['handle'])
    result = discover(states, extraction)
    assert [w['generation'] for w in result['observed_windows']] == [3, 4]


@pytest.mark.parametrize('mutation', [
    lambda s: s.update(actor='npc_dota_hero_lina'),
    lambda s: s.update(account_id_verified_by_resource=12),
    lambda s: s.update(resource_slot=1),
    lambda s: s.update(source_extraction_hash='d'*64),
    lambda s: s.update(validation='validated'),
    lambda s: s['timeline'][0].update(feasibility='feasible'),
    lambda s: s['timeline'][0]['hero']['fields']['m_flMana'].update(source_record_index=11),
    lambda s: s['timeline'][0].update(game_time=9),
    lambda s: s['timeline'][0]['hero'].update(mapping_source_record_index=11),
    lambda s: s['timeline'][0]['clock'].update(evidence_records=[11]),
    lambda s: s['timeline'][0]['inventory'][0].update(item_id='item_ghost'),
    lambda s: s['resource_steam_id'].update(status='unknown'),
])
def test_foreign_self_promoted_or_future_bound_inputs_fail_closed(mutation):
    states, extraction = artifact()
    mutation(states)
    with pytest.raises(ValueError):
        discover(states, extraction)


def test_tampered_payload_receipt_rejected():
    states, extraction = artifact()
    states['timeline'][0]['hero']['fields']['m_flMana']['value'] = 10
    with pytest.raises(ValueError, match='hash mismatch'):
        discover_resource_opportunities(states, extraction)


def test_clock_missing_and_frozen_do_not_infer_cooldown_ready():
    states, extraction = artifact()
    states['timeline'][0]['clock']['paused_ticks'] = None
    states['timeline'][1]['inventory'][0]['fields']['m_bFrozenCooldown']['value'] = True
    result = discover(states, extraction)
    assert all(s['observations'][0]['checks'][2]['value'] is None for s in result['samples'][:2])


def test_world_fields_and_duplicate_inventory_members_rejected():
    states, extraction = artifact()
    states['timeline'][0]['enemy_positions'] = [{'x': 1}]
    with pytest.raises(ValueError, match='world payload'):
        discover(states, extraction)
    states, extraction = artifact()
    states['timeline'][0]['inventory'] *= 2
    with pytest.raises(ValueError, match='duplicate'):
        discover(states, extraction)


def test_decreasing_raw_cooldown_does_not_select_remaining_or_absolute_semantics():
    states, extraction = artifact()
    for sample, value in zip(states['timeline'], (95, 94, 93)):
        sample['sampled_net_tick'] = 30000
        sample['inventory'][0]['fields']['m_fCooldown']['value'] = value
        sample['inventory'][0]['checks'] = [{'code': 'raw_cooldown_end_not_after_clock',
            'value': True, 'status': 'unverified_candidate', 'evidence_record_indices': [2]}]
    result = discover(states, extraction)
    for sample in result['samples']:
        check = sample['observations'][0]['checks'][2]
        assert check['value'] is None and check['status'] == 'unknown'
        assert [h['arithmetic_comparison_value'] for h in check['interpretations']] == [False, True]
        assert check['chosen_interpretation'] is None
        assert sample['observations'][0]['candidate_status'] == 'unknown_requirements'
    assert result['assessed_count'] == 0


def test_zero_cooldown_hypotheses_agreement_still_cannot_grant_ready():
    states, extraction = artifact()
    result = discover(states, extraction)
    check = result['samples'][0]['observations'][0]['checks'][2]
    assert [h['arithmetic_comparison_value'] for h in check['interpretations']] == [True, True]
    assert all(h['status'] == 'unverified_hypothesis' for h in check['interpretations'])
    assert check['value'] is None and check['feasibility'] == 'unknown'
