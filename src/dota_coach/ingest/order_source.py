"""Validate replay callback receipts without interpreting command stages.

The record counter belongs to the orders sidecar, never the entity trace.
Spectator messages are not evidence of attempted/accepted/committed inputs.
"""
from collections import Counter
import hashlib
import base64
import math
from pathlib import Path

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash

SCHEMA = 'replay-orders.v1'
CALLBACKS = (
    'dota.CDOTAUserMsg_SpectatorPlayerUnitOrders',
    'dota.CDOTAUserMsg_QueuedOrderRemoved',
    'dota.CDOTAUserMsg_SpectatorPlayerClick',
    'dota.CDOTAUserMsg_HudError',
    'dota.CDemoUserCmd',
)
MAX_RECORD_BYTES = 1 << 20


def _wire_data(kind, data):
    """Manta v1.5.0 proto2 fields, including only explicitly present values."""
    int32 = (-2**31, 2**31-1)
    uint32 = (0, 2**32-1)
    def integer(value, bounds):
        return type(value) is int and bounds[0] <= value <= bounds[1]
    def floating(value):
        if isinstance(value,str):
            return value in ('NaN','Infinity','-Infinity')
        if type(value) not in (int,float):
            return False
        try:
            return math.isfinite(value) and abs(value) <= 3.4028235e38
        except OverflowError:
            return False
    fields = {
        CALLBACKS[0]: {'entindex': int32, 'order_type': int32, 'units': [int32],
            'target_index': int32, 'ability_id': int32, 'position': 'vector', 'queue': 'bool',
            'sequence_number': int32, 'flags': uint32, 'last_order_latency': uint32, 'ping': uint32},
        CALLBACKS[1]: {'unit_order_sequence': [uint32]},
        CALLBACKS[2]: {'entindex': int32, 'order_type': int32, 'target_index': int32},
        CALLBACKS[3]: {'order_id': int32, 'sequence_number': int32},
        CALLBACKS[4]: {'cmd_number': int32, 'data': 'bytes'},
    }[kind]
    if set(data)-set(fields):
        raise ValueError('unknown raw protobuf JSON field')
    for key, value in data.items():
        rule = fields[key]
        if isinstance(rule, tuple):
            valid = integer(value, rule)
        elif isinstance(rule, list):
            valid = isinstance(value, list) and all(integer(v, rule[0]) for v in value)
        elif rule == 'bool':
            valid = type(value) is bool
        elif rule == 'bytes':
            valid = isinstance(value, str)
            if valid:
                try:
                    base64.b64decode(value, validate=True)
                except ValueError:
                    valid = False
        else:
            valid = isinstance(value, dict) and not set(value)-{'x','y','z','w'}
            if valid:
                valid = all(floating(v) for v in value.values())
        if not valid:
            raise ValueError('raw protobuf JSON value/type outside wire schema')


def load_order_source(path, *, extraction, examples_per_type=3):
    return _load_order_source(path, extraction=extraction, examples_per_type=examples_per_type)


