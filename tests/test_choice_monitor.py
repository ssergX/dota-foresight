"""Synthetic transition evidence; never labels for an actual game."""
from dataclasses import replace

import pytest

from dota_coach.decisions.choice_monitor import ContinuityCoverage,ContinuityAdmission,monitor_choice_stream
from dota_coach.evidence.contracts import content_hash
from tests.test_choice_window import inputs,admission,clock,operand


def stream():
    scope,semantics,first,cue=inputs()
    second=replace(first,sample_id='s2',prefix_record_index=150,at=clock(1400),
        facts=tuple(operand('self.control_bits',4,available=1300,record=140) if f.fact.predicate=='self.control_bits' else f for f in first.facts))
    from dota_coach.decisions.choice_window import derive_feasibility
    codes=tuple(c['code'] for c in derive_feasibility(scope,first,semantics=semantics)['conditions'])
    cov=ContinuityCoverage('fixture-continuity',7,scope.subject_ref,scope.patch,scope.item_id,
        clock(1000),clock(1600),clock(1700),170,(content_hash(first),content_hash(second)),
        content_hash(cue),content_hash(semantics),codes,'fixture.truth-transitions.v1',cue.observation.fact.source_refs,
        (content_hash(cue),))
    registry=ContinuityAdmission(admission(scope,semantics,first,second,cues=(cue,)),frozenset({content_hash(cov)}))
    return scope,semantics,(first,second),(cue,),cov,registry


def run(values,**kwargs):
    scope,mechanics,samples,cues,coverage,registry=values
    return monitor_choice_stream(scope,samples,cues,cutoff=clock(2000),cutoff_record_index=200,
        semantics=mechanics,coverages=(coverage,),admission=registry,**kwargs)


def test_reviewed_truth_stream_supports_span_until_material_control_transition():
    result=run(stream())
    assert result['supported_span_count']==1
    assert result['spans'][0]['interval_ms']==[1000,1300]
    assert result['spans'][0]['duration_ms']==300
    assert result['spans'][1]['status']=='unknown'
    assert result['training_eligible'] is False and result['strategic_quality']=='not_established'


def test_matching_snapshots_ttl_and_stable_until_do_not_establish_continuity():
    values=stream();scope,mechanics,samples,cues,cov,registry=values
    initial=replace(samples[0],stable_until=clock(1800))
    result=monitor_choice_stream(scope,(initial,),cues,cutoff=clock(2000),cutoff_record_index=200,
        semantics=mechanics,admission=ContinuityAdmission(admission(scope,mechanics,initial,cues=cues),frozenset()))
    assert result['supported_span_count']==0
    assert result['spans'][0]['reason_codes']==['complete_constraint_cue_pause_transition_review_missing']


@pytest.mark.parametrize('kind',['unreviewed','missing_condition','future_receipt','future_time','forecast'])
def test_incomplete_or_unavailable_coverage_never_grants_span(kind):
    scope,mechanics,samples,cues,cov,registry=stream()
    if kind=='unreviewed':registry=replace(registry,coverage_hashes=frozenset())
    else:
        if kind=='missing_condition':cov=replace(cov,condition_codes=cov.condition_codes[:-1])
        if kind=='future_receipt':cov=replace(cov,source_record_index=201)
        if kind=='future_time':cov=replace(cov,available_at=clock(2100))
        if kind=='forecast':cov=replace(cov,available_at=clock(1200))
        registry=replace(registry,coverage_hashes=frozenset({content_hash(cov)}))
    result=run((scope,mechanics,samples,cues,cov,registry))
    assert result['supported_span_count']==0


def test_coverage_cannot_hide_an_intermediate_transition_sample():
    scope,mechanics,samples,cues,cov,registry=stream()
    cov=replace(cov,sample_hashes=(content_hash(samples[0]),))
    registry=replace(registry,coverage_hashes=frozenset({content_hash(cov)}))
    with pytest.raises(ValueError,match='omitted'):
        run((scope,mechanics,samples,cues,cov,registry))


