from dataclasses import asdict,replace
import json

import pytest

from dota_coach.evidence.contracts import EntityRef,SourceRef,TimeRef,content_hash
from dota_coach.decisions.defensive_impact import ImpactGoal,load_defensive_impact_input,evaluate_defensive_impact
from dota_coach.ingest.impact_prefix import (
    PHYSICAL_ASSUMPTIONS,REQUIRED_PASSES,ImpactPrefixQuery,PrefixReplayManifest,
    PrefixOwnState,PrefixScreenCue,CommittedProjectile,HistoricalProjectileRule,
    PrefixRuleAdmission,ImpactPrefixRegistry,compile_impact_prefix,load_impact_prefix_input,
)


def context():
    at=TimeRef(1000,10,5,0,'fixture.clock','verified');prior=TimeRef(900,9,1,0,'fixture.clock','verified')
    source=lambda kind:SourceRef('synthetic.'+kind,content_hash(kind),'synthetic','fixture.v1',kind,'fixture.v1')
    actor,item,missile,caster=(EntityRef('match:7',index,gen) for index,gen in ((42,3),(44,7),(66,9),(77,4)))
    query=ImpactPrefixQuery(7,'a'*64,'fixture.patch','fixture.build','account:11','account:11',actor,
        'fixture.item',item,'fixture.projectile',at,40,'fixture.shared_prefix',dataset_kind='synthetic')
    manifest=PrefixReplayManifest(7,query.replay_sha256,query.patch,query.game_build,query.dataset_kind,(source('manifest'),),prior)
    common=dict(subject_ref=query.subject_ref,observer_ref=query.observer_ref,source_record_domain=query.source_record_domain,
        valid_at=prior,available_at=prior,perspective='team')
    own=PrefixOwnState(**common,event_id='own',actor_entity=actor,item_entity=item,source_record_index=30,
        hp_min=500,hp_max=500,mana_min=150,mana_max=150,mana_cost_min=50,mana_cost_max=50,
        baseline_multiplier_min=1,baseline_multiplier_max=1,activation_feasible=True,hold_feasible=True,
        single_impact_complete=True,window_stable=True,source_refs=(source('own'),))
    cue=PrefixScreenCue(**{**common,'perspective':'screen'},event_id='cue',projectile_entity=missile,
        threat_id=query.threat_id,source_record_index=31,exposed=True,source_refs=(source('cue'),))
    projectile=CommittedProjectile(**common,event_id='projectile',projectile_entity=missile,caster_entity=caster,
        target_entity=actor,threat_id=query.threat_id,damage_tag='fixture.tag',source_record_index=32,
        launch_at=TimeRef(800,8,1,0,'fixture.clock','verified'),committed=True,in_flight=True,
        launch_to_fixed_target_distance_min=300,launch_to_fixed_target_distance_max=300,
        speed_units_per_second_min=1000,speed_units_per_second_max=1000,cast_level=2,
        damage_parameter_min=400,damage_parameter_max=420,source_refs=(source('projectile'),))
    rule=HistoricalProjectileRule('fixture.rule',query.patch,query.game_build,query.item_id,query.threat_id,'fixture.rule.v1','fixture.tag',
        ((100,120),(200,220)),1,1,10,10,200,200,.25,.25,(),PHYSICAL_ASSUMPTIONS,prior,(source('rule'),))
    goal=ImpactGoal(100,50,(source('goal'),),prior)
    return dict(query=query,manifest=manifest,own_state=own,cue=cue,projectile=projectile,rules=(rule,),goal=goal)


def registry_for(args):
    rule=args['rules'][0]
    review=SourceRef('synthetic.review','b'*64,'synthetic','fixture.v1','review','fixture.v1')
    admission=PrefixRuleAdmission(content_hash(args['query']),content_hash(args['manifest']),content_hash(rule),
        content_hash(args['own_state']),content_hash(args['cue']),content_hash(args['projectile']),content_hash(args['goal']),
        REQUIRED_PASSES,(review,))
    sources=tuple(s for obj in (args['manifest'],args['own_state'],args['cue'],args['projectile'],rule,args['goal']) for s in obj.source_refs)+(review,)
    return ImpactPrefixRegistry((admission,),frozenset(content_hash(s) for s in sources),'testing')


