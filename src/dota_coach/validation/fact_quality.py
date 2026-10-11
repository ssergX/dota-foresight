"""Fact correctness is reviewed separately from the decision verdict."""
from collections import Counter, defaultdict


def fact_quality_report(annotations, records, *, split, min_raters=2):
    # This is a public entry point, not only an evaluate_predictions helper.
    # Bind every label and revision before selecting the requested cohort, so
    # a reused decision ID cannot credit facts reviewed in another input.
    from .contracts import SPLITS
    from .pipeline import validate_annotations

    if split not in SPLITS:
        raise ValueError('unknown evaluation partition')
    if type(min_raters) is not int or min_raters<2:
        raise ValueError('fact review requires independent rater agreement')
    annotations, records = tuple(annotations), tuple(records)
    validate_annotations(annotations, records)
    cohort={r.decision_id:r for r in records if r.split==split and r.dataset_kind=='replay'}
    # Revisions replace a rater's previous answer within that review pass. The
    # same rater reviewing both decision and extraction cannot count twice.
    latest={}
    for a in annotations:
        if a.decision_id not in cohort or a.dataset_kind!='replay' or a.annotator_kind!='human_expert':
            continue
        if a.review_pass not in ('extraction','decision_blinded','text'):
            continue
        key=(a.decision_id,a.annotator_id,a.review_pass)
        if key not in latest or a.annotation_version>latest[key].annotation_version:
            latest[key]=a
    by_fact=defaultdict(lambda:defaultdict(list))
    for a in latest.values():
        for check in a.facts_checked:
            by_fact[(a.decision_id,check.fact_id)][a.annotator_id].append(check)
    counts=Counter()
    detail=[]
    for (decision,fact),raters in sorted(by_fact.items()):
        # Conflicting votes by one rater across passes do not become agreement.
        correctness={k:{c.correctness for c in checks} for k,checks in raters.items()}
        availability={k:{c.availability for c in checks} for k,checks in raters.items()}
        correct_values=set.union(*correctness.values())
        available_values=set.union(*availability.values())
        if len(raters)<min_raters:
            status='insufficient_raters'
        elif any(len(v)>1 for v in correctness.values()) or len(correct_values)>1:
            status='disputed'
        else:
            status=next(iter(correct_values))
        counts[status]+=1
        available=next(iter(available_values)) if len(raters)>=min_raters and len(available_values)==1 else 'unknown_or_disputed'
        counts['availability_'+available]+=1
        detail.append({'decision_id':decision,'fact_id':fact,'raters':len(raters),
            'correctness':status,'availability':available})
    known=counts['correct']+counts['incorrect']
    return {'schema_version':'foresight.fact-quality.v1','split':split,
        'distinct_reviewed_facts':len(by_fact),'known_consensus_facts':known,
        'factual_error_rate':{'numerator':counts['incorrect'],'denominator':known,
            'value':counts['incorrect']/known if known else None,
            'unknown_or_disputed':len(by_fact)-known},
        'counts':dict(counts),'facts':detail,'validation_status':'independent_provenance_pending',
        'limitations':['Rate applies only to the independently checked supplied facts, not every extracted field.',
            'Rater identity and independence require external review; declarations do not establish them.',
            'No extraction-coverage or client-validation claim follows from a zero numerator.']}
