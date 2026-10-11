from dataclasses import asdict, replace
import json
import pytest

from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.decisions.choice_window import PrefixFact
from dota_coach.decisions.movement import (
    MovementScope, RouteEdge, NavigationGraph, MovementSemantics, MovementAdmission,
    evaluate_movement, load_movement_input,
)


def context():
    at = TimeRef(1000, replay_tick=10, uncertainty_ms=0, clock_mapping_version='fixture', order_status='verified')
    prior = replace(at, game_time_ms=900, replay_tick=9)
    receipt = SourceRef('fixture', 'a'*64, 'synthetic', 'fixture.v1', 'prefix', 'fixture')
    scope = MovementScope(7, 'ally:1', 'account:1', 'fixture', at, 20, dataset_kind='synthetic')
    graph = NavigationGraph('fixture', 'fixture.graph', ('a','b','c'), (
        RouteEdge('direct','a','c',500,600), RouteEdge('ab','a','b',100,120),
        RouteEdge('bc','b','c',200,240)), (receipt,), prior)
    semantics = MovementSemantics('fixture', 'fixture.walk', 0, 4)
    values = {'movement.start_node':'a','movement.speed_min':100,'movement.speed_max':200,
              'movement.life_state':0,'movement.control_bits':0,'route.passable:direct':True,
              'route.passable:ab':True,'route.passable:bc':True}
    facts = tuple(PrefixFact(Fact(key,'ally:1',key,value,'observed',prior,prior,'team',(receipt,),
                                 observer_ref='account:1',method_version='fixture'),i+1)
                  for i,(key,value) in enumerate(values.items()))
    return scope, graph, semantics, facts, receipt


def review(scope, graph, semantics, facts, receipt):
    return MovementAdmission(scope.match_id,scope.subject_ref,scope.observer_ref,scope.patch,
        frozenset((graph.admission_hash,)),frozenset((content_hash(semantics),)),
        frozenset(f.input_hash for f in facts),(receipt,))


def run(*, change=None, reviewed=True, missing=()):
    scope,graph,semantics,facts,receipt=context()
    facts=tuple(replace(f,fact=replace(f.fact,value=change[1])) if change and f.fact.predicate==change[0] else f for f in facts)
    facts=tuple(f for f in facts if f.fact.predicate not in missing)
    admission=review(scope,graph,semantics,facts,receipt) if reviewed else None
    return evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=facts,
                             semantics=semantics,admission=admission)


def test_path_and_time_bounds_are_computed_from_route_and_speed():
    result=run()
    assert result['path_edge_ids']==['ab','bc']
    assert result['travel_duration_bounds']=={'minimum_ms':1500,'maximum_ms':3600}
    assert result['status']=='conditional_route_supported'
    assert result['safety']==result['actual_arrival']=='not_established'
    assert result['training_eligible'] is False


def test_reviewed_blocked_path_uses_longer_available_route():
    result=run(change=('route.passable:bc',False))
    assert result['path_edge_ids']==['direct']
    assert result['travel_duration_bounds']=={'minimum_ms':2500,'maximum_ms':6000}


def test_unknown_shortcut_cannot_shorten_upper_bound():
    result=run(missing=('route.passable:bc',))
    assert result['path_edge_ids']==['direct']
    assert result['travel_duration_bounds']=={'minimum_ms':1500,'maximum_ms':6000}


@pytest.mark.parametrize('change',[('movement.control_bits',4),('movement.life_state',1)])
def test_control_and_alive_are_computed_not_distance_only(change):
    result=run(change=change)
    assert result['status']=='excluded_in_reviewed_movement_model'
    assert result['travel_duration_bounds'] is None


@pytest.mark.parametrize('key',['movement.speed_min','movement.speed_max','movement.start_node','movement.control_bits'])
def test_missing_operand_retains_unknown(key):
    result=run(missing=(key,))
    assert result['status']=='unknown' and result['travel_duration_bounds'] is None


def test_unreviewed_graph_and_mechanics_do_not_grant_arrival():
    assert run(reviewed=False)['status']=='unknown'
    assert run(reviewed=False)['travel_duration_bounds'] is None