def portable():
    args=context()
    return json.loads(json.dumps({'schema_version':'foresight.impact-prefix-input.v1',
        **{key:[asdict(r) for r in value] if key=='rules' else asdict(value) for key,value in args.items()}}))


def test_compiles_available_committed_launch_into_forecast_and_impact_proposal():
    args=context();result=compile_impact_prefix(**args,registry=registry_for(args))
    assert result['status']=='reviewed_conditional_prefix_proposal'
    assert result['forecast']=={'arrival_time_min_ms':1100,'arrival_time_max_ms':1100,
        'damage_before_resistance_min':600,'damage_before_resistance_max':640,
        'travel_duration_min_ms':300,'travel_duration_max_ms':300}
    impact=evaluate_defensive_impact(**load_defensive_impact_input(result['candidate_defensive_impact_input']))
    activate=impact['candidate_arithmetic']['alternatives']['activate']
    assert activate['hp_after_impact']=={'minimum':340,'maximum':350}
    assert activate['mana_after_action']=={'minimum':100,'maximum':100}
    assert impact['verdict']=='unknown' and not impact['training_eligible']
    assert result['noticed']=='not_established' and result['downstream_case_and_criterion_admission_required']


def test_unreviewed_json_never_creates_forecast_or_historical_rule_admission():
    result=compile_impact_prefix(**load_impact_prefix_input(portable()))
    assert result['candidate_defensive_impact_input'] is result['forecast'] is None
    assert result['raw_own_operand_candidates']['hp_min']==500
    assert result['training_eligible'] is False


def test_empty_actual_historical_rulebook_remains_unavailable():
    args=context();args['rules']=()
    result=compile_impact_prefix(**args)
    assert 'historical_rule_missing_or_ambiguous' in result['missing_reasons']
    assert result['selected_rule_hash'] is result['forecast'] is None


@pytest.mark.parametrize('part',['manifest','own_state','cue','projectile','rule','goal','review'])
def test_current_dependency_allowlist_revokes_each_distinct_receipt(part):
    args=context();registry=registry_for(args)
    obj=args['rules'][0] if part=='rule' else registry.admissions[0] if part=='review' else args[part]
    source=obj.review_sources[0] if part=='review' else obj.source_refs[0]
    revoked=replace(registry,allowed_source_receipt_hashes=registry.allowed_source_receipt_hashes-{content_hash(source)})
    result=compile_impact_prefix(**args,registry=revoked)
    assert result['forecast'] is result['candidate_defensive_impact_input'] is None


@pytest.mark.parametrize('part',['manifest','own_state','cue','projectile','rule','goal'])
def test_source_content_mutations_cannot_reuse_previous_review(part):
    args=context();registry=registry_for(args)
    obj=args['rules'][0] if part=='rule' else args[part]
    changed=replace(obj,source_refs=(replace(obj.source_refs[0],content_hash='c'*64),))
    if part=='rule':args['rules']=(changed,)
    else:args[part]=changed
    assert compile_impact_prefix(**args,registry=registry)['forecast'] is None


@pytest.mark.parametrize('part',['own_state','cue','projectile'])
def test_future_callback_or_future_availability_never_enters_forecast(part):
    args=context();event=args[part]
    for changed in (replace(event,source_record_index=40),replace(event,available_at=replace(args['query'].at,game_time_ms=1200,replay_tick=12)),
            replace(event,valid_at=replace(args['query'].at,game_time_ms=1200,replay_tick=12))):
        proposed={**args,part:changed}
        assert compile_impact_prefix(**proposed,registry=registry_for(proposed))['forecast'] is None


