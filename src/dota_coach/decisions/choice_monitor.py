"""Reconstruct finite constraint spans from independently reviewed transitions.

Freshness is not persistence. Continuous support requires complete *constraint
truth transitions*, including cue availability and pauses, rather than merely
all entity callbacks or snapshots. Results are retrospective at the cutoff;
decision-start hashes never include later coverage or state changes.
"""
from dataclasses import asdict, dataclass

from dota_coach.evidence.contracts import SourceRef, TimeRef, content_hash
from dota_coach.evidence.clock_math import decimal, numeric_interval, numeric_bound
from .choice_window import (
    ChoiceScope, ChoiceSample, ChoiceCue, MechanicalSemantics, EvidenceAdmission,
    _bounds, _sample_projection, _cue_projection, resolve_choice_windows,
)


@dataclass(frozen=True)
class ContinuityCoverage:
    coverage_id: str
    match_id: int
    subject_ref: str
    patch: str
    item_id: str
    start: TimeRef
    end: TimeRef
    available_at: TimeRef
    source_record_index: int
    sample_hashes: tuple[str, ...]
    cue_hash: str
    semantic_hash: str
    condition_codes: tuple[str, ...]
    transition_method_version: str
    source_refs: tuple[SourceRef, ...]
    cue_transition_hashes: tuple[str, ...] = ()
    mode: str = 'complete_constraint_truth_transitions_with_cue_and_pause'

    def __post_init__(self):
        if not all(isinstance(v,str) and v for v in (self.coverage_id,self.subject_ref,self.patch,self.item_id,self.transition_method_version)):
            raise ValueError('explicit continuity identity and transition semantics required')
        if type(self.match_id) is not int or self.match_id<=0 or type(self.source_record_index) is not int or self.source_record_index<0:
            raise ValueError('exact match and source record required')
        if any(not isinstance(v,TimeRef) for v in (self.start,self.end,self.available_at)):
            raise ValueError('typed coverage clocks required')
        if self.mode!='complete_constraint_truth_transitions_with_cue_and_pause':
            raise ValueError('sample coverage or raw writes cannot establish constraint persistence')
        if not isinstance(self.sample_hashes,tuple) or not isinstance(self.condition_codes,tuple) or len(set(self.condition_codes))!=len(self.condition_codes):
            raise ValueError('immutable exact witness hashes and distinct condition codes required')
        if not isinstance(self.source_refs,tuple) or not self.source_refs or any(not isinstance(s,SourceRef) for s in self.source_refs):
            raise ValueError('continuity requires original transition source receipts')
        if not isinstance(self.cue_transition_hashes,tuple):raise ValueError('immutable cue transition manifest required')
        for h in (*self.sample_hashes,*self.cue_transition_hashes,self.cue_hash,self.semantic_hash):
            if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):
                raise ValueError('exact witness/semantics/cue digest required')


@dataclass(frozen=True)
class ContinuityAdmission:
    choice_admission: EvidenceAdmission
    coverage_hashes: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.choice_admission,EvidenceAdmission) or not isinstance(self.coverage_hashes,frozenset):
            raise TypeError('caller-owned typed review registry required; portable flags cannot grant continuity')
        for h in self.coverage_hashes:
            if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):
                raise ValueError('exact reviewed continuity digest required')


def _prefix(scope,samples,cues,coverages,cutoff,cutoff_record_index):
    if not isinstance(scope,ChoiceScope) or not isinstance(cutoff,TimeRef) or type(cutoff_record_index) is not int or cutoff_record_index<0:
        raise ValueError('typed scope/cutoff and exact source prefix required')
    if not all(isinstance(x,tuple) for x in (samples,cues,coverages)) or any(not isinstance(c,ContinuityCoverage) for c in coverages):
        raise ValueError('immutable typed stream inputs required')
    if any(not isinstance(s,ChoiceSample) for s in samples) or any(not isinstance(c,ChoiceCue) for c in cues):
        raise ValueError('typed samples and cues required')
    selected=tuple(s for s in samples if s.prefix_record_index<cutoff_record_index
        and (not _bounds(s.at,scope.clock_mapping_version) or s.at.definitely_available_before(cutoff)))
    if len({s.sample_id for s in selected})!=len(selected) or any(a.prefix_record_index>=b.prefix_record_index for a,b in zip(selected,selected[1:])):
        raise ValueError('distinct ordered stream sample prefixes required')
    chosen_cues=tuple(c for c in cues if c.observation.source_record_index<cutoff_record_index
        and _bounds(c.observation.fact.available_at,scope.clock_mapping_version)
        and c.observation.fact.available_at.definitely_available_before(cutoff))
    chosen_coverages=tuple(c for c in coverages if c.source_record_index<cutoff_record_index
        and c.available_at.order_status=='verified' and c.available_at.definitely_available_before(cutoff))
    return selected,chosen_cues,chosen_coverages