def test_freshness_boundary_closes_supported_span_instead_of_holding_values_forever():
    scope,mechanics,samples,cues,cov,registry=stream()
    samples=(samples[0],)
    cov=replace(cov,end=clock(1900),available_at=clock(1950),source_record_index=195,
        sample_hashes=(content_hash(samples[0]),))
    registry=ContinuityAdmission(admission(scope,mechanics,*samples,cues=cues),frozenset({content_hash(cov)}))
    result=run((scope,mechanics,samples,cues,cov,registry))
    assert result['spans'][0]['interval_ms']==[1000,1800]
    assert run((scope,mechanics,samples,cues,cov,registry),minimum_duration_ms=850)['supported_span_count']==0


def test_future_transition_and_coverage_do_not_change_earlier_prefix():
    scope,mechanics,samples,cues,cov,registry=stream()
    def prefix(selected):
        return monitor_choice_stream(scope,selected,cues,cutoff=clock(1200),cutoff_record_index=120,
            semantics=mechanics,coverages=(cov,),admission=registry)
    first=prefix(samples[:1]);later=prefix(samples)
    assert first==later
    assert first['supported_span_count']==0


def test_closed_reconstruction_does_not_change_decision_start_feature():
    values=stream();scope,mechanics,samples,cues,cov,registry=values
    before=monitor_choice_stream(scope,samples[:1],cues,cutoff=clock(1200),cutoff_record_index=120,
        semantics=mechanics,admission=registry)
    after=run(values)
    assert before['spans'][0]['decision_start_hash']==after['spans'][0]['decision_start_hash']


def test_complete_raw_writes_and_portable_validation_cannot_grant_continuity():
    scope,mechanics,samples,cues,cov,registry=stream()
    with pytest.raises(ValueError,match='raw writes'):replace(cov,mode='all_entity_callbacks')
    with pytest.raises(TypeError,match='portable'):
        monitor_choice_stream(scope,samples,cues,cutoff=clock(2000),cutoff_record_index=200,admission={'validated':True})


def test_unknown_pause_at_start_prevents_support_even_with_reviewed_coverage():
    scope,mechanics,samples,cues,cov,registry=stream()
    samples=(replace(samples[0],paused=None),samples[1])
    cov=replace(cov,sample_hashes=tuple(content_hash(s) for s in samples))
    registry=ContinuityAdmission(admission(scope,mechanics,*samples,cues=cues),frozenset({content_hash(cov)}))
    assert run((scope,mechanics,samples,cues,cov,registry))['supported_span_count']==0


def test_reviewed_cue_retraction_closes_initial_span_at_actual_validity():
    from dota_coach.decisions.choice_window import ChoiceCue
    scope,mechanics,samples,cues,cov,registry=stream()
    retraction=operand('screen.reaction_cue',False,available=1100,record=110)
    retraction=replace(retraction,fact=replace(retraction.fact,fact_id='fixture:cue-retraction'))
    cancelled=ChoiceCue(retraction,paused=False)
    cues=(*cues,cancelled)
    cov=replace(cov,cue_transition_hashes=tuple(content_hash(c) for c in cues))
    registry=ContinuityAdmission(admission(scope,mechanics,*samples,cues=cues),frozenset({content_hash(cov)}))
    result=run((scope,mechanics,samples,cues,cov,registry),minimum_duration_ms=50)
    assert result['spans'][0]['interval_ms']==[1000,1100]
    assert run((scope,mechanics,samples,cues,cov,registry))['supported_span_count']==0
    with pytest.raises(ValueError,match='cue transition'):
        run((scope,mechanics,samples,cues,replace(cov,cue_transition_hashes=(content_hash(cues[0]),)),registry))


def test_material_transition_without_exact_time_review_prevents_support():
    scope,mechanics,samples,cues,cov,registry=stream()
    # Remove the receipt for the control transition while keeping its sample
    # and completeness certificate; completeness does not validate its timing.
    control=next(f for f in samples[1].facts if f.fact.predicate=='self.control_bits')
    registry=replace(registry,choice_admission=replace(registry.choice_admission,
        fact_hashes=registry.choice_admission.fact_hashes-{control.input_hash}))
    result=run((scope,mechanics,samples,cues,cov,registry))
    assert result['supported_span_count']==0


def portable(values=None):
    from dataclasses import asdict
    scope,semantics,samples,cues,cov,registry=values or stream()
    return {'schema_version':'foresight.choice-stream.v1','choice_input':{
        'schema_version':'foresight.choice-evidence.v1','scope':asdict(scope),
        'semantics':asdict(semantics),'samples':[asdict(s) for s in samples],'cues':[asdict(c) for c in cues]},
        'cutoff':asdict(clock(2000)),'cutoff_record_index':200,'minimum_duration_ms':150,
        'coverages':[asdict(cov)]}