def _load_order_source(path, *, extraction, examples_per_type=3, schema=SCHEMA, observation_callback=None):
    """Verify a sealed full callback census bound to an extraction's replay SHA."""
    if type(examples_per_type) is not int or not 0 <= examples_per_type <= 20:
        raise ValueError('bounded example count required')
    expected = extraction.audit['replay_sha256']
    if (extraction.replay.manifest is None or extraction.replay.manifest.replay_hash != expected
            or extraction.replay.manifest.match_id != extraction.replay.match_id):
        raise ValueError('extraction manifest and audit replay binding disagree')
    digest, counts, examples = hashlib.sha256(), Counter(), {k: [] for k in CALLBACKS}
    meta = footer = None
    previous_demo = previous_sequence = None
    records = 0
    with Path(path).open('rb') as stream:
        while True:
            raw = stream.readline(MAX_RECORD_BYTES+1)
            if not raw:
                break
            if len(raw)>MAX_RECORD_BYTES:
                raise ValueError('orders record exceeds byte limit')
            digest.update(raw)
            if not raw.strip():
                raise ValueError('blank records in orders source')
            row = strict_json(raw.decode('utf-8-sig'))
            if not isinstance(row, dict) or footer is not None:
                raise ValueError('orders source has invalid or trailing records')
            records += 1
            if type(row.get('record_index')) is not int or row['record_index'] != records:
                raise ValueError('orders callback record indices must be contiguous')
            for key in ('demo_tick', 'net_tick', 'sequence_in_tick'):
                if (type(row.get(key)) is not int or row[key] < (1 if key == 'sequence_in_tick' else 0)
                        or row[key] > (2**64-1 if key == 'sequence_in_tick' else 2**32-1)):
                    raise ValueError('raw orders clock/counter required')
            sequence = previous_sequence + 1 if previous_demo == row['demo_tick'] else 1
            if row['sequence_in_tick'] != sequence or row.get('game_time', 'missing') is not None:
                raise ValueError('orders sequence or unverified game time altered')
            previous_demo, previous_sequence = row['demo_tick'], row['sequence_in_tick']
            if records == 1:
                if row.get('t') != 'meta' or row.get('schema_version') != schema:
                    raise ValueError('orders metadata required first')
                if row.get('replay_sha256') != expected or row.get('source_callbacks') != list(CALLBACKS):
                    raise ValueError('orders source replay/callback binding mismatch')
                if (row.get('completeness') != 'registered_source_callback_census_only'
                        or row.get('sequence_semantics') != 'callback_stream_order_not_verified_simulation_order'
                        or row.get('validation') != 'unverified_source_observation'):
                    raise ValueError('orders metadata promotes unverified observations')
                if type(row.get('replay_bytes')) is not int or row['replay_bytes'] <= 0:
                    raise ValueError('replay byte receipt required')
                if (row.get('extractor_name') != 'manta' or row.get('extractor_version') != 'foresight-replay/3.1'
                        or row.get('manta_version') != 'v1.5.0'):
                    raise ValueError('versioned orders extractor receipt required')
                meta = row
            elif row.get('t') == 'order_message':
                kind = row.get('protobuf_type')
                if kind not in CALLBACKS or not isinstance(row.get('data'), dict):
                    raise ValueError('unregistered orders message')
                _wire_data(kind,row['data'])
                if (row.get('actor_identity', 'missing') is not None
                        or row.get('command_stage', 'missing') is not None
                        or row.get('validation') != 'unverified_source_observation'):
                    raise ValueError('raw order identity/stage must remain unknown')
                wire = row.get('protobuf_unknown_fields_hex')
                if not isinstance(wire, str) or len(wire) % 2:
                    raise ValueError('unknown protobuf wire bytes required')
                try:
                    bytes.fromhex(wire)
                except ValueError as exc:
                    raise ValueError('invalid unknown protobuf wire bytes') from exc
                counts[kind] += 1
                if observation_callback is not None:
                    observation_callback(row)
                if len(examples[kind]) < examples_per_type:
                    examples[kind].append(row)
            elif row.get('t') == 'orders_end':
                footer = row
            else:
                raise ValueError('unexpected orders record kind')
            for key in ('attempt_coverage', 'accepted_commands', 'committed_commands'):
                if key in row and row[key] is not None:
                    raise ValueError('raw source cannot certify command stages')
            if row.get('validation') != 'unverified_source_observation' or row.get('training_eligible',False) is not False:
                raise ValueError('raw source cannot promote validation or training')
    if meta is None or footer is None or footer.get('parser_completed') is not True:
        raise ValueError('complete orders footer required')
    for key in ('schema_version', 'replay_sha256', 'replay_bytes', 'extractor_name', 'extractor_version', 'manta_version'):
        if footer.get(key) != meta.get(key):
            raise ValueError('orders metadata/footer mismatch')
    claimed = footer.get('counts')
    if (not isinstance(claimed, dict) or set(claimed) != set(CALLBACKS)
            or any(type(v) is not int or v < 0 or v != counts[k] for k, v in claimed.items())
            or type(footer.get('message_count')) is not int or footer['message_count'] != sum(counts.values())):
        raise ValueError('orders footer census mismatch')
    result = {
        'schema_version': 'foresight.order-source-summary.v1',
        'match_id': extraction.replay.match_id, 'replay_sha256': expected,
        'source_sha256': digest.hexdigest(), 'source_record_domain': 'orders',
        'match_binding': 'supplied_extraction_replay_sha256',
        'metadata': meta, 'footer': footer, 'callback_counts': dict(claimed), 'examples': examples,
        'selected_player_message_count': None, 'attempt_count': None,
        'accepted_count': None, 'committed_count': None, 'attempt_coverage': None,
        'validation': 'unverified_source_observation', 'training_eligible': False,
        'limitations': [
            'raw_entindex_and_ability_id_have_no_generation_or_player_join',
            'spectator_message_stage_does_not_establish_client_attempt',
            'callback_census_is_not_attempt_channel_coverage',
            'raw_ticks_are_not_validated_game_or_screen_time',
            'record_indices_are_local_to_orders_sidecar',
        ],
    }
    result['payload_sha256'] = content_hash(result)
    return result