def _ambiguous_samples(scope,samples,cutoff,cutoff_record_index):
    limit=_bounds(cutoff,scope.clock_mapping_version)
    return tuple(s for s in samples if s.prefix_record_index<cutoff_record_index
        and (b:=_bounds(s.at,scope.clock_mapping_version)) and limit
        and b[0]<limit[1] and not s.at.definitely_available_before(cutoff))


def _unresolved_cues(scope,cues,cutoff,cutoff_record_index):
    limit=_bounds(cutoff,scope.clock_mapping_version)
    return tuple(c for c in cues if c.observation.source_record_index<cutoff_record_index
        and (not (b:=_bounds(c.observation.fact.available_at,scope.clock_mapping_version))
            or limit and b[0]<limit[1] and not c.observation.fact.available_at.definitely_available_before(cutoff)))


def monitor_choice_stream(scope,samples,cues,*,cutoff,cutoff_record_index,
                          semantics=None,coverages=(),admission=None,minimum_duration_ms=150):
    """Compute supported half-open spans, never interpolate unreviewed frames.

    A coverage witness must list every supplied transition sample in its time
    interval and explicitly cover all computed constraint codes plus cue and
    pause transitions. Independent review validates the transition extractor;
    this function computes state conjunction, temporal clipping and splitting.
    It does not certify the extractor or the independence of human reviewers.
    """
    import math
    if type(minimum_duration_ms) not in (int,float) or not math.isfinite(minimum_duration_ms) or minimum_duration_ms<=0:
        raise ValueError('positive finite action duration required')
    if admission is not None and not isinstance(admission,ContinuityAdmission):
        raise TypeError('portable validation fields cannot grant a continuous window')
    selected,chosen_cues,chosen_coverages=_prefix(scope,samples,cues,coverages,cutoff,cutoff_record_index)
    ambiguous=_ambiguous_samples(scope,samples,cutoff,cutoff_record_index)
    unresolved_cues=_unresolved_cues(scope,cues,cutoff,cutoff_record_index)
    barriers=[{'source_record_index':s.prefix_record_index,'at':asdict(s.at),
        'reason':'sample_time_overlaps_query_cutoff'} for s in ambiguous]
    barriers.extend({'source_record_index':c.observation.source_record_index,
        'available_at':asdict(c.observation.fact.available_at) if c.observation.fact.available_at else None,
        'reason':'cue_delivery_unresolved'} for c in unresolved_cues)
    registry=admission.choice_admission if admission else None
    sampled=resolve_choice_windows(scope,selected,chosen_cues,semantics=semantics,admission=registry)
    by_sample={s.sample_id:s for s in selected}
    feasibility={x['sample_id']:x for x in sampled['feasibility_samples']}
    final=_bounds(cutoff,scope.clock_mapping_version)
    valid_coverages=[]
    for c in chosen_coverages:
        if (c.match_id,c.subject_ref,c.patch,c.item_id)!=(scope.match_id,scope.subject_ref,scope.patch,scope.item_id):
            raise ValueError('foreign continuity source scope')
        start,end=_bounds(c.start,scope.clock_mapping_version),_bounds(c.end,scope.clock_mapping_version)
        if not start or not end or any(t.order_status!='verified' for t in (c.start,c.end,c.available_at)) or not c.start.definitely_available_before(c.end):
            continue
        if start[1]>=end[0] or not c.end.definitely_available_before(cutoff) or not c.end.definitely_available_before(c.available_at):
            continue
        witness_samples=sorted((*selected,*ambiguous),key=lambda s:s.prefix_record_index)
        witnesses=tuple(content_hash(s) for s in witness_samples
            if not (b:=_bounds(s.at,scope.clock_mapping_version))
            or b[1]>=start[0] and b[0]<=end[1])
        if witnesses!=c.sample_hashes:
            raise ValueError('continuity witness omitted, altered or imported a transition sample')
        cue_witnesses=tuple(content_hash(cue) for cue in sorted((*chosen_cues,*unresolved_cues),
            key=lambda cue:cue.observation.source_record_index)
            if not (b:=_bounds(cue.observation.fact.valid_at,scope.clock_mapping_version)) or b[0]<=end[1])
        if cue_witnesses!=c.cue_transition_hashes:
            raise ValueError('continuity witness omitted or altered a cue transition')
        if not semantics or content_hash(semantics)!=c.semantic_hash:
            raise ValueError('continuity bound to different mechanical semantics')
        if unresolved_cues or any(_bounds(s.at,scope.clock_mapping_version)[1]>=start[0] for s in ambiguous):
            continue  # Cannot certify continuity through an unresolved later sample.
        if admission and content_hash(c) in admission.coverage_hashes:
            valid_coverages.append((c,start,end))
    spans=[]
    for window in sampled['windows']:
        sample=by_sample[window['sample_id']]
        bounds=_bounds(sample.at,scope.clock_mapping_version)
        cue=next((c for c in chosen_cues if c.observation.fact.fact_id==window['cue_id']),None)
        result={'sample_id':sample.sample_id,'cue_id':window['cue_id'],'decision_start_hash':window['window_id'],
            'status':'unknown','interval_ms':None,'duration_ms':None,'coverage_id':None,
            'reason_codes':[],'scope':'retrospective_constraint_span_as_of_cutoff','training_eligible':False}
        if window['status']!='supported_choice' or not bounds or not final or cutoff.order_status!='verified':
            result['reason_codes'].append('sample_or_cutoff_not_supported')
        else:
            index=selected.index(sample)
            next_bounds=_bounds(selected[index+1].at,scope.clock_mapping_version) if index+1<len(selected) else final
            required={c['code'] for c in feasibility[sample.sample_id]['conditions']}
            matches=[(c,a,b) for c,a,b in valid_coverages if c.cue_hash==content_hash(cue)
                and required<=set(c.condition_codes) and a[1]<=bounds[0]<b[0]]
            if not matches:
                result['reason_codes'].append('complete_constraint_cue_pause_transition_review_missing')
            elif next_bounds is None:
                result['reason_codes'].append('next_transition_clock_unknown')
            elif index+1<len(selected) and not sample.at.definitely_available_before(selected[index+1].at):
                result['reason_codes'].append('transition_order_unknown_or_conflicting')
            else:
                # Select longest independently covered span. End is open: an
                # event at that time belongs to the following state.
                c,a,b=max(matches,key=lambda row:row[2][0])
                transition_end=next_bounds[0]
                interruptions=[later for later in chosen_cues if later.observation.fact.fact_id!=cue.observation.fact.fact_id
                    and later.observation.source_record_index>cue.observation.source_record_index
                    and (later.observation.fact.value is not True or later.observation.fact.status in ('unknown','conflict'))]
                unknown_cue=[later for later in interruptions if later.observation.input_hash not in registry.fact_hashes
                    or content_hash(later) not in registry.cue_hashes or later.observation.fact.valid_at.order_status!='verified'
                    or not _bounds(later.observation.fact.valid_at,scope.clock_mapping_version)
                    or not later.observation.fact.valid_at.definitely_available_before(cutoff)]
                if unknown_cue:
                    result['reason_codes'].append('cue_transition_time_not_independently_bound')
                    spans.append(result)
                    continue
                if interruptions:transition_end=min(transition_end,*(_bounds(later.observation.fact.valid_at,scope.clock_mapping_version)[0] for later in interruptions))
                if index+1<len(selected):
                    following=selected[index+1]
                    if following.paused!=sample.paused:
                        result['reason_codes'].append('pause_transition_time_not_observed')
                        spans.append(result)
                        continue
                    original={f.fact.predicate:f.fact for f in sample.facts}
                    following_predicates={f.fact.predicate for f in following.facts}
                    used_ids={fid for condition in feasibility[sample.sample_id]['conditions'] for fid in condition['operand_fact_ids']}
                    removed={f.fact.predicate for f in sample.facts if f.fact.fact_id in used_ids}-following_predicates
                    if removed:
                        result['reason_codes'].append('material_operand_removal_time_unknown')
                        spans.append(result)
                        continue
                    changed=[f for f in following.facts if f.fact.predicate not in original
                        or (f.fact.value,f.fact.status)!=(original[f.fact.predicate].value,original[f.fact.predicate].status)]
                    invalid=[f for f in changed if f.input_hash not in registry.fact_hashes
                        or f.fact.valid_at.order_status!='verified' or f.fact.available_at is None
                        or not f.fact.valid_at.definitely_available_before(following.at)
                        or not _bounds(f.fact.available_at,scope.clock_mapping_version)
                        or not f.fact.valid_at.definitely_available_before(f.fact.available_at)
                        or not f.fact.available_at.definitely_available_before(cutoff)]
                    if invalid:
                        result['reason_codes'].append('material_transition_time_not_independently_bound')
                        spans.append(result)
                        continue
                    if changed:transition_end=min(transition_end,*(_bounds(f.fact.valid_at,scope.clock_mapping_version)[0] for f in changed))
                reaction=tuple(decimal(v) for v in window['guaranteed_interval_ms'])
                start=max(bounds[1],a[1],reaction[0])
                used={fid for condition in feasibility[sample.sample_id]['conditions'] for fid in condition['operand_fact_ids']}
                fresh_end=min(_bounds(f.fact.valid_at,scope.clock_mapping_version)[0]+decimal(scope.max_fact_age_ms)
                    for f in sample.facts if f.fact.fact_id in used)
                end=min(transition_end,b[0],final[0],reaction[1],fresh_end)
                if sample.at.definitely_available_before(cutoff) and end-start>=decimal(minimum_duration_ms):
                    interval=numeric_interval((start,end),guaranteed=True)
                    duration=decimal(interval[1])-decimal(interval[0])
                    if duration>=decimal(minimum_duration_ms):
                        result.update(status='supported_constraint_span',interval_ms=interval,
                            duration_ms=numeric_bound(duration,upper=False),coverage_id=c.coverage_id)
                    else:result['reason_codes'].append('numeric_export_duration_insufficient')
                else:result['reason_codes'].append('duration_or_freshness_insufficient')
        spans.append(result)
    output={'schema_version':'foresight.choice-monitor.v1','cutoff':asdict(cutoff),'cutoff_record_index':cutoff_record_index,
        'sampled':sampled,'spans':spans,'unresolved_transition_boundaries':barriers,'minimum_duration_ms':minimum_duration_ms,
        'supported_span_count':sum(s['status']=='supported_constraint_span' for s in spans),
        'unknown_span_count':sum(s['status']=='unknown' for s in spans),'game_opportunity_coverage':None,
        'validation_status':'conditional_research_not_certified','strategic_quality':'not_established','training_eligible':False}
    output['prefix_feature_hash']=content_hash({'scope':asdict(scope),'samples':[_sample_projection(s) for s in selected],
        'windows':[{k:v for k,v in w.items() if k not in ('sample_id','cue_id')} for w in sampled['windows']],
        'unresolved_transition_boundaries':barriers})
    output['payload_sha256']=content_hash(output)
    return output