@pytest.mark.parametrize('part',['own_state','cue','projectile'])
def test_hidden_world_foreign_observer_and_record_domain_rejected(part):
    args=context()
    for field,value in (('perspective','world'),('observer_ref','opponent:99'),('source_record_domain','foreign')):
        changed={**args,part:replace(args[part],**{field:value})}
        with pytest.raises(ValueError):compile_impact_prefix(**changed,registry=registry_for(changed))


@pytest.mark.parametrize('perspective',['team','public'])
def test_team_visibility_is_not_own_screen_exposure(perspective):
    args=context();args['cue']=replace(args['cue'],perspective=perspective)
    with pytest.raises(ValueError,match='screen'):compile_impact_prefix(**args,registry=registry_for(args))


def test_selected_subject_must_own_the_screen_cue():
    args=context();args['query']=replace(args['query'],observer_ref='observer:99')
    for key in ('own_state','cue','projectile'):args[key]=replace(args[key],observer_ref='observer:99')
    with pytest.raises(ValueError,match='screen'):compile_impact_prefix(**args,registry=registry_for(args))


@pytest.mark.parametrize('part,field',[
    ('own_state','actor_entity'),('own_state','item_entity'),('cue','projectile_entity'),('projectile','target_entity'),
])
def test_exact_entity_generations_not_reused(part,field):
    args=context();entity=getattr(args[part],field);args[part]=replace(args[part],**{field:replace(entity,generation=entity.generation+1)})
    result=compile_impact_prefix(**args,registry=registry_for(args));assert result['forecast'] is None


@pytest.mark.parametrize('field,value',[('patch','other.patch'),('game_build','other.build'),('replay_sha256','c'*64),('match_id',8)])
def test_manifest_binding_precedes_historical_rule_lookup(field,value):
    args=context();args['manifest']=replace(args['manifest'],**{field:value})
    result=compile_impact_prefix(**args,registry=registry_for(args));assert result['selected_rule_hash'] is None
    assert 'manifest_match_replay_patch_build_dataset_mismatch' in result['missing_reasons']


def test_unknown_patch_or_build_cannot_select_unknown_rule():
    args=context()
    args['query']=replace(args['query'],patch='unknown');args['manifest']=replace(args['manifest'],patch='unknown')
    args['rules']=(replace(args['rules'][0],patch='unknown'),)
    result=compile_impact_prefix(**args,registry=registry_for(args));assert result['forecast'] is None and result['selected_rule_hash'] is None


def test_distance_speed_intervals_and_launch_uncertainty_are_conservative():
    args=context();p=args['projectile']
    args['projectile']=replace(p,launch_to_fixed_target_distance_min=600,launch_to_fixed_target_distance_max=800,
        speed_units_per_second_min=1000,speed_units_per_second_max=2000,launch_at=replace(p.launch_at,uncertainty_ms=10))
    result=compile_impact_prefix(**args,registry=registry_for(args))
    assert result['forecast']['arrival_time_min_ms']==1090
    assert result['forecast']['arrival_time_max_ms']==1610


def test_in_flight_age_is_interpolated_from_launch_not_restarted_at_choice():
    args=context();result=compile_impact_prefix(**args,registry=registry_for(args))
    assert result['forecast']['arrival_time_min_ms']==1100
    assert result['forecast']['arrival_time_min_ms']!=args['query'].at.game_time_ms+300


def test_already_elapsed_or_partial_past_arrival_abstains():
    args=context();args['projectile']=replace(args['projectile'],launch_to_fixed_target_distance_min=100,launch_to_fixed_target_distance_max=500)
    result=compile_impact_prefix(**args,registry=registry_for(args));assert result['forecast'] is None
    assert 'forecast_not_wholly_after_choice' in result['missing_reasons']


def test_arrival_equal_to_choice_has_no_known_impact_vs_choice_order():
    args=context()
    args['projectile']=replace(args['projectile'],launch_to_fixed_target_distance_min=200,launch_to_fixed_target_distance_max=200)
    args['rules']=(replace(args['rules'][0],activation_latency_min_ms=0,activation_latency_max_ms=0),)
    result=compile_impact_prefix(**args,registry=registry_for(args))
    assert result['candidate_defensive_impact_input'] is result['forecast'] is None
    assert 'forecast_not_wholly_after_choice' in result['missing_reasons']


