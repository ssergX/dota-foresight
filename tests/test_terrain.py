from dataclasses import asdict, replace
import json

import pytest

from dota_coach.evidence.contracts import SourceRef, TimeRef, content_hash
from dota_coach.decisions.terrain import (Cell, KnownBlocker, TerrainAdmission, TerrainModel,
    TerrainRegistry, TerrainScope, WardQuery, _supercover, evaluate_terrain, load_terrain_input)


def fixture():
    before = TimeRef(100, 10, 1, 0, 'fixture.clock', 'verified')
    at = TimeRef(200, 20, 1, 0, 'fixture.clock', 'verified')
    source = SourceRef('fixture.map', 'a' * 64, 'synthetic', 'fixture.map.v1', 'cells', 'fixture.v1')
    model = TerrainModel('fixture.patch', 'fixture.build', 'fixture.raster.v1', 3, 3, 10,
        tuple(Cell(x, y, 0, True, False) for x in range(3) for y in range(3)), (source,), before, True, 0)
    scope = TerrainScope(7, 'account:11', 'account:11', model.patch, model.game_build, at, 20, 'synthetic')
    return scope, model, source


def run(model, scope=None, **kwargs):
    return evaluate_terrain(scope or fixture()[0], model, **kwargs)


def test_conditional_geometry_builds_cardinal_graph_and_exact_radius_without_grant():
    scope, model, _ = fixture()
    value = run(model, queries=(WardQuery('centre', 1, 1, 10, 0),))
    assert value['status'] == 'unknown' and not value['actual_game_vision_established']
    view = value['candidate_geometry']['ward_views'][0]
    assert set(view['visible_cells']) == {(1, 1), (0, 1), (2, 1), (1, 0), (1, 2)}
    graph = value['candidate_geometry']['navigation_graph']
    assert len(graph['nodes']) == 9 and len(graph['edges']) == 24
    assert all(e['distance_min'] == e['distance_max'] == 10 for e in graph['edges'])


def test_supercover_corner_includes_both_neighbours_and_is_direction_symmetric():
    assert set(_supercover((0, 0), (1, 1))) == {(0, 0), (1, 0), (0, 1), (1, 1)}
    for x in range(8):
        for y in range(8):
            assert set(_supercover((0, 0), (x, y))) == set(_supercover((x, y), (0, 0)))


@pytest.mark.parametrize('field,value,category', [('opaque', True, 'blocked_cells'), ('opaque', None, 'unknown_cells'),
    ('height', 1, 'blocked_cells'), ('height', None, 'unknown_cells')])
def test_intermediate_blocker_height_and_unknown_preserve_three_way_visibility(field, value, category):
    _, model, _ = fixture()
    model = replace(model, cells=tuple(replace(c, **{field: value}) if (c.x, c.y) == (1, 1) else c for c in model.cells))
    view = run(model, queries=(WardQuery('ray', 0, 1, 30, 0),))['candidate_geometry']['ward_views'][0]
    assert (2, 1) in view[category]


def test_endpoint_opaque_visibility_rule_explicit_and_never_walkability():
    _, model, _ = fixture()
    model = replace(model, cells=tuple(replace(c, opaque=True, walkable=False) if (c.x, c.y) == (1, 1) else c for c in model.cells))
    query = (WardQuery('ray', 0, 1, 10, 0),)
    first = run(model, queries=query)['candidate_geometry']
    assert (1, 1) in first['ward_views'][0]['visible_cells'] and '1,1' not in first['navigation_graph']['nodes']
    second = run(replace(model, blocker_cell_visible=False), queries=query)['candidate_geometry']
    assert (1, 1) in second['ward_views'][0]['blocked_cells']


def test_dynamic_uncertain_obstacle_degrades_known_cell_but_not_static_obstruction():
    scope, model, source = fixture()
    blocker = KnownBlocker('tree', 1, 1, True, True, None, scope.subject_ref, scope.observer_ref,
        'team', model.available_at, model.available_at, 10, (source,))
    geometry = run(model, blockers=(blocker,), queries=(WardQuery('ray', 0, 1, 30, 0),))['candidate_geometry']
    assert '1,1' not in geometry['navigation_graph']['nodes'] and geometry['unknown_navigation_cells'] == 1
    assert (2, 1) in geometry['ward_views'][0]['unknown_cells']
    solid = replace(model, cells=tuple(replace(c, walkable=False, opaque=True) if (c.x, c.y) == (1, 1) else c for c in model.cells))
    assert (2, 1) in run(solid, blockers=(blocker,), queries=(WardQuery('ray', 0, 1, 30, 0),))['candidate_geometry']['ward_views'][0]['blocked_cells']


def test_future_blocker_cannot_change_prefix_geometry_or_packet():
    scope, model, source = fixture()
    blocker = KnownBlocker('future', 1, 1, True, True, True, scope.subject_ref, scope.observer_ref,
        'team', replace(scope.at, game_time_ms=300, replay_tick=30), replace(scope.at, game_time_ms=300, replay_tick=30), 30, (source,))
    base = run(model)
    assert run(model, blockers=(blocker,)) == base
    assert run(model, blockers=(replace(blocker, x=2, blocks_walk=False, blocks_vision=False),)) == base


