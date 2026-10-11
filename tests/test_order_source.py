import copy
import json
from types import SimpleNamespace

import pytest

from dota_coach.ingest.order_source import CALLBACKS, load_order_source


def fixture(tmp_path):
    meta = {'t': 'meta', 'schema_version': 'replay-orders.v1', 'replay_sha256': 'a'*64,
            'replay_bytes': 12, 'source_callbacks': list(CALLBACKS), 'extractor_name': 'manta',
            'extractor_version': 'foresight-replay/3.1', 'manta_version': 'v1.5.0',
            'completeness': 'registered_source_callback_census_only',
            'sequence_semantics': 'callback_stream_order_not_verified_simulation_order',
            'validation': 'unverified_source_observation'}
    message = {'t': 'order_message', 'protobuf_type': CALLBACKS[0],
               'data': {'entindex': 14, 'ability_id': 44, 'last_order_latency': 4294966296},
               'protobuf_unknown_fields_hex': 'a00101', 'actor_identity': None,
               'command_stage': None, 'validation': 'unverified_source_observation'}
    footer = {k: meta[k] for k in ('schema_version', 'replay_sha256', 'replay_bytes', 'extractor_name', 'extractor_version', 'manta_version')}
    footer.update(t='orders_end', parser_completed=True,
                  validation='unverified_source_observation',
                  counts={k: int(i == 0) for i, k in enumerate(CALLBACKS)}, message_count=1)
    rows = [meta, message, footer]
    for i, row in enumerate(rows):
        row.update(record_index=i+1, demo_tick=10, net_tick=20,
                   sequence_in_tick=i+1, game_time=None)
    path = tmp_path/'orders.jsonl'
    extraction = SimpleNamespace(audit={'replay_sha256': 'a'*64}, replay=SimpleNamespace(match_id=7,
        manifest=SimpleNamespace(match_id=7,replay_hash='a'*64)))
    return path, extraction, rows


def write(path, rows):
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')


def test_raw_orders_do_not_grant_attempt_stage_or_join_catalog(tmp_path):
    path, extraction, rows = fixture(tmp_path)
    write(path, rows)
    result = load_order_source(path, extraction=extraction)
    assert result['callback_counts'][CALLBACKS[0]] == 1
    assert result['selected_player_message_count'] is None
    assert result['attempt_count'] is None and result['attempt_coverage'] is None
    assert result['accepted_count'] is None and result['committed_count'] is None
    assert result['training_eligible'] is False
    example = result['examples'][CALLBACKS[0]][0]
    assert example['data']['last_order_latency'] == 4294966296
    assert example['data']['ability_id'] == 44
    assert example['protobuf_unknown_fields_hex'] == 'a00101'


@pytest.mark.parametrize('mutate', [
    lambda r: r.pop(),
    lambda r: r.append(copy.deepcopy(r[-1])),
    lambda r: r[0].update(replay_sha256='b'*64),
    lambda r: r[-1].update(replay_bytes=13),
    lambda r: r[-1].update(message_count=True),
    lambda r: r[-1]['counts'].update({CALLBACKS[0]: 0}),
    lambda r: r[1].update(command_stage='accepted'),
    lambda r: r[1].update(actor_identity='account:11'),
    lambda r: r[1].update(game_time=0),
    lambda r: r[1].update(record_index=4),
    lambda r: r[1].update(net_tick=True),
    lambda r: r[1].update(sequence_in_tick=1),
    lambda r: r[1].update(protobuf_type='dota.CDOTAClientMsg_ExecuteOrders'),
    lambda r: r[1].update(protobuf_unknown_fields_hex='zz'),
    lambda r: r[0].update(attempt_coverage='complete'),
    lambda r: r[-1].update(validation='verified',training_eligible=True),
    lambda r: r[1].update(net_tick=2**80),
    lambda r: r[1]['data'].update(ability_id=True),
    lambda r: r[1]['data'].update(units=['fake_entity']),
    lambda r: r[1]['data'].update(order_type='not_int32'),
    lambda r: r[0].pop('extractor_version'),
    lambda r: r[1]['data'].update(position={'x':10**1000}),
])
def test_unsealed_mismatched_or_promoted_orders_rejected(tmp_path, mutate):
    path, extraction, rows = fixture(tmp_path)
    mutate(rows)
    write(path, rows)
    with pytest.raises(ValueError):
        load_order_source(path, extraction=extraction)


def test_no_observed_orders_does_not_establish_no_attempts(tmp_path):
    path, extraction, rows = fixture(tmp_path)
    rows.pop(1)
    rows[-1].update(record_index=2, sequence_in_tick=2, message_count=0,
                    counts={k: 0 for k in CALLBACKS})
    write(path, rows)
    result = load_order_source(path, extraction=extraction)
    assert not any(result['callback_counts'].values())
    assert result['attempt_count'] is None


def test_source_indices_remain_separate_and_examples_bounded(tmp_path):
    path, extraction, rows = fixture(tmp_path)
    write(path, rows)
    result = load_order_source(path, extraction=extraction, examples_per_type=0)
    assert result['source_record_domain'] == 'orders'
    assert not result['examples'][CALLBACKS[0]]


def test_manifest_conflict_and_oversized_record_rejected(tmp_path):
    path, extraction, rows = fixture(tmp_path)
    write(path, rows)
    extraction.replay.manifest.replay_hash='b'*64
    with pytest.raises(ValueError,match='manifest'):
        load_order_source(path,extraction=extraction)
    extraction.replay.manifest.replay_hash='a'*64
    path.write_bytes(b' '*((1<<20)+1))
    with pytest.raises(ValueError,match='byte limit'):
        load_order_source(path,extraction=extraction)


def test_cli_source_export_does_not_overwrite_raw_input(tmp_path):
    from dota_coach.cli import main
    path,_,rows=fixture(tmp_path);write(path,rows)
    before=path.read_bytes()
    assert main(['orders-source','--source-jsonl',str(path),'--extraction-json',str(tmp_path/'missing.json'),
                 '--out',str(path)])==1
    assert path.read_bytes()==before