def load_monitor_input(source):
    from pathlib import Path
    from .batch import strict_json
    from .choice_window import load_choice_evidence
    payload=source if isinstance(source,dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    required={'schema_version','choice_input','cutoff','cutoff_record_index','coverages','minimum_duration_ms'}
    if not isinstance(payload,dict) or set(payload)!=required or payload['schema_version']!='foresight.choice-stream.v1':
        raise ValueError('strict choice stream schema required; no portable admission')
    choice=load_choice_evidence(payload['choice_input'])
    if 'samples' not in choice:raise ValueError('typed transition samples required')
    if not isinstance(payload['coverages'],list):raise ValueError('coverage array required')
    coverages=[]
    for row in payload['coverages']:
        if not isinstance(row,dict):raise ValueError('typed continuity coverage required')
        row=dict(row)
        for key in ('start','end','available_at'):row[key]=TimeRef(**row[key])
        for key in ('sample_hashes','condition_codes','cue_transition_hashes'):row[key]=tuple(row.get(key,()))
        row['source_refs']=tuple(SourceRef(**s) for s in row['source_refs'])
        coverages.append(ContinuityCoverage(**row))
    return choice|{'cutoff':TimeRef(**payload['cutoff']),'cutoff_record_index':payload['cutoff_record_index'],
        'coverages':tuple(coverages),'minimum_duration_ms':payload['minimum_duration_ms']}


def monitor_input_record(value,*,replay_sha256,split='development'):
    from dota_coach.validation.contracts import DatasetRecord
    selected,cues,coverages=_prefix(value['scope'],value['samples'],value['cues'],value['coverages'],
        value['cutoff'],value['cutoff_record_index'])
    semantics=value['semantics']
    payload={'scope':asdict(value['scope']),'samples':[asdict(s) for s in selected],
        'cues':[asdict(c) for c in cues],'coverages':[asdict(c) for c in coverages],
        'semantics':asdict(semantics) if semantics else None,'cutoff':asdict(value['cutoff']),
        'cutoff_record_index':value['cutoff_record_index'],'minimum_duration_ms':value['minimum_duration_ms'],
        'ambiguous_sample_hashes':[content_hash(s) for s in _ambiguous_samples(value['scope'],value['samples'],
            value['cutoff'],value['cutoff_record_index'])],
        'unresolved_cue_hashes':[content_hash(c) for c in _unresolved_cues(value['scope'],value['cues'],
            value['cutoff'],value['cutoff_record_index'])]}
    scope=value['scope']
    return DatasetRecord(f'continuity:{scope.match_id}:{scope.subject_ref}:before:{value["cutoff_record_index"]}',
        content_hash(payload),scope.match_id,replay_sha256,scope.subject_ref,scope.patch,split,scope.dataset_kind,(scope.subject_ref,))


def resolve_reviewed_continuity(value,*,replay_sha256,records,annotations):
    from .choice_window import resolve_reviewed_choice_admission
    from dota_coach.validation.pipeline import validate_annotations
    records,annotations=tuple(records),tuple(annotations)
    validate_annotations(annotations,records)
    expected=monitor_input_record(value,replay_sha256=replay_sha256)
    record=next((r for r in records if r.decision_id==expected.decision_id),None)
    if record is None:return None
    expected=monitor_input_record(value,replay_sha256=replay_sha256,split=record.split)
    if record!=expected:raise ValueError('continuity review bound to another input/replay/query')
    latest={}
    for a in annotations:
        if a.decision_id!=record.decision_id or a.review_pass!='extraction':continue
        if a.annotator_id not in latest or a.annotation_version>latest[a.annotator_id].annotation_version:latest[a.annotator_id]=a
    def agreed(fid):
        votes=[c for a in latest.values() if a.dataset_kind=='replay' and a.annotator_kind=='human_expert' for c in a.facts_checked if c.fact_id==fid]
        return len(votes)>=2 and all(c.correctness=='correct' and c.availability=='available' for c in votes)
    if not agreed('continuity-context:'+record.input_hash):return None
    selected,cues,coverages=_prefix(value['scope'],value['samples'],value['cues'],value['coverages'],value['cutoff'],value['cutoff_record_index'])
    registry=resolve_reviewed_choice_admission(value['scope'],selected,cues,value['semantics'],
        replay_sha256=replay_sha256,records=records,annotations=annotations)
    if registry is None:return None
    return ContinuityAdmission(registry,frozenset(content_hash(c) for c in coverages if agreed('continuity-coverage:'+content_hash(c))))
