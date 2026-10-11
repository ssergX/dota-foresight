"""Generation-scoped source graph for selected hero and raw unit associations.

Resource slots are not player IDs. Ownership, a control-mask bit and hero class
are distinct observations; none establishes current player agency or visibility.
Only callbacks strictly before each boundary enter that graph.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult, _sha

SCHEMA = 'foresight.unit-control-source.v1'
DOMAIN = 'replay-trace.v3.record_index'
STEAM_BASE = 76561197960265728
FIELDS = ('m_iPlayerID', 'm_nPlayerOwnerID', 'm_iIsControllableByPlayer64',
          'm_hOwnerEntity', 'm_hOwnerNPC', 'm_bIsIllusion', 'm_hReplicatingOtherHero')
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOTS = 128
LIMITATIONS = ('raw_ownership_not_current_control_or_agency',
    'control_mask_interpretation_not_client_validated',
    'resource_slot_not_assumed_player_id', 'entity_presence_not_visibility',
    'callback_order_not_simulation_order', 'no_command_or_gameplay_verdict',
    'hero_class_not_proof_of_primary_hero_or_clone_kind')


def _uint(value, maximum):
    # Accept only the Go decoder's exact uint64 decimal spelling or an integer.
    if isinstance(value, str):
        if not value or len(value) > 20: return None
        try: n = int(value)
        except ValueError: return None
        if str(n) != value: return None
    elif type(value) is int: n = value
    else: return None
    return n if 0 <= n <= maximum else None


def _operand(value, wire_type, key):
    if not isinstance(wire_type, str) or not 1 <= len(wire_type) <= 128:
        raise ValueError('raw operand wire type required')
    if value is None: return  # Go records nonfinite projections as null.
    if key == 'm_bIsIllusion':
        valid = wire_type == 'bool' and type(value) is bool
    elif wire_type in ('uint32', 'int32'):
        lower, upper = (0, 2**32-1) if wire_type == 'uint32' else (-2**31, 2**31-1)
        valid = type(value) is int and lower <= value <= upper
    elif wire_type in ('uint64', 'int64'):
        valid = False
        if isinstance(value, str) and 1 <= len(value) <= 20:
            try:
                n = int(value)
                lower, upper = (0, 2**64-1) if wire_type == 'uint64' else (-2**63, 2**63-1)
                valid = str(n) == value and lower <= n <= upper
            except ValueError: pass
    else: valid = False
    if not valid: raise ValueError('raw ID/handle/mask/illusion wire value mismatch')


def _unit(cn):
    return cn.startswith(('CDOTA_Unit_', 'CDOTA_BaseNPC', 'CDOTA_NPC_'))


def _ref(entity):
    return {k: entity[k] for k in ('entity_index', 'generation', 'class_name')}


def _fact(entity, key):
    return deepcopy(entity['fields'].get(key))


def _value(entity, key):
    fact = entity['fields'].get(key)
    return fact['value'] if fact else None


def _resolve(handle, entities):
    number = _uint(handle, 2**32 - 1)
    if number is None or number == 16777215: return None
    entity = entities.get(number & 16383)
    return entity if entity and entity['generation'] == number >> 14 and entity['active'] else None


def _owner_path(entity, primary, entities):
    """Search both raw handle fields, without treating ownership as control."""
    if primary is None: return {'status': 'primary_unresolved', 'path': []}
    todo = [(entity, [], frozenset())]
    unresolved = cycle = False
    visits = 0
    while todo:
        current, path, seen = todo.pop()
        identity = (current['entity_index'], current['generation'])
        if identity in seen:
            cycle = True; continue
        if identity == (primary['entity_index'], primary['generation']):
            return {'status': 'raw_handle_path_to_selected_hero', 'path': path}
        if len(path) >= 64 or visits >= 1024:
            return {'status': 'bounded_search_incomplete', 'path': []}
        visits += 1
        present = False
        for key in ('m_hOwnerEntity', 'm_hOwnerNPC'):
            fact = _fact(current, key)
            if fact is None:
                unresolved = True; continue
            present = True
            target = _resolve(fact['value'], entities)
            if target is None:
                unresolved = True; continue
            edge = {'from': _ref(current), 'field': key, 'fact': fact, 'to': _ref(target)}
            todo.append((target, path + [edge], seen | {identity}))
        if not present: unresolved = True
    return {'status': 'cycle_or_unresolved' if cycle else 'unresolved' if unresolved else 'no_path_in_observed_graph', 'path': []}


def _graph(entities, *, match_id, replay_sha256, account_id, cutoff, dataset_kind):
    resources = []
    for entity in entities.values():
        if not entity['active'] or entity['class_name'] != 'CDOTA_PlayerResource': continue
        for slot in range(64):
            steam_key = f'm_vecPlayerData.{slot:04d}.m_iPlayerSteamID'
            if _uint(_value(entity, steam_key), 2**64-1) == STEAM_BASE + account_id:
                resources.append((entity, slot, steam_key))
    binding = None
    primary = None
    if len(resources) == 1:
        resource, slot, steam_key = resources[0]
        selected_key = f'm_vecPlayerTeamData.{slot:04d}.m_hSelectedHero'
        primary = _resolve(_value(resource, selected_key), entities)
        if primary is not None and not primary['class_name'].startswith('CDOTA_Unit_Hero_'): primary = None
        binding = {'resource': _ref(resource), 'resource_slot': slot,
            'steam_fact': _fact(resource, steam_key), 'selected_handle_fact': _fact(resource, selected_key),
            'selected_hero': _ref(primary) if primary else None,
            'player_id_fact': _fact(primary, 'm_iPlayerID') if primary else None}
    player_id = _uint(_value(primary, 'm_iPlayerID'), 63) if primary else None
    nodes = []
    for index in sorted(entities):
        entity = entities[index]
        if not entity['active'] or not _unit(entity['class_name']): continue
        mask = _uint(_value(entity, 'm_iIsControllableByPlayer64'), 2**64-1)
        direct_pid = _uint(_value(entity, 'm_iPlayerID'), 63)
        owner_pid = _uint(_value(entity, 'm_nPlayerOwnerID'), 63)
        path = _owner_path(entity, primary, entities)
        is_primary = primary is not None and _ref(entity) == _ref(primary)
        associations = {'selected_hero': is_primary,
            'raw_player_id_equal': direct_pid == player_id if direct_pid is not None and player_id is not None else None,
            'raw_owner_player_id_equal': owner_pid == player_id if owner_pid is not None and player_id is not None else None,
            'raw_control_bit_set': bool(mask & (1 << player_id)) if mask is not None and player_id is not None else None,
            'raw_owner_path': path}
        if not (is_primary or any(associations[k] is True for k in ('raw_player_id_equal', 'raw_owner_player_id_equal', 'raw_control_bit_set'))
                or path['status'] == 'raw_handle_path_to_selected_hero'): continue
        nodes.append({**_ref(entity), 'fields': deepcopy(entity['fields']),
            'associations': associations, 'illusion_raw': _fact(entity, 'm_bIsIllusion'),
            'classification': 'selected_primary_source_handle' if is_primary else 'raw_associated_unit_kind_unverified',
            'control_available': None, 'player_visibility': None, 'training_eligible': False})
    graph = {'match_id': match_id, 'replay_sha256': replay_sha256, 'account_id': account_id,
        'dataset_kind': dataset_kind, 'source_domain': DOMAIN, 'cutoff_record_index': cutoff,
        'boundary': 'strictly_before_source_callback_record', 'binding': binding,
        'binding_status': 'unique_current_resource' if len(resources) == 1 else 'ambiguous_resources' if resources else 'resource_unresolved',
        'raw_player_id': player_id, 'nodes': nodes, 'active_observed_unit_count': sum(e['active'] and _unit(e['class_name']) for e in entities.values()),
        'associated_unit_count': len(nodes), 'perspective': 'retrospective_world_observation',
        'validation': 'unverified', 'training_eligible': False, 'limitations': list(LIMITATIONS)}
    graph['prefix_sha256'] = content_hash(graph)
    return graph


def build_unit_control_source(path: str | Path, *, extraction: TraceResult, account_id: int,
                              cutoff_record_indices: tuple[int, ...] | None = None) -> dict:
    """Validate the full trace; project immutable, strictly prior unit graphs.

    Explicit boundaries can point to observed item/ability records, which are
    not authenticated decisions. Always include an end-of-file
    observation, separate from earlier graphs and their prefix hashes.
    """
    if type(account_id) is not int or not 0 < account_id <= 0xffffffff: raise ValueError('exact positive account ID required')
    if not isinstance(extraction, TraceResult): raise TypeError('typed bound trace extraction required')
    audit, manifest = extraction.audit, extraction.replay.manifest
    if (audit.get('match_id') != extraction.replay.match_id or manifest.match_id != extraction.replay.match_id
            or manifest.replay_hash != audit.get('replay_sha256')): raise ValueError('extraction replay binding mismatch')
    for key in ('trace_sha256', 'replay_sha256'): _sha(audit.get(key), key)
    if cutoff_record_indices is None:
        # Caller omission requests end-of-file only; never infer actor by name.
        cutoffs = ()
    else:
        if (not isinstance(cutoff_record_indices, tuple) or len(cutoff_record_indices) > MAX_SNAPSHOTS
                or any(type(c) is not int or c <= 0 for c in cutoff_record_indices)
                or tuple(sorted(set(cutoff_record_indices))) != cutoff_record_indices):
            raise ValueError('sorted distinct positive bounded cutoff indices required')
        cutoffs = cutoff_record_indices
    entities, retired, snapshots = {}, set(), []
    counters, operations = Counter(), Counter()
    digest = hashlib.sha256()
    metadata = footer = None
    last = 0
    wanted = iter(cutoffs)
    next_cutoff = next(wanted, None)
    def capture(cutoff):
        return _graph(entities, match_id=extraction.replay.match_id, replay_sha256=audit['replay_sha256'],
            account_id=account_id, cutoff=cutoff, dataset_kind=manifest.dataset_kind)
    with Path(path).open('rb') as stream:
        while raw := stream.readline(MAX_RECORD_BYTES + 1):
            if len(raw) > MAX_RECORD_BYTES: raise ValueError('unit source record exceeds bound')
            digest.update(raw)
            if not raw.strip(): continue
            row = strict_json(raw.decode('utf-8-sig'))
            if not isinstance(row, dict): raise ValueError('trace record object required')
            rid, kind = row.get('record_index'), row.get('t')
            if type(rid) is not int or rid != last+1 or not isinstance(kind, str) or footer is not None: raise ValueError('consecutive complete trace required')
            if next_cutoff == rid:
                snapshots.append(capture(rid)); next_cutoff = next(wanted, None)
            last = rid; counters[kind] += 1
            if metadata is None:
                if kind != 'meta' or row.get('schema_version') != 'replay-trace.v3' or row.get('replay_sha256') != audit['replay_sha256']: raise ValueError('initial bound v3 metadata required')
                metadata = row; continue
            if kind == 'meta': raise ValueError('duplicate source metadata')
            if kind == 'trace_end':
                if (row.get('parser_completed') is not True or not isinstance(row.get('counts'), dict)
                        or any(type(v) is not int or v < 0 for v in row['counts'].values())
                        or row['counts'] != dict(counters)): raise ValueError('complete source footer census required')
                footer = row; continue
            if kind != 'entity': continue
            index, generation, cn = row.get('entity_index'), row.get('generation'), row.get('class')
            if (type(index) is not int or not 0 <= index < 16384 or type(generation) is not int or not 0 <= generation < 2**32
                    or not isinstance(cn, str) or not 1 <= len(cn) <= 256): raise ValueError('exact entity generation/class required')
            fields, types, removed, op = row.get('fields'), row.get('field_types'), row.get('removed_fields'), row.get('op_bits')
            if (not isinstance(fields, dict) or not isinstance(types, dict) or not isinstance(removed, list)
                    or any(not isinstance(k, str) for k in removed) or type(op) is not int or not 0 <= op <= 31
                    or type(row.get('full_snapshot')) is not bool or set(fields) != set(types)
                    or len(set(removed)) != len(removed) or set(fields).intersection(removed)):
                raise ValueError('typed disjoint entity operation and projection required')
            identity = (index, generation)
            current = entities.get(index)
            if op & 4:
                retired.add(identity)
                if current and current['generation'] == generation: entities.pop(index)
                operations['deleted'] += 1; continue
            if identity in retired:
                operations['retired_lifetime_ignored'] += 1; continue
            if current and current['generation'] != generation:
                if not row['full_snapshot']:
                    operations['stale_or_baselineless_delta_ignored'] += 1; continue
                retired.add((index, current['generation'])); current = None
            if current is None and not row['full_snapshot']:
                operations['stale_or_baselineless_delta_ignored'] += 1; continue
            if current and current['class_name'] != cn: raise ValueError('entity class changed within lifetime')
            if current is None:
                current = {'entity_index': index, 'generation': generation, 'class_name': cn, 'fields': {}, 'active': True}
                entities[index] = current
            if row['full_snapshot']: current['fields'] = {}
            if op & 16: current['active'] = False
            elif op & (1 | 8): current['active'] = True
            for key in removed: current['fields'].pop(key, None)
            for key, value in fields.items():
                if key in FIELDS or cn == 'CDOTA_PlayerResource' and key.endswith(('.m_iPlayerSteamID', '.m_hSelectedHero')):
                    _operand(value, types[key], key)
                    current['fields'][key] = {'value': deepcopy(value), 'wire_type': types.get(key), 'source_record_index': rid}
    if metadata is None or footer is None or digest.hexdigest() != audit['trace_sha256']: raise ValueError('source differs from complete bound extraction')
    source_build = str(footer['game_build']) if footer.get('game_build') is not None else None
    if counters != Counter(audit.get('record_counts', {})) or source_build != manifest.game_build: raise ValueError('source census/build differs from extraction')
    if next_cutoff == last+1:
        snapshots.append(capture(last+1)); next_cutoff = next(wanted, None)
    if next_cutoff is not None: raise ValueError('cutoff beyond complete source')
    final = capture(last+1)
    result = {'schema_version': SCHEMA, 'match_id': extraction.replay.match_id, 'account_id': account_id,
        'replay_sha256': audit['replay_sha256'], 'trace_sha256': audit['trace_sha256'],
        'dataset_kind': manifest.dataset_kind, 'game_build': manifest.game_build,
        'snapshots': snapshots, 'final_observation': final, 'source_operations': dict(operations),
        'source_census': dict(counters), 'validation': 'unverified', 'training_eligible': False,
        'limitations': list(LIMITATIONS)}
    result['payload_sha256'] = content_hash(result)
    return result