def test_portable_monitor_loader_cannot_self_admit_coverage(tmp_path):
    import json
    from dota_coach.decisions.choice_monitor import load_monitor_input
    value=load_monitor_input(portable())
    assert monitor_choice_stream(**value)['supported_span_count']==0
    with pytest.raises(ValueError):load_monitor_input(portable()|{'admission':'verified'})
    file=tmp_path/'duplicate.json';file.write_text('{"schema_version":"a","schema_version":"b"}')
    with pytest.raises(ValueError,match='duplicate'):load_monitor_input(file)


def reviewed_stream():
    from tests.test_choice_window import reviewed_fixture
    from dota_coach.decisions.choice_monitor import load_monitor_input,monitor_input_record
    from dota_coach.validation.contracts import FactCheck
    scope,mechanics,sample,cue,sample_record,sample_labels=reviewed_fixture()
    *_,cov,_registry=stream()
    cov=replace(cov,sample_hashes=(content_hash(sample),))
    value=load_monitor_input(portable((scope,mechanics,(sample,),(cue,),cov,None)))
    record=monitor_input_record(value,replay_sha256=sample_record.replay_hash)
    labels=tuple(replace(a,decision_id=record.decision_id,input_hash=record.input_hash,
        facts_checked=(FactCheck('continuity-context:'+record.input_hash,'correct','available','Synthetic contract fixture'),
            FactCheck('continuity-coverage:'+content_hash(cov),'correct','available','Synthetic truth stream fixture')))
        for a in sample_labels)
    return value,(sample_record,record),(*sample_labels,*labels)


def test_exact_independent_stream_review_and_negative_revision_revoke_support():
    from dota_coach.decisions.choice_monitor import resolve_reviewed_continuity
    from dota_coach.validation.contracts import FactCheck
    value,records,labels=reviewed_stream()
    registry=resolve_reviewed_continuity(value,replay_sha256='c'*64,records=iter(records),annotations=iter(labels))
    assert monitor_choice_stream(**value,admission=registry)['supported_span_count']==1
    last=labels[-1]
    changed=replace(last,annotation_version=2,previous_annotation_hash=last.annotation_hash,revision_reason='Fixture correction',
        facts_checked=tuple(replace(c,correctness='incorrect') if c.fact_id.startswith('continuity-coverage:') else c for c in last.facts_checked))
    registry=resolve_reviewed_continuity(value,replay_sha256='c'*64,records=records,annotations=(*labels,changed))
    assert monitor_choice_stream(**value,admission=registry)['supported_span_count']==0
    with pytest.raises(ValueError,match='another'):
        resolve_reviewed_continuity(value,replay_sha256='e'*64,records=records,annotations=labels)


def test_single_declared_stream_reviewer_cannot_establish_continuity():
    from dota_coach.decisions.choice_monitor import resolve_reviewed_continuity
    value,records,labels=reviewed_stream()
    registry=resolve_reviewed_continuity(value,replay_sha256='c'*64,records=records,annotations=labels[:-1])
    assert monitor_choice_stream(**value,admission=registry)['supported_span_count']==0


@pytest.mark.parametrize('label_index',[1,3])
def test_reviewer_kind_downgrade_revokes_older_expert_vote(label_index):
    from dota_coach.decisions.choice_monitor import resolve_reviewed_continuity
    value,records,labels=reviewed_stream()
    old=labels[label_index]
    revision=replace(old,annotation_version=2,previous_annotation_hash=old.annotation_hash,
        revision_reason='Fixture withdrawal of expert status',annotator_kind='self_evaluation')
    registry=resolve_reviewed_continuity(value,replay_sha256='c'*64,records=records,annotations=(*labels,revision))
    assert monitor_choice_stream(**value,admission=registry)['supported_span_count']==0


def test_numeric_future_sample_cannot_enter_earlier_time_prefix():
    scope,mechanics,samples,cues,cov,registry=stream()
    extra=replace(samples[0],sample_id='future',prefix_record_index=110,at=clock(1500))
    def query(selected):
        return monitor_choice_stream(scope,selected,cues,cutoff=clock(1200),cutoff_record_index=120,
            semantics=mechanics,admission=registry)
    assert query(samples[:1])==query((samples[0],extra))