@pytest.mark.parametrize('field,value', [('perspective', 'world'), ('observer_ref', 'other'), ('subject_ref', 'other')])
def test_hidden_or_foreign_blocker_never_enters_geometry(field, value):
    scope, model, source = fixture()
    blocker = KnownBlocker('tree', 1, 1, True, True, True, scope.subject_ref, scope.observer_ref,
        'team', model.available_at, model.available_at, 10, (source,))
    with pytest.raises(ValueError, match='hidden/foreign'):
        run(model, blockers=(replace(blocker, **{field:value}),))


@pytest.mark.parametrize('field,value', [('patch', 'other'), ('game_build', 'other'), ('available_at', None)])
def test_historical_map_identity_and_availability_required(field, value):
    _, model, _ = fixture()
    assert run(replace(model, **{field: value}))['candidate_geometry'] is None


def test_empty_known_walkable_region_has_no_invented_navigation_node():
    _, model, _ = fixture()
    model = replace(model, cells=tuple(replace(c, walkable=None) for c in model.cells))
    geometry = run(model)['candidate_geometry']
    assert geometry['navigation_graph'] is None and geometry['unknown_navigation_cells'] == 9


def test_pairwise_duplicate_visibility_not_intersection_of_all_three_queries():
    _, model, _ = fixture()
    queries = (WardQuery('a', 0, 0, 10, 0), WardQuery('b', 1, 0, 0, 0), WardQuery('c', 2, 2, 0, 0))
    geometry = run(model, queries=queries)['candidate_geometry']
    assert geometry['duplicate_visible_cells'] == [(1, 0)]


def test_testing_registry_and_current_source_revocation_never_establish_game_vision():
    scope, model, source = fixture()
    proposal = run(model)
    admission = TerrainAdmission(proposal['packet_hash'], (source,))
    registry = TerrainRegistry((admission,), frozenset((content_hash(source),)), 'testing')
    assert run(model, registry=registry)['status'] == 'testing_only'
    assert run(model, registry=replace(registry, review_context='external_review'))['status'] == 'conditional_model_admitted'
    assert not run(model, registry=replace(registry, review_context='external_review'))['actual_game_vision_established']
    assert run(model, registry=replace(registry, allowed_source_receipt_hashes=frozenset()))['status'] == 'unknown'
    assert run(replace(model, source_refs=(replace(source, locator='new'),)), registry=registry)['status'] == 'unknown'


def test_derived_graph_binds_dynamic_receipt_and_cannot_be_reused_before_compilation():
    scope, model, source = fixture()
    dynamic=replace(source,artifact_id='fixture.tree',locator='tree',content_hash='b'*64)
    delivered=replace(model.available_at,game_time_ms=180,replay_tick=18)
    blocker=KnownBlocker('tree',1,1,True,True,True,scope.subject_ref,scope.observer_ref,
        'team',delivered,delivered,18,(dynamic,))
    result=run(model,blockers=(blocker,))
    graph=result['candidate_geometry']['navigation_graph']
    assert graph['available_at']==asdict(scope.at)
    assert asdict(dynamic) in graph['source_refs'] and asdict(source) in graph['source_refs']
    assert any(s['content_hash']==result['packet_hash'] for s in graph['source_refs'])
    assert graph['available_at']['game_time_ms']>delivered.game_time_ms


def test_navigation_never_drops_lineage_to_fit_receipt_limit():
    scope, model, source = fixture()
    sources=tuple(replace(source,artifact_id=f'fixture.map:{i}',locator=f'cell:{i}') for i in range(32))
    result=run(replace(model,source_refs=sources))
    assert result['candidate_geometry']['navigation_graph'] is None
    assert len(result['dependency_receipts'])==32
    assert result['candidate_geometry']['navigation_status']=='provenance_limit'


def test_strict_portable_loader_roundtrip_and_rejects_admission(tmp_path):
    scope, model, _ = fixture()
    proposal = json.loads(json.dumps({'schema_version':'foresight.terrain-input.v1', 'scope':asdict(scope),
        'model':asdict(model), 'blockers':[], 'queries':[asdict(WardQuery('a', 0, 0, 10, 0))]}))
    path = tmp_path/'input.json'; path.write_text(json.dumps(proposal), encoding='utf-8')
    assert evaluate_terrain(**load_terrain_input(path))['status'] == 'unknown'
    proposal['admission'] = True
    with pytest.raises(ValueError, match='exact terrain'):
        load_terrain_input(proposal)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'nan', 'negative-radius', 'outside'])
def test_invalid_geometry_rejected(mutation):
    scope, model, _ = fixture()
    with pytest.raises(ValueError):
        if mutation == 'missing': replace(model, cells=model.cells[:-1])
        elif mutation == 'duplicate': replace(model, cells=model.cells[:-1]+(model.cells[0],))
        elif mutation == 'nan': replace(model, cell_size=float('nan'))
        elif mutation == 'negative-radius': WardQuery('a', 0, 0, -1, 0)
        else: run(model, queries=(WardQuery('a', 3, 0, 1, 0),))
