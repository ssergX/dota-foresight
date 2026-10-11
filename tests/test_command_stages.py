"""Protocol fixtures only: no client stream or authentic expert labels."""
import copy
from dataclasses import replace
import pytest
from tests.test_command_binding import fixture as binding_fixture
from tests.test_order_source import write
from dota_coach.ingest.command_stages import (
    bridge_command_stages, observation_hash, StageReceipt, StageRegistry, REVIEW_CLAIMS,
)
from dota_coach.ingest.order_source import CALLBACKS
from dota_coach.evidence.contracts import EntityRef, SourceRef, TimeRef
from dota_coach.decisions.command_census import census_commands, CommandScope


def clock(ms, width=0):
    return TimeRef(ms,uncertainty_ms=width,clock_mapping_version='fixture.clock',order_status='verified')


def seal(path, rows):
    for i,row in enumerate(rows):row.update(record_index=i+1,sequence_in_tick=i+1)
    rows[-1]['message_count']=len(rows)-2
    rows[-1]['counts']={kind:sum(r.get('protobuf_type')==kind for r in rows[1:-1]) for kind in CALLBACKS}
    write(path,rows)


def fixture(tmp_path):
    path, extraction, rows=binding_fixture(tmp_path)
    for kind,data in ((CALLBACKS[3],{'order_id':8,'sequence_number':0}),
                      (CALLBACKS[1],{'unit_order_sequence':[0]})):
        row=copy.deepcopy(rows[1]);row.update(protobuf_type=kind,data=data,
            entity_context={'field_entities':{},'selected_heroes':[],
                            'semantics':'raw_index_candidate_and_exact_handle_links_only'})
        rows.insert(-1,row)
    rows[1]['data']['sequence_number']=0
    seal(path,rows)
    return path,extraction,rows


def receipt(rows, stage='attempt', record=2, at=100, available=110, **changes):
    result=StageReceipt('receipt:'+str(record)+':'+stage,'transaction:1',2,observation_hash(rows[1]),
        record,observation_hash(rows[record-1]),EntityRef('match:7',42,3),EntityRef('match:7',44,7),
        stage,clock(at),clock(available),'fixture.stage.v1',REVIEW_CLAIMS,
        (SourceRef('fixture.review','b'*64,'synthetic_review','fixture.v1','per-record-fixture'),))
    return replace(result,**changes)


def reviewed(*receipts, **changes):
    return replace(StageRegistry(7,11,'a'*64,6943,'fixture.patch',tuple(receipts)),**changes)


def run(path, extraction, registry=None, **changes):
    args={'extraction':extraction,'account_id':11,'cutoff_record_index':5,
          'cutoff':clock(1000) if registry else None,'registry':registry}
    args.update(changes)
    return bridge_command_stages(path,**args)


def test_equal_zero_sequences_and_auxiliary_callbacks_never_infer_stages(tmp_path):
    path,ext,rows=fixture(tmp_path);result=run(path,ext)
    prefix=result.document['prefix']
    assert prefix['raw_linked_root_count']==1
    assert prefix['callback_counts'][CALLBACKS[3]]==prefix['callback_counts'][CALLBACKS[1]]==1
    assert not result.events and not result.cast_started
    assert set(prefix['conditional_stage_counts'].values())=={0}
    assert prefix['attempt_count'] is prefix['attempt_coverage'] is None
    assert prefix['raw_root_examples'][0]['raw_fields']['sequence_number']==0
    assert prefix['training_eligible'] is False


def test_explicit_root_binding_retains_each_stage_without_coverage(tmp_path):
    path,ext,rows=fixture(tmp_path)
    receipts=(receipt(rows),receipt(rows,'accepted',3,120,130),receipt(rows,'rejected',4,140,150))
    result=run(path,ext,reviewed(*receipts))
    assert [e.stage for e in result.events]==['attempt','accepted','rejected']
    assert len(result.document['prefix']['stage_ledger'])==3
    scope=CommandScope(7,'account:11','fixture.patch',EntityRef('match:7',44,7),'fixture.clock')
    census=census_commands(scope,result.events,interval_start=clock(0),interval_end=clock(500),
                          cutoff=clock(1000),cutoff_record_index=5)
    assert census['stage_counts']['attempt']==1
    assert census['status']=='unknown' and census['derived_fact']['value'] is None
    assert census['training_eligible'] is False