@pytest.mark.parametrize('field,value',[('committed',None),('committed',False),('in_flight',False)])
def test_cast_or_effect_is_not_invented_as_committed_projectile(field,value):
    args=context();args['projectile']=replace(args['projectile'],**{field:value})
    assert compile_impact_prefix(**args,registry=registry_for(args))['forecast'] is None


def test_late_unknown_or_foreign_clock_launch_and_stale_event_abstain():
    args=context();p=args['projectile']
    for modified in (replace(p,launch_at=replace(p.launch_at,game_time_ms=950,replay_tick=9,sequence_in_tick=2)),
            replace(p,launch_at=replace(p.launch_at,clock_mapping_version='foreign')),
            replace(p,launch_at=replace(p.launch_at,order_status='unknown')),
            replace(p,valid_at=replace(p.valid_at,game_time_ms=-500))):
        changed={**args,'projectile':modified};assert compile_impact_prefix(**changed,registry=registry_for(changed))['forecast'] is None


def test_overflow_and_unavailable_cast_level_abstain():
    args=context();args['projectile']=replace(args['projectile'],cast_level=3)
    assert compile_impact_prefix(**args,registry=registry_for(args))['forecast'] is None
    args=context();args['projectile']=replace(args['projectile'],launch_to_fixed_target_distance_min=1e308,launch_to_fixed_target_distance_max=1e308,
        speed_units_per_second_min=1e-308,speed_units_per_second_max=1e-308)
    result=compile_impact_prefix(**args,registry=registry_for(args));assert result['forecast'] is None and 'physical_forecast_overflow' in result['missing_reasons']


def test_all_exclusions_explicit_and_damage_exemption_tag_carried_without_guessing():
    args=context()
    with pytest.raises(ValueError):replace(args['rules'][0],assumptions=PHYSICAL_ASSUMPTIONS[:-1])
    args['rules']=(replace(args['rules'][0],exempt_tags=('fixture.tag',)),)
    result=compile_impact_prefix(**args,registry=registry_for(args))
    impact=evaluate_defensive_impact(**load_defensive_impact_input(result['candidate_defensive_impact_input']))
    assert impact['candidate_arithmetic']['timing_coverage']=='exempt'


@pytest.mark.parametrize('extra',['registry','admission','noticed','outcome','future_damage_loss','utility_bounds','validated'])
def test_portable_future_outcomes_or_grants_forbidden(extra):
    data=portable();data[extra]=True
    with pytest.raises(ValueError):load_impact_prefix_input(data)


def test_portable_unknown_clocks_and_zero_real_rules_default_closed():
    data=portable();data['rules']=[];data['query']['dataset_kind']=data['manifest']['dataset_kind']='replay'
    result=compile_impact_prefix(**load_impact_prefix_input(data));assert result['forecast'] is None
    data=portable();data['query']['at']['clock_mapping_version']='unknown'
    assert compile_impact_prefix(**load_impact_prefix_input(data))['forecast'] is None


def test_mutable_admissions_and_duplicate_rulebook_rejected():
    args=context()
    with pytest.raises(TypeError):compile_impact_prefix(**args,registry=asdict(registry_for(args)))
    args['rules']=args['rules']+args['rules']
    with pytest.raises(ValueError):compile_impact_prefix(**args)


def test_immutable_equal_copies_preserve_review_but_changed_copy_revokes_it():
    args=context();registry=registry_for(args)
    copied={key:tuple(replace(r) for r in value) if key=='rules' else replace(value) for key,value in args.items()}
    assert compile_impact_prefix(**copied,registry=registry)==compile_impact_prefix(**args,registry=registry)
    copied['projectile']=replace(copied['projectile'],damage_parameter_min=401)
    assert compile_impact_prefix(**copied,registry=registry)['forecast'] is None