def test_future_passability_is_not_a_prefix_feature():
    scope,graph,semantics,facts,receipt=context()
    facts=tuple(f for f in facts if f.fact.predicate!='route.passable:bc')
    admission=review(scope,graph,semantics,facts,receipt)
    extra=PrefixFact(Fact('future','ally:1','route.passable:bc',True,'observed',
        replace(scope.at,game_time_ms=2000),replace(scope.at,game_time_ms=2000),'team',(receipt,),observer_ref='account:1'),30)
    def call(v):
        return evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=facts+(v,),semantics=semantics,admission=admission)
    assert call(extra)==call(replace(extra,fact=replace(extra.fact,value=False)))


@pytest.mark.parametrize('mutation',[{'perspective':'world'},{'observer_ref':'enemy'},{'subject_ref':'other'}])
def test_hidden_or_foreign_context_rejected(mutation):
    scope,graph,semantics,facts,_=context()
    with pytest.raises(ValueError,match='world/foreign'):
        evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=(replace(facts[0],fact=replace(facts[0].fact,**mutation)),),semantics=semantics)


def test_portable_proposal_cannot_include_admission_or_outcome():
    scope,graph,semantics,facts,_=context()
    payload={'schema_version':'foresight.movement-input.v1','scope':asdict(scope),'graph':asdict(graph),
             'start_node':'a','destination_node':'c','facts':[asdict(f) for f in facts],'semantics':asdict(semantics)}
    payload=json.loads(json.dumps(payload))
    assert evaluate_movement(**load_movement_input(payload))['status']=='unknown'
    for key in ('admission','radiant_win','validated','arrival_ms'):
        with pytest.raises(ValueError,match='not portable'):
            load_movement_input(payload|{key:True})


def test_cycles_and_equal_routes_do_not_break_path_reconstruction():
    scope,graph,semantics,facts,receipt=context()
    graph=replace(graph,edges=graph.edges+(RouteEdge('cycle','b','a',0,0),))
    prior=facts[0].fact.valid_at
    facts+= (PrefixFact(Fact('cycle','ally:1','route.passable:cycle',True,'observed',prior,prior,'team',(receipt,),observer_ref='account:1'),15),)
    result=evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=facts,semantics=semantics,
                             admission=review(scope,graph,semantics,facts,receipt))
    assert result['path_edge_ids']==['ab','bc']


def test_unknown_or_stale_clock_cannot_measure_arrival():
    scope,graph,semantics,facts,receipt=context()
    for changed in (replace(scope,at=replace(scope.at,order_status='unknown')),replace(scope,max_fact_age_ms=50)):
        result=evaluate_movement(changed,graph=graph,start_node='a',destination_node='c',facts=facts,semantics=semantics,
                                 admission=review(changed,graph,semantics,facts,receipt))
        assert result['travel_duration_bounds'] is None


def test_wrong_patch_and_portable_registry_rejected():
    scope,graph,semantics,facts,_=context()
    with pytest.raises(ValueError,match='foreign historical graph'):
        evaluate_movement(scope,graph=replace(graph,patch='other'),start_node='a',destination_node='c',facts=facts)
    with pytest.raises(ValueError,match='admission'):
        evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=facts,admission={'validated':True})


def test_graph_review_requires_exact_source_and_availability_receipts():
    scope,graph,semantics,facts,receipt=context()
    admission=review(scope,graph,semantics,facts,receipt)
    other=replace(graph,source_refs=(replace(receipt,artifact_id='other',content_hash='b'*64),))
    assert other.semantic_hash==graph.semantic_hash
    assert other.admission_hash!=graph.admission_hash
    result=evaluate_movement(scope,graph=other,start_node='a',destination_node='c',facts=facts,
                             semantics=semantics,admission=admission)
    assert result['status']=='unknown' and result['travel_duration_bounds'] is None


def test_overflow_cannot_become_a_false_no_route_exclusion():
    scope,graph,semantics,facts,receipt=context()
    graph=replace(graph,edges=(RouteEdge('ab','a','b',1e308,1e308),RouteEdge('bc','b','c',1e308,1e308)))
    with pytest.raises(ValueError,match='not finite'):
        evaluate_movement(scope,graph=graph,start_node='a',destination_node='c',facts=facts[:5]+facts[6:],
                          semantics=semantics,admission=review(scope,graph,semantics,facts,receipt))


def test_duration_overflow_cannot_be_displayed_as_an_arrival_bound():
    with pytest.raises(ValueError,match='duration is not finite'):
        run(change=('movement.speed_min',1e-308))
