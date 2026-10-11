from dataclasses import replace

import pytest

from dota_coach.validation.contracts import Annotation,DatasetRecord,FactCheck
from dota_coach.validation.fact_quality import fact_quality_report


def record():
    return DatasetRecord('d1','a'*64,1,'b'*64,'p1','patch','holdout')


def annotation(who,correctness='incorrect',version=1):
    return Annotation('d1','a'*64,'b'*64,'patch',who,('insufficient_evidence',),'unknown',
        'source review',facts_checked=(FactCheck('hp',correctness,'unknown','client unavailable'),),
        unknowns=('cue',),review_pass='extraction',annotation_version=version,
        previous_annotation_hash='c'*64 if version>1 else None,revision_reason='corrected' if version>1 else None)


def test_fact_metrics_do_not_confuse_one_rater_revisions_with_independence():
    a=annotation('e1')
    old=annotation('e1',correctness='correct')
    new=replace(annotation('e1',version=2),previous_annotation_hash=old.annotation_hash)
    report=fact_quality_report((old,new),(record(),),split='holdout')
    assert report['factual_error_rate']['value'] is None
    b=annotation('e2')
    report=fact_quality_report((a,b),(record(),),split='holdout')
    assert report['factual_error_rate']['value']==1


def test_disputed_and_system_facts_stay_out_of_known_denominator():
    report=fact_quality_report((annotation('e1'),annotation('e2','correct'),
        replace(annotation('bot'),annotator_kind='system')),(record(),),split='holdout')
    assert report['factual_error_rate']['denominator']==0
    assert report['factual_error_rate']['unknown_or_disputed']==1
    assert report['counts']['disputed']==1


@pytest.mark.parametrize('field,value', (
    ('input_hash','c'*64), ('replay_hash','d'*64), ('patch','another_patch'),
    ('dataset_kind','synthetic'), ('decision_id','other_decision'),
))
def test_standalone_fact_metrics_reject_labels_reviewed_in_another_input(field,value):
    wrong=replace(annotation('e1'),**{field:value})
    with pytest.raises(ValueError):
        fact_quality_report((wrong,annotation('e2')),(record(),),split='holdout')


def test_duplicate_manifest_identity_cannot_overwrite_the_review_binding():
    with pytest.raises(ValueError,match='duplicate decision id'):
        fact_quality_report((annotation('e1'),annotation('e2')),
            (record(),replace(record(),input_hash='c'*64)),split='holdout')


def test_duplicate_annotation_version_cannot_double_vote():
    with pytest.raises(ValueError,match='duplicate annotation identity'):
        fact_quality_report((annotation('e1'),annotation('e1')),(record(),),split='holdout')


@pytest.mark.parametrize('include_previous', (False,True))
def test_missing_or_corrupted_revision_chain_is_rejected(include_previous):
    old=annotation('e1')
    new=annotation('e1',version=2)
    rows=(old,new) if include_previous else (new,)
    with pytest.raises(ValueError,match='revision chain missing or corrupted'):
        fact_quality_report(rows,(record(),),split='holdout')


def test_unknown_partition_is_an_error_instead_of_an_empty_quality_report():
    with pytest.raises(ValueError,match='unknown evaluation partition'):
        fact_quality_report((),(record(),),split='invented')


def test_standalone_metrics_bind_iterator_inputs_before_aggregating():
    report=fact_quality_report(iter((annotation('e1'),annotation('e2'))),
        iter((record(),)),split='holdout')
    assert report['factual_error_rate']['denominator']==1
    assert report['factual_error_rate']['value']==1