@pytest.mark.parametrize('missing_pass',sorted(REQUIRED_PASSES))
def test_each_independent_review_pass_is_required(missing_pass):
    args=context();registry=registry_for(args)
    registry=replace(registry,admissions=(replace(registry.admissions[0],authenticated_passes=REQUIRED_PASSES-{missing_pass}),))
    assert compile_impact_prefix(**args,registry=registry)['candidate_defensive_impact_input'] is None


def test_whole_source_mutation_rebinds_receipts_without_changing_prefix_arithmetic():
    args=context();before=compile_impact_prefix(**args,registry=registry_for(args))
    changed={key:tuple(replace(r,source_refs=(replace(r.source_refs[0],content_hash='c'*64),)) for r in value)
        if key=='rules' else replace(value,source_refs=(replace(value.source_refs[0],content_hash='c'*64),))
        if hasattr(value,'source_refs') else value for key,value in args.items()}
    after=compile_impact_prefix(**changed,registry=registry_for(changed))
    assert before['forecast']==after['forecast']
    old=evaluate_defensive_impact(**load_defensive_impact_input(before['candidate_defensive_impact_input']))
    new=evaluate_defensive_impact(**load_defensive_impact_input(after['candidate_defensive_impact_input']))
    assert old['input_hash']==new['input_hash'] and old['candidate_arithmetic']==new['candidate_arithmetic']
    assert compile_impact_prefix(**changed,registry=registry_for(args))['forecast'] is None


def test_derived_source_inventory_is_bounded_without_silently_dropping_dependencies():
    args=context()
    source=lambda n:SourceRef('synthetic.'+str(n),content_hash(n),'synthetic','fixture.v1',str(n),'fixture.v1')
    args['projectile']=replace(args['projectile'],source_refs=tuple(source(n) for n in range(32)))
    args['rules']=(replace(args['rules'][0],source_refs=(source(32),)),)
    result=compile_impact_prefix(**args,registry=registry_for(args))
    assert result['candidate_defensive_impact_input'] is None
    assert 'derived_forecast_source_receipt_bound_exceeded' in result['missing_reasons']


@pytest.mark.parametrize('dependency',['manifest','rule'])
def test_derived_availability_and_receipts_include_later_causal_dependency(dependency):
    args=context();later=TimeRef(950,9,2,0,'fixture.clock','verified')
    if dependency=='rule':args['rules']=(replace(args['rules'][0],available_at=later),)
    else:args['manifest']=replace(args['manifest'],available_at=later)
    result=compile_impact_prefix(**args,registry=registry_for(args))
    proposal=load_defensive_impact_input(result['candidate_defensive_impact_input'])
    damage=next(f.fact for f in proposal['facts'] if f.fact.predicate=='threat.damage_before_resistance_min')
    assert damage.available_at==later and damage.valid_at.game_time_ms==900
    assert args['manifest'].source_refs[0] in damage.source_refs
    assert args['rules'][0].source_refs[0] in damage.source_refs
    assert args['manifest'].source_refs[0] in proposal['model'].source_refs
    assert proposal['model'].available_at==later
    early=replace(proposal['scope'],at=TimeRef(925,9,3,0,'fixture.clock','verified'))
    assessment=evaluate_defensive_impact(**{**proposal,'scope':early})
    assert assessment['candidate_arithmetic'] is None


@pytest.mark.parametrize('clock',[' unknown ',' ','legacy','UNAVAILABLE'])
def test_reserved_or_whitespace_clock_cannot_claim_verified_mapping(clock):
    data=portable()
    for key in ('query','manifest','own_state','cue','projectile','goal'):
        for field in ('at','valid_at','available_at','launch_at'):
            if isinstance(data[key].get(field),dict):data[key][field]['clock_mapping_version']=clock
    data['rules'][0]['available_at']['clock_mapping_version']=clock
    args=load_impact_prefix_input(data)
    assert compile_impact_prefix(**args,registry=registry_for(args))['forecast'] is None