def test_cast_started_separate_from_commit_and_not_promoted_to_attempt(tmp_path):
    path,ext,rows=fixture(tmp_path)
    result=run(path,ext,reviewed(receipt(rows,'cast_started')))
    assert len(result.cast_started)==1 and not result.events
    assert result.document['prefix']['conditional_stage_counts']['cast_started']==1
    assert result.document['prefix']['conditional_stage_counts']['committed']==0
    assert result.document['prefix']['attempt_count'] is None


@pytest.mark.parametrize('field,value',[
    ('origin_sha256','c'*64),('source_sha256','c'*64),
    ('actor_entity',EntityRef('match:7',42,4)),('action_entity',EntityRef('match:7',44,8)),
    ('actor_entity',EntityRef('match:8',42,3)),('origin_record_index',3),
])
def test_damaged_root_hash_or_generation_refused(tmp_path,field,value):
    path,ext,rows=fixture(tmp_path)
    r=receipt(rows,'rejected',4)
    with pytest.raises(ValueError):run(path,ext,reviewed(replace(r,**{field:value})))


@pytest.mark.parametrize('field,value',[
    ('match_id',8),('account_id',12),('replay_sha256','b'*64),('game_build',6944),('patch','other.patch'),
])
def test_foreign_review_scope_refused(tmp_path,field,value):
    path,ext,rows=fixture(tmp_path)
    ext.replay.manifest.patch='fixture.patch'
    with pytest.raises(ValueError):run(path,ext,reviewed(receipt(rows),**{field:value}))


def test_duplicate_receipt_counts_once_but_conflicts_refused(tmp_path):
    path,ext,rows=fixture(tmp_path);r=receipt(rows)
    assert len(run(path,ext,reviewed(r,r)).events)==1
    with pytest.raises(ValueError,match='conflicting'):
        run(path,ext,reviewed(r,replace(r,stage='accepted')))


def test_transaction_cannot_join_distinct_root_orders(tmp_path):
    path,ext,rows=fixture(tmp_path);rows.insert(-1,copy.deepcopy(rows[1]));seal(path,rows)
    r=receipt(rows,'accepted',5,120,130,origin_record_index=5,origin_sha256=observation_hash(rows[4]))
    with pytest.raises(ValueError,match='distinct roots'):
        run(path,ext,reviewed(receipt(rows),r),cutoff_record_index=6)


def test_future_and_undelivered_reviews_leave_prefix_unchanged(tmp_path):
    path,ext,rows=fixture(tmp_path)
    baseline=run(path,ext,reviewed(receipt(rows)),cutoff_record_index=4)
    future=receipt(rows,'rejected',4,200,210,action_entity=EntityRef('match:7',44,99))
    late=receipt(rows,'accepted',3,500,1100,actor_entity=EntityRef('match:8',42,3))
    result=run(path,ext,reviewed(receipt(rows),future,late),cutoff_record_index=4)
    assert baseline.document['prefix']==result.document['prefix']


def test_changed_future_source_does_not_change_point_review_or_prefix_hash(tmp_path):
    path,ext,rows=fixture(tmp_path);r=receipt(rows)
    before=run(path,ext,reviewed(r),cutoff_record_index=3)
    rows[2]['data']['sequence_number']=999;seal(path,rows)
    after=run(path,ext,reviewed(r),cutoff_record_index=3)
    assert before.document['prefix']==after.document['prefix']
    assert before.events==after.events
    assert before.document['source_provenance']['source_sha256']!=after.document['source_provenance']['source_sha256']


