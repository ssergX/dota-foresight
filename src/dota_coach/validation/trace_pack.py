"""Real activation cases for independent review, without outcome disclosure."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from dota_coach.evidence.contracts import content_hash
from dota_coach.validation.contracts import DatasetRecord, Prediction
from dota_coach.validation.pipeline import write_dataset, audit_splits, evaluate_predictions, load_annotations


def export_trace_review_pack(notebook: dict, *, replay_hash: str, patch: str,
                             account_id: int, participants: tuple[str, ...], out_dir) -> dict:
    if notebook.get('schema_version')!='foresight.activation-notebook.v1':
        raise ValueError('activation notebook required')
    target=Path(out_dir)
    target.mkdir(parents=True,exist_ok=True)
    (target/'blinded').mkdir(exist_ok=True)
    (target/'system').mkdir(exist_ok=True)
    cases,records,templates,predictions=[],[],[],[]
    for row in notebook['entries']:
        case={'schema_version':'foresight.trace-blind-case.v1','decision_id':row['decision_id'],
            'match_id':row['match_id'],'subject':f'account:{account_id}',
            'observation_time':row['observation_time'],
            'boundary_status':'activation_observed_choice_unresolved',
            'observed_action':{'stage':'combat_log_observation','item':row['item']},
            'own_state_time':row['own_state_time'],
            'own_state':[{'fact_id':f"{row['decision_id']}:sample:{key}",'predicate':f'self.{key}',
                'value':value,'correctness':'unverified','availability_to_subject':'unverified',
                'source_prefix_record_index':row['own_state_source_record_index']} for key,value in row['own_state']],
            'missing_context':['exact_prechoice_state','screen_reaction_cue','verified_feasible_actions',
                'subject_goal','historical_mechanics'],
            'media_status':'player_prefix_recording_required',
            'review_readiness':'extraction_review_ready_decision_context_incomplete'}
        resource=row.get('resource_review')
        if resource is not None:
            case['own_resource_facts']=[{'fact_id':row['decision_id']+':'+key,
                'predicate':'self.'+key,'raw_observation':resource[source],
                'semantic_validation':'unverified'} for key,source in [('mana','mana_source'),('activation_mana_cost','cost_source')]]
        digest=content_hash(case)
        kind=notebook.get('dataset_kind','unknown')
        record=DatasetRecord(row['decision_id'],digest,row['match_id'],replay_hash,f'account:{account_id}',
            patch,'development',kind,participants)
        cases.append(case|{'input_hash':digest})
        records.append(record)
        predictions.append(Prediction(row['decision_id'],digest,'insufficient_evidence','activation-notebook.v1'))
        templates.append({'schema_version':'foresight.annotation.v1','decision_id':row['decision_id'],
            'input_hash':digest,'replay_hash':replay_hash,'patch':patch,'annotator_id':None,
            'acceptable_verdicts':[],'eligibility':None,'rationale':'','facts_checked':[],
            'available_actions':[],'decisive_evidence_ids':[],'unknowns':[],
            'dataset_kind':kind,'annotator_kind':'human_expert','annotation_version':1,
            'pass':'decision_blinded','outcome_visible':False,'system_verdict_visible':False,
            'adjudication_status':'unreviewed','previous_annotation_hash':None,'revision_reason':None})
    def rows(name,values):
        (target/name).write_text(''.join(json.dumps(v,ensure_ascii=False,allow_nan=False)+'\n' for v in values),encoding='utf-8')
    # A zero-byte file means no independent labels were supplied. The template
    # cannot be loaded as a completed annotation and contributes to no metric.
    annotation_path=target/'annotations.jsonl'
    annotations=load_annotations(annotation_path) if annotation_path.exists() else ()
    summary={'schema_version':'foresight.trace-review-pack.v1','cases':len(cases),
        'dataset_kind':notebook.get('dataset_kind','unknown'),'partition':'development','independent_human_labels':sum(a.annotator_kind=='human_expert' and a.review_pass=='decision_blinded' and a.dataset_kind=='replay' for a in annotations),
        'decision_context':'incomplete','blinding':'no_world_outcome_system_verdict_in_cases',
        'split_audit':audit_splits(tuple(records)),
        'quality':evaluate_predictions(tuple(predictions),annotations,tuple(records),split='development')}
    # Reject changed cases with existing labels before overwriting any pack file.
    rows('blinded/blind-cases.jsonl',cases)
    rows('blinded/annotation-template.jsonl',templates)
    rows('system/predictions.jsonl',[asdict(p) for p in predictions])
    write_dataset(target/'dataset.jsonl',records)
    annotation_path.touch(exist_ok=True)
    (target/'quality.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (target/'README.md').write_text('''# Независимая проверка реальных активаций

Пять типов проверки разделены: извлечение, вердикт, текст, полезность и последующее поведение.
Здесь реальные наблюдения активаций; экспертных ответов нет. Все случаи находятся в development.
Это не независимый holdout и не доказательство качества. Dataset kind в dataset.jsonl
определяет происхождение каждого случая; synthetic/unknown не входят в real quality cohort.

1. Для проверки извлечения сверить исходные record references, SteamID/hero ID,
   время до старта/после завершения/паузу, собственные ресурсы, item handle и каст в клиенте.
2. Перед оценкой решения получить запись экрана игрока или отдельно проверенный
   pre-choice prefix. Сейчас случай не содержит полного контекста для игрового вердикта.
3. Два независимых эксперта сначала получают только blinded/ и проверенный prefix.
   Не показывать им system/, quality.json, analysis.json, полный replay или итог боя.
4. В blinded/annotation-template.jsonl нет предвыбранного ответа. Указать настоящий annotator_id,
   acceptable_verdicts, проверенные факты/действия и основания. Нет данных — явно unknown.
5. После решения отдельно открыть результат и текст. Противоречия разобрать третьим экспертом,
   сохранив предыдущую разметку и hash revision chain. Не изменять случай задним числом.
6. Для holdout зарезервировать новые матчи и игроков; исключить также матчи retrieval,
   проверить всех десятерых участников и перенос патча. Не перемаркировать development как holdout.
7. Импортировать настоящие labels командой review-quality. Ни template, ни system prediction
   не являются экспертной разметкой и не открывают validation gate.

Полезность спрашивается у реального игрока после совета; изменение поведения измеряется
на следующих неперекрывающихся сопоставимых матчах. Эти результаты здесь не заполнены.
''',encoding='utf-8')
    return summary
