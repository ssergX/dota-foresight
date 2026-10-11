import json
from dataclasses import asdict
import pytest

from dota_coach.decisions.trace_episode import activation_notebook
from dota_coach.validation.trace_pack import export_trace_review_pack
from tests.test_trace_episode import result


def test_real_prefix_pack_omits_system_assessment_and_hidden_outcome(tmp_path):
    notebook=activation_notebook(result(),actor='npc_dota_hero_kez',resource_slot=0)
    summary=export_trace_review_pack(notebook,replay_hash='a'*64,patch='fixture',account_id=7,
        participants=('account:7',),out_dir=tmp_path)
    case=json.loads((tmp_path/'blinded/blind-cases.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert 'verdict' not in case and 'goals' not in case
    assert 'source_trace_hash' not in case
    assert {f['predicate'] for f in case['own_state']}=={'self.hp','self.max_hp','self.mana','self.level','self.alive'}
    assert case['review_readiness'].endswith('context_incomplete')
    assert summary['independent_human_labels']==0
    template=json.loads((tmp_path/'blinded/annotation-template.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert template['annotator_id'] is None and template['acceptable_verdicts']==[]
    assert (tmp_path/'annotations.jsonl').read_text()==''
    assert not (tmp_path/'blinded/predictions.jsonl').exists()


def test_unknown_or_synthetic_origins_do_not_manufacture_real_quality_cases(tmp_path):
    notebook=activation_notebook(result(),actor='npc_dota_hero_kez',resource_slot=0)
    notebook['dataset_kind']='synthetic'
    summary=export_trace_review_pack(notebook,replay_hash='a'*64,patch='fixture',account_id=7,
        participants=('account:7',),out_dir=tmp_path)
    row=json.loads((tmp_path/'dataset.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert row['dataset_kind']=='synthetic' and summary['dataset_kind']=='synthetic'
    assert summary['independent_human_labels']==0


def test_changed_case_with_existing_labels_is_rejected_before_pack_overwrite(tmp_path):
    from dota_coach.validation.contracts import Annotation
    notebook=activation_notebook(result(),actor='npc_dota_hero_kez',resource_slot=0)
    kwargs=dict(replay_hash='a'*64,patch='fixture',account_id=7,participants=('account:7',),out_dir=tmp_path)
    export_trace_review_pack(notebook,**kwargs)
    path=tmp_path/'blinded/blind-cases.jsonl';before=path.read_bytes()
    case=json.loads(before.decode('utf-8').splitlines()[0])
    annotation=Annotation(case['decision_id'],case['input_hash'],'a'*64,'fixture','fixture-human',
        ('insufficient_evidence',),'unknown','fixture label only',unknowns=('missing',),dataset_kind='unknown')
    (tmp_path/'annotations.jsonl').write_text(json.dumps(asdict(annotation))+'\n',encoding='utf-8')
    notebook['entries'][0]['own_state']=[(k,101 if k=='hp' else v) for k,v in notebook['entries'][0]['own_state']]
    with pytest.raises(ValueError,match='input_hash'):
        export_trace_review_pack(notebook,**kwargs)
    assert path.read_bytes()==before