def test_sub_float_uncertainty_at_cutoff_not_available(tmp_path):
    path,ext,rows=fixture(tmp_path)
    r=receipt(rows,at=0,available=1e16,available_at=clock(1e16,1e-7))
    result=run(path,ext,reviewed(r),cutoff=clock(1e16))
    assert not result.events and result.document['prefix']['conditional_stage_counts']['attempt']==0


@pytest.mark.parametrize('field,value',[
    ('reviewed_claims',frozenset()),('reviewed_claims',list(REVIEW_CLAIMS)),
    ('stage','cancelled'),('at',200),('available_at',replace(clock(110),clock_mapping_version='other')),
    ('semantic_version','unknown'),('source_record_index',True),('review_sources',()),
])
def test_incomplete_or_ill_typed_receipt_refused(tmp_path,field,value):
    _,_,rows=fixture(tmp_path)
    with pytest.raises((TypeError,ValueError)):receipt(rows,**{field:value})


def test_no_portable_review_flag_or_unmapped_cutoff(tmp_path):
    path,ext,rows=fixture(tmp_path)
    with pytest.raises(TypeError):run(path,ext,{'validated':True})
    with pytest.raises(ValueError):run(path,ext,reviewed(receipt(rows)),cutoff=None)
    with pytest.raises(ValueError):run(path,ext,reviewed(receipt(rows)),cutoff=replace(clock(1000),order_status='unknown'))


def test_unknown_future_top_field_and_incomplete_footer_refused(tmp_path):
    path,ext,rows=fixture(tmp_path);rows[3]['future_result']='won';seal(path,rows)
    with pytest.raises(ValueError,match='projection'):run(path,ext,cutoff_record_index=3)
    rows[3].pop('future_result');seal(path,rows[:-1])
    with pytest.raises(ValueError):run(path,ext,cutoff_record_index=3)


def test_bounded_examples_explicitly_account_for_omissions(tmp_path):
    path,ext,rows=fixture(tmp_path);rows.insert(-1,copy.deepcopy(rows[1]));seal(path,rows)
    result=run(path,ext,cutoff_record_index=6,max_examples=1)
    assert result.document['prefix']['raw_linked_root_count']==2
    assert result.document['prefix']['omitted_root_examples']==1


def test_foreign_prior_clock_refused_but_future_clock_ignored(tmp_path):
    path,ext,rows=fixture(tmp_path)
    r=receipt(rows,'rejected',4)
    r=replace(r,at=replace(r.at,clock_mapping_version='other'),
              available_at=replace(r.available_at,clock_mapping_version='other'))
    with pytest.raises(ValueError,match='foreign'):run(path,ext,reviewed(r))
    assert not run(path,ext,reviewed(r),cutoff_record_index=4).events


def test_cli_explicit_orders_cutoff_and_source_overwrite_guard(tmp_path,monkeypatch):
    import json
    from dota_coach.cli import main
    import dota_coach.ingest.trace as trace
    path,ext,rows=fixture(tmp_path)
    saved=tmp_path/'extraction.json';saved.write_text('{}')
    monkeypatch.setattr(trace,'load_trace_result',lambda p:ext)
    args=['command-stages-source','--source-jsonl',str(path),'--extraction-json',str(saved),
          '--account-id','11','--cutoff-record-index','3']
    target=tmp_path/'stages.json'
    assert main(args+['--out',str(target)])==0
    result=json.loads(target.read_text())
    assert result['prefix']['raw_linked_root_count']==1
    assert result['prefix']['callback_counts'][CALLBACKS[3]]==0
    assert result['prefix']['attempt_count'] is None
    before=path.read_bytes()
    assert main(args+['--out',str(path)])==1 and path.read_bytes()==before


@pytest.mark.parametrize('cutoff',[0,True,6])
def test_invalid_or_unobserved_cutoff_refused(tmp_path,cutoff):
    path,ext,rows=fixture(tmp_path)
    with pytest.raises(ValueError):run(path,ext,cutoff_record_index=cutoff)

@pytest.mark.parametrize('mapping',['unknown','Unknown',' unavailable','unavailable','Unverified','legacy/unknown',None])
def test_reserved_or_ill_typed_clock_mapping_refused(tmp_path,mapping):
    _,_,rows=fixture(tmp_path)
    r=receipt(rows)
    with pytest.raises(ValueError):replace(r,at=replace(r.at,clock_mapping_version=mapping),
                                           available_at=replace(r.available_at,clock_mapping_version=mapping))


@pytest.mark.parametrize('stage',['attempt','accepted','cast_started'])
def test_review_aliases_cannot_duplicate_semantic_command(tmp_path,stage):
    path,ext,rows=fixture(tmp_path);r=receipt(rows,stage)
    with pytest.raises(ValueError,match='aliases'):
        run(path,ext,reviewed(r,replace(r,receipt_id='review-alias')))


def test_review_artifact_hashes_separate_from_analytical_stage_hash(tmp_path):
    path,ext,rows=fixture(tmp_path);r=receipt(rows)
    before=run(path,ext,reviewed(r))
    refs=tuple(replace(ref,artifact_id='replacement-review',content_hash='c'*64) for ref in r.review_sources)
    after=run(path,ext,reviewed(replace(r,review_sources=refs,receipt_id='replacement-receipt')))
    assert before.document['prefix']==after.document['prefix']
    assert before.events[0].command_id==after.events[0].command_id
    assert before.document['review_manifest_sha256']!=after.document['review_manifest_sha256']
    assert before.events[0].source_refs!=after.events[0].source_refs


def test_example_display_limit_does_not_change_analytical_hash(tmp_path):
    path,ext,rows=fixture(tmp_path)
    assert run(path,ext,max_examples=0).document['prefix']['input_hash']==run(path,ext).document['prefix']['input_hash']

@pytest.mark.parametrize('build',['9999',True,'unknown',6944])
def test_known_extraction_build_mismatch_refused(tmp_path,build):
    path,ext,rows=fixture(tmp_path);ext.replay.manifest.game_build=build
    with pytest.raises(ValueError,match='build'):run(path,ext,reviewed(receipt(rows)))


@pytest.mark.parametrize('build',['6943',6943])
def test_matching_known_extraction_build_accepted(tmp_path,build):
    path,ext,rows=fixture(tmp_path);ext.replay.manifest.game_build=build
    assert len(run(path,ext,reviewed(receipt(rows))).events)==1


def test_zero_account_cannot_be_own_player(tmp_path):
    path,ext,rows=fixture(tmp_path)
    with pytest.raises(ValueError):run(path,ext,account_id=0)
    with pytest.raises(ValueError):reviewed(receipt(rows),account_id=0)


def test_review_revocation_rebuild_removes_all_conditional_stages(tmp_path):
    path,ext,rows=fixture(tmp_path)
    assert len(run(path,ext,reviewed(receipt(rows))).events)==1
    result=run(path,ext,reviewed())
    assert not result.events and result.document['prefix']['stage_ledger']==[]
    assert result.document['prefix']['attempt_count'] is None
    assert result.document['prefix']['training_eligible'] is False


def test_transaction_relabelling_cannot_duplicate_single_raw_root(tmp_path):
    path,ext,rows=fixture(tmp_path);r=receipt(rows)
    with pytest.raises(ValueError,match='relabelled'):
        run(path,ext,reviewed(r,replace(r,receipt_id='alias',attempt_id='transaction:2')))


@pytest.mark.parametrize('build',[True,'6943',-1,2**32])
def test_noncanonical_raw_source_build_refused(tmp_path,build):
    path,ext,rows=fixture(tmp_path);rows[-1]['game_build']=build;seal(path,rows)
    with pytest.raises(ValueError,match='build'):run(path,ext)
