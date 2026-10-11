"""Integrated real-replay report. Source data and analytical authority stay separate."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
from pathlib import Path

from dota_coach.decisions.trace_episode import activation_notebook
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult
from dota_coach.surface import feedback_controls, feedback_script, context_sections
from dota_coach.evidence.contracts import TimeRef
from dota_coach.learning.contextual import BuildQuestion, GoalHypothesis, analyze_build_question
from dota_coach.learning.portfolio import build_descriptive_portfolio
from dota_coach.validation.trace_pack import export_trace_review_pack
from dota_coach.profile import describe_series


@dataclass(frozen=True)
class NotebookAssessment:
    verdict: str = "insufficient_evidence"
    reason_codes: tuple[str, ...] = ("choice_boundary_unresolved", "criterion_not_validated")
    status: str = "unverified"

    @property
    def assessment_hash(self):
        return content_hash(self)


@dataclass(frozen=True)
class NotebookDossier:
    observation: dict
    assessment: NotebookAssessment = NotebookAssessment()


@dataclass(frozen=True)
class NotebookCard:
    episode_id: str
    dossier: NotebookDossier


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _time(value):
    if value is None:
        return "время не установлено"
    sign = "−" if value < 0 else ""
    sec = abs(value)
    return f"{sign}{int(sec)//60}:{sec%60:04.1f}"


def _study_html(discovery, match_id, *, hero_id, patch_id, role):
    if discovery is None:
        return "<section id='study'><h2>Матчи для изучения</h2><p>Подбор не запущен. Команда study ищет существующие матчи и проверяет источник и доступность replay.</p></section>", None
    cards=[]
    for example in discovery.examples:
        if (example.study.match_id == match_id or example.study.hero_id != hero_id
                or patch_id is None or example.patch_id != patch_id
                or role == 'unknown' or example.role_estimate.role != role):
            continue
        s=example.study
        links=" · ".join(f"<a href='{html.escape(r.source_url,quote=True)}'>Источник {i+1}</a>" for i,r in enumerate(example.receipts))
        expertise={'registered_pro':'Профессиональный аккаунт по реестру OpenDota','high_rank':'Высокая медаль источника; числовой MMR не подтверждён'}.get(example.expertise_class,'Статус игрока не установлен')
        role_label=s.role.replace('position_','Позиция ')
        cards.append(f"<article class='card'><h3><a href='https://www.opendota.com/matches/{s.match_id}'>Матч {s.match_id}</a></h3>"
            f"<p>{html.escape(expertise)} · {html.escape(role_label)} (оценка) · патч источника {example.patch_id if example.patch_id is not None else 'неизвестен'}</p>"
            f"<p>{html.escape(s.learning_task)}</p><p>Replay: {html.escape(s.replay_availability)}. Проверка доступности заголовка: {html.escape(example.replay_probe.checked_at)}.</p>"
            f"<details><summary>Почему пример и где перенос ограничен</summary><p>Совпадает герой; роль оценена источником. Сходство стиля, целей и противников не установлено.</p><ul>"+
            "".join(f"<li>{html.escape(v)}</li>" for v in s.transfer_limitations)+f"</ul>{links}</details></article>")
    return ("<section id='study'><h2>Матчи для изучения</h2><p>Это сравнение наблюдаемых решений сильных игроков. Статус игрока не делает каждое его действие правильным.</p>"+
        "".join(cards)+( "<p>Других подходящих матчей в ограниченном поиске не найдено; это не отсутствие таких матчей вообще.</p>" if not cards else "")+
        "<details><summary>Источники и исключения</summary><a href='study-sources.json'>Полученные данные и receipts</a></details></section>", asdict(discovery))


def render_live_report(result: TraceResult, raw_match: dict, *, account_id: int,
                       catalog, out_dir: str | Path, discovery=None, build_advice=None,
                       action_states=None,combat_names_path=None,orders_path=None,
                       constraint_source_path=None,event_visibility_path=None,
                       command_binding_path=None,projectiles_path=None,unit_control_trace_path=None,movement_input_path=None,defensive_impact_path=None,
                       impact_prefix_path=None,terrain_input_path=None,history_input_path=None,
                       analytical_review=None,witness_sink=None,video_path=None,video_offset=None,ffmpeg=None) -> dict:
    from dota_coach.video.trace_clips import validate_video_options,guard_video_source,build_activation_clips,clip_card_html
    validate_video_options(video_path,video_offset)
    guard_video_source(video_path,out_dir)
    if raw_match.get("match_id") != result.replay.match_id:
        raise ValueError("match and trace identity disagree")
    players=[p for p in raw_match.get("players",[]) if type(p.get("account_id")) is int and p["account_id"]==account_id]
    if len(players)!=1:
        raise ValueError("target account is absent or ambiguous")
    player=players[0]
    slot=player.get("player_slot")
    if type(slot) is not int or slot not in (*range(5),*range(128,133)):
        raise ValueError("invalid source player slot")
    resource_slot=slot if slot<128 else slot-128+5
    hero=next((h for h in catalog.heroes if h.hero_id==player.get("hero_id")),None)
    if hero is None:
        raise ValueError("catalog hero identity is required for source join")
    wire_hero=result.replay.heroes.get(resource_slot)
    expected_name=hero.internal_name.removeprefix("npc_dota_hero_").replace("_", "").lower()
    if wire_hero is None or wire_hero.removeprefix("CDOTA_Unit_Hero_").replace("_", "").lower()!=expected_name:
        raise ValueError("replay selected hero and sourced target hero disagree or are unresolved")
    identity=result.audit.get('resource_identities',{}).get(str(resource_slot),{})
    if identity.get('m_iPlayerSteamID') != str(76561197960265728+account_id) or identity.get('m_nSelectedHeroID') != player['hero_id']:
        raise ValueError('replay Steam account/selected hero identity does not bind the target account')
    replay_sources={'schema_version':'foresight.replay-sources.v1','match_id':result.replay.match_id,
        'orders':None,'constraints':None,'event_visibility':None,'command_binding':None,'projectiles':None,'training_eligible':False}
    unit_control=None
    mechanics=None
    movement=None
    defensive_impact=None
    impact_prefix=None
    case_assessment=None
    terrain_support=None
    verified_history=None
    workflow=None
    history_witness=None
    from dota_coach.analytical_workflow import AnalyticsReviewContext,evaluate_prefix_workflow,evaluate_case_proposal,evaluate_history_workflow
    if analytical_review is not None and not isinstance(analytical_review,AnalyticsReviewContext):
        raise TypeError('typed backend analytical review required; portable grants forbidden')
    context=analytical_review or AnalyticsReviewContext()
    if witness_sink is not None and not callable(witness_sink):
        raise TypeError('backend witness sink must be callable')
    if impact_prefix_path is not None and defensive_impact_path is not None:
        raise ValueError('choose one prefix compiler or direct defensive impact proposal')
    if orders_path is not None:
        from dota_coach.ingest.order_source import load_order_source
        replay_sources['orders']=load_order_source(orders_path,extraction=result)
    if constraint_source_path is not None:
        from dota_coach.decisions.mechanics_adapter import _verified_sidecar,summarize_constraint_mechanics
        candidate=_verified_sidecar(constraint_source_path,result)
        if (candidate.get('expected_account_id')==account_id and candidate.get('resource_slot')==resource_slot
                and candidate.get('actor')==hero.internal_name):
            replay_sources['constraints']={k:v for k,v in candidate.items() if k!='path'}
            mechanics=summarize_constraint_mechanics(constraint_source_path,extraction=result,account_id=account_id)
    if event_visibility_path is not None:
        from dota_coach.ingest.event_visibility import load_event_visibility_source
        replay_sources['event_visibility']=load_event_visibility_source(event_visibility_path,extraction=result)
    if command_binding_path is not None:
        from dota_coach.ingest.command_binding import load_command_binding_source
        replay_sources['command_binding']=load_command_binding_source(command_binding_path,extraction=result,account_id=account_id)
    if projectiles_path is not None:
        from dota_coach.ingest.projectile_source import load_projectile_source
        replay_sources['projectiles']=load_projectile_source(projectiles_path,extraction=result,account_id=account_id)
    if unit_control_trace_path is not None:
        from dota_coach.ingest.unit_control import build_unit_control_source,MAX_SNAPSHOTS
        from dota_coach.ingest.action_state import DEFENSIVE_ITEMS
        unit_cutoffs=tuple(sorted(a.event_record_index for a in result.actions
            if a.actor==hero.internal_name and a.kind=='item' and a.ability_or_item in DEFENSIVE_ITEMS))
        unit_control=build_unit_control_source(unit_control_trace_path,extraction=result,
            account_id=account_id,cutoff_record_indices=unit_cutoffs[:MAX_SNAPSHOTS])
        unit_control['anchor_selection']={'observed_defensive_anchors':len(unit_cutoffs),
            'projected_anchors':min(len(unit_cutoffs),MAX_SNAPSHOTS),
            'omitted_anchors':max(0,len(unit_cutoffs)-MAX_SNAPSHOTS),'policy':'earliest_source_records_bounded'}
        unit_control['payload_sha256']=content_hash({k:v for k,v in unit_control.items() if k!='payload_sha256'})
    if movement_input_path is not None:
        from dota_coach.decisions.movement import load_movement_input,evaluate_movement
        proposal=load_movement_input(movement_input_path)
        scope=proposal['scope']
        allies={f"account:{p['account_id']}" for p in raw_match['players']
                if type(p.get('account_id')) is int and p['account_id']>0 and type(p.get('player_slot')) is int
                and (p['player_slot']<128)==(slot<128)}
        if scope.match_id!=result.replay.match_id or scope.observer_ref!=f'account:{account_id}' or scope.subject_ref not in allies or scope.dataset_kind!=result.replay.manifest.dataset_kind:
            raise ValueError('movement proposal does not bind selected match/player/team/source kind')
        movement=evaluate_movement(**proposal)
    if defensive_impact_path is not None:
        from dota_coach.decisions.defensive_impact import load_defensive_impact_input,evaluate_defensive_impact
        proposal=load_defensive_impact_input(defensive_impact_path)
        scope=proposal['scope']
        if (scope.match_id!=result.replay.match_id or scope.subject_ref!=f'account:{account_id}'
                or scope.observer_ref!=f'account:{account_id}'
                or scope.dataset_kind!=result.replay.manifest.dataset_kind
                or scope.item_entity.replay_id!=f'match:{result.replay.match_id}'
                or type(raw_match.get('patch')) is not int
                or scope.patch!=f"opendota_patch_id:{raw_match['patch']}"):
            raise ValueError('defensive impact proposal does not bind selected match/player/source kind')
        defensive_impact=evaluate_defensive_impact(**proposal)
        from dota_coach.decisions.impact_pipeline import ImpactCaseInput
        workflow=evaluate_case_proposal(ImpactCaseInput(**proposal,replay_hash=result.replay.manifest.replay_hash),review=context.case_review)
        case_assessment=workflow.document(current_review=context.case_review)['case_assessment']
    if impact_prefix_path is not None:
        from dota_coach.ingest.impact_prefix import load_impact_prefix_input
        proposal=load_impact_prefix_input(impact_prefix_path)
        query=proposal['query']
        if (query.match_id!=result.replay.match_id or query.replay_sha256!=result.replay.manifest.replay_hash
                or query.subject_ref!=f'account:{account_id}' or query.observer_ref!=f'account:{account_id}'
                or query.dataset_kind!=result.replay.manifest.dataset_kind
                or type(raw_match.get('patch')) is not int or query.patch!=f"opendota_patch_id:{raw_match['patch']}"
                or result.replay.manifest.game_build is None or query.game_build!=str(result.replay.manifest.game_build)):
            raise ValueError('impact prefix proposal does not bind selected match/player/patch/build/source')
        workflow=evaluate_prefix_workflow(proposal,prefix_registry=context.prefix_registry,review=context.case_review)
        document=workflow.document(current_review=context.case_review)
        impact_prefix=document['prefix'];defensive_impact=document['defensive_impact'];case_assessment=document['case_assessment']
    if terrain_input_path is not None:
        from dota_coach.decisions.terrain import load_terrain_input,evaluate_terrain
        proposal=load_terrain_input(terrain_input_path);scope=proposal['scope']
        if (scope.match_id!=result.replay.match_id or scope.subject_ref!=f'account:{account_id}'
                or scope.observer_ref!=f'account:{account_id}' or scope.dataset_kind!=result.replay.manifest.dataset_kind
                or type(raw_match.get('patch')) is not int or scope.patch!=f"opendota_patch_id:{raw_match['patch']}"
                or result.replay.manifest.game_build is None or scope.game_build!=str(result.replay.manifest.game_build)):
            raise ValueError('terrain proposal does not bind selected match/player/patch/build/source')
        terrain_support=evaluate_terrain(**proposal,registry=context.terrain_registry)
    if history_input_path is not None:
        from dota_coach.learning.verified_history import load_verified_history_input
        proposal=load_verified_history_input(history_input_path)
        if proposal['account_id']!=account_id:
            raise ValueError('history proposal does not bind selected account')
        history_witness,verified_history=evaluate_history_workflow(proposal,review=context.history_review)
    replay_sources['payload_sha256']=content_hash(replay_sources)
    from dota_coach.ingest.semantic_events import build_semantic_events,load_combat_semantic_events
    semantics=build_semantic_events(result,raw_match)
    if combat_names_path is not None:
        sidecar=load_combat_semantic_events(combat_names_path,match_id=result.replay.match_id,
            expected_replay_sha256=result.replay.manifest.replay_hash,dataset_kind=result.replay.manifest.dataset_kind)
        semantics['lanes'].update(sidecar['lanes'])
        semantics['coverage'].update(sidecar['coverage'])
        semantics['combat_names_source']={key:sidecar[key] for key in ('source_sha256','source_match_binding','payload_sha256')}
        semantics['payload_sha256']=content_hash({k:v for k,v in semantics.items() if k!='payload_sha256'})
    notebook=activation_notebook(result,actor=hero.internal_name,resource_slot=resource_slot)
    resource_reviews={}
    resource_opportunities=None
    choice_windows=None
    if action_states is not None:
        from dota_coach.ingest.action_state import validate_action_states
        from dota_coach.decisions.resource_review import review_resource_prefix
        validate_action_states(action_states,result)
        if action_states.get('resource_slot')!=resource_slot or action_states.get('actor')!=hero.internal_name or (
                action_states.get('account_id_verified_by_resource')!=account_id):
            raise ValueError('own action states do not bind the target account and hero')
        from dota_coach.decisions.opportunity_discovery import discover_resource_opportunities
        resource_opportunities=discover_resource_opportunities(action_states,result)
        from dota_coach.decisions.choice_window import resolve_resource_choice_windows
        choice_windows=resolve_resource_choice_windows(action_states,result)
        notebook['raw_candidate_discovery']={'artifact':'resource-opportunities.json',
            'observed_windows':len(resource_opportunities['observed_windows']),
            'processed_samples':resource_opportunities['supplied_stream_coverage']['processed_sample_count'],
            'game_opportunity_coverage':None,'assessment_admission':'not_established'}
        snapshots={s['action_id']:s for s in action_states['snapshots']}
        for row in notebook['entries']:
            if row['decision_id'] in snapshots:
                review=review_resource_prefix(snapshots[row['decision_id']],item_id=row['item'])
                resource_reviews[row['decision_id']]=review
                row['resource_review']=review
                row['input_hash']=content_hash({k:v for k,v in row.items() if k not in ('input_hash','source_trace_hash')})
    # A point for discussion, not a resolved purchase choice. No future
    # purchases or raw enemy roster enter the question's known context.
    known_times=[row['observation_time'] for row in notebook['entries'] if row['observation_time'] is not None and row['observation_time']>=0]
    cutoff=min(known_times) if known_times else 0
    portfolio=build_descriptive_portfolio(raw_match,account_id)
    prefix=tuple(p for p in portfolio.purchases.purchases if p.game_time_seconds is not None and p.game_time_seconds<cutoff)
    question=BuildQuestion(f"build:{result.replay.match_id}:{account_id}:{cutoff}",result.replay.match_id,
        f"player:{account_id}",TimeRef(cutoff*1000,clock_mapping_version=result.replay.manifest.timebase_version),
        GoalHypothesis(f"goal:{result.replay.match_id}:{account_id}"),hero_id=player['hero_id'],purchases=prefix,
        candidate_item_ids=("item_black_king_bar","item_manta","item_force_staff"))
    expected_advice=analyze_build_question(question,catalog)
    if build_advice is not None and build_advice != expected_advice:
        raise ValueError('supplied build advice does not bind the source question and catalog')
    build_advice=expected_advice
    cards=[NotebookCard(row["decision_id"],NotebookDossier(row)) for row in notebook["entries"]]
    out=Path(out_dir)
    clip_navigation=build_activation_clips(notebook,out,replay_sha256=result.replay.manifest.replay_hash,
        video_path=video_path,video_offset=video_offset,ffmpeg=ffmpeg)
    clip_receipts={row['decision_id']:row for row in clip_navigation['entries']}
    out.mkdir(parents=True,exist_ok=True)
    (out/'unit-control.json').write_text(_safe_json(unit_control),encoding='utf-8')
    (out/'replay-sources.json').write_text(_safe_json(replay_sources),encoding='utf-8')
    (out/'mechanics.json').write_text(_safe_json(mechanics),encoding='utf-8')
    (out/'movement-support.json').write_text(_safe_json(movement),encoding='utf-8')
    (out/'defensive-impact.json').write_text(_safe_json(defensive_impact),encoding='utf-8')
    for name,value in (('impact-prefix.json',impact_prefix),('case-assessment.json',case_assessment),
                       ('terrain-support.json',terrain_support),('verified-history.json',verified_history)):
        (out/name).write_text(_safe_json(value),encoding='utf-8')
    (out/"source-match.json").write_text(_safe_json(raw_match),encoding="utf-8")
    (out/"trace-audit.json").write_text(_safe_json(result.audit),encoding="utf-8")
    (out/"observed-actions.json").write_text(_safe_json([asdict(a) for a in result.actions]),encoding="utf-8")
    (out/"activation-notebook.json").write_text(_safe_json(notebook),encoding="utf-8")
    (out/'semantic-events.json').write_text(_safe_json(semantics),encoding='utf-8')
    from dota_coach.ingest.semantic_lifecycle import build_semantic_lifecycles
    lifecycles=build_semantic_lifecycles(semantics)
    (out/'semantic-lifecycles.json').write_text(_safe_json(lifecycles),encoding='utf-8')
    from dota_coach.ingest.objective_state import build_objective_state
    objective_state=build_objective_state(semantics)
    (out/'objective-state.json').write_text(_safe_json(objective_state),encoding='utf-8')
    from dota_coach.learning.ward_plan import build_ward_observations
    ward_observations=build_ward_observations(result,account_id=account_id,resource_slot=resource_slot,actor=hero.internal_name)
    (out/'ward-observations.json').write_text(_safe_json(ward_observations),encoding='utf-8')
    from dota_coach.learning.ward_analysis import analyze_ward_prefix
    ward_prefixes=[];ward_exclusions=[]
    for event in ward_observations['events']:
        if event['operation']!='placed':
            continue
        team=ward_observations['subject_team']
        if team is None or event['team'] not in (team,None):
            ward_exclusions.append({'ward_id':event['ward_id'],'source_ref':event['source_ref'],
                'reason':'planning_subject_team_unknown' if team is None else 'other_team_placement'})
            continue
        ward_prefixes.append(analyze_ward_prefix(ward_observations,event['ward_id']))
    ward_analysis={'schema_version':'foresight.ward-analysis-batch.v1','analyses':ward_prefixes,
        'excluded_placements':ward_exclusions,'scope':'all_supplied_placement_callbacks',
        'game_opportunity_coverage':None,'training_eligible':False}
    ward_analysis['payload_sha256']=content_hash(ward_analysis)
    (out/'ward-analysis.json').write_text(_safe_json(ward_analysis),encoding='utf-8')
    if resource_opportunities is not None:
        (out/'resource-opportunities.json').write_text(_safe_json(resource_opportunities),encoding='utf-8')
        (out/'choice-windows.json').write_text(_safe_json(choice_windows),encoding='utf-8')
    if action_states is not None:
        (out/'action-states.json').write_text(_safe_json(action_states),encoding='utf-8')
    participants=tuple(f"account:{p['account_id']}" for p in raw_match['players'] if type(p.get('account_id')) is int and p['account_id']>0)
    review_pack=export_trace_review_pack(notebook,replay_hash=result.replay.manifest.replay_hash,
        patch=f"opendota_patch_id:{raw_match['patch']}" if raw_match.get('patch') is not None else 'unknown',
        account_id=account_id,participants=participants,out_dir=out/'independent-review')
    from dota_coach.validation.review_workspace import write_review_workspace
    write_review_workspace(out/'independent-review')
    extensions,ext_payload=context_sections(raw_match,account_id,result.replay)
    # Keep the existing lifecycle/purchases/habit surface. The source-backed
    # examples replace its explicit unavailable study section.
    start=extensions.find("<section id='study'>")
    end=extensions.find("<section id='habits'>",start)
    from dota_coach.ingest.study_sources import estimate_role
    target_role=estimate_role(raw_match,player,'source-match').role
    study,study_payload=_study_html(discovery,result.replay.match_id,hero_id=player['hero_id'],
        patch_id=raw_match.get('patch'),role=target_role)
    if start>=0 and end>=0:
        extensions=extensions[:start]+study+extensions[end:]
    if discovery is not None:
        (out/"study-sources.json").write_text(_safe_json(study_payload),encoding="utf-8")
    series={raw_match['match_id']:raw_match}
    if discovery is not None:
        for example in discovery.examples:
            if example.account_id==account_id:
                for receipt in example.receipts:
                    if receipt.source_url==f'https://api.opendota.com/api/matches/{example.study.match_id}':
                        series.setdefault(example.study.match_id,receipt.data)
    groups=describe_series(list(series.values()),account_id)
    profile={'schema_version':'foresight.descriptive-profile.v1','groups':[asdict(g) for g in groups],
        'origin':'supplied_match_and_captured_study_sources','scope':'public_demo_account_not_user_history',
        'confirmed_habits':[],'training_status':'insufficient_evidence'}
    (out/'profile.json').write_text(_safe_json(profile),encoding='utf-8')
    profile_cards=[]
    for group in groups:
        values=''.join(f"<tr><td>{html.escape(m.metric)}</td><td>{m.median_value if m.median_value is not None else 'неизвестно'}</td><td>{m.measured_matches}/{m.considered_matches}</td></tr>" for m in group.metrics)
        items=''.join(f"<li>{html.escape(p.item)}: покупка в {p.matches_with_purchase}/{p.matches_with_purchase_log} матчей с журналом; всего рассмотрено {p.considered_matches}. Первое время: {_time(p.median_first_purchase_seconds)}.</li>" for p in group.item_preferences[:12])
        profile_cards.append(f"<details><summary>Герой {group.hero_id} · роль {html.escape(group.role)} · {len(group.match_ids)} матчей</summary><p>Патч источника: {html.escape(group.patch)}. Прокси уровня противников: {html.escape(group.opponent_level_proxy)}.</p><div class='table-scroll'><table><tr><th>Измерение</th><th>Медиана</th><th>Есть данные / рассмотрено</th></tr>{values}</table></div><h4>Наблюдаемые покупки</h4><ul>{items}</ul></details>")
    profile_html="<section id='profile'><h2>Описание доступной серии</h2><p>Метрики ресурсов, участия и покупки — измерения, а не оценка стиля. Эта небольшая серия публичного аккаунта не устанавливает устойчивую привычку или исправление ошибки. Движение и выбор риска требуют проверенного контекста.</p>"+''.join(profile_cards)+"<a href='profile.json'>Контекст, источники и знаменатели</a></section>"
    build_html=""
    if build_advice is not None:
        advice=asdict(build_advice)
        (out/"build-context.json").write_text(_safe_json(advice),encoding="utf-8")
        option_cards=[]
        for option in build_advice.options:
            option_cards.append(f"<article class='card'><h3>{html.escape(option.label)}</h3><p>{html.escape(option.goal_condition)}</p>"
                f"<p>Выполнимость: {html.escape(option.feasibility)}. Оптимальность не установлена.</p><details><summary>Задача, цена выбора и пересмотр</summary><ul>"+
                "".join(f"<li>{html.escape(v)}</li>" for v in option.advantages+option.tradeoffs)+"</ul><h4>Пересмотреть, если</h4><ul>"+
                "".join(f"<li>{html.escape(v)}</li>" for v in option.revisit_conditions)+"</ul>"+
                " · ".join(f"<a href='{html.escape(url,quote=True)}'>Механика в источнике</a>" for url in option.source_urls)+"</details></article>")
        build_html=("<section id='build-context'><h2>Контекстный план предметов</h2><p>Сравнение для момента первой наблюдаемой защитной активации. Цель, угроза и применимость механики к патчу ещё требуют проверки.</p>"+
            "<details><summary>Уточнить цель и необходимые сведения</summary><ul>"+"".join(f"<li>{html.escape(v.description)}</li>" for v in build_advice.goal_hypotheses)+
            "".join(f"<li>{html.escape(v)}</li>" for v in build_advice.research_questions)+"</ul></details>"+"".join(option_cards)+
            "<a href='build-context.json'>Задачи, альтернативы и источники JSON</a></section>")
    parts=[]
    observed_outcomes={}
    for i,card in enumerate(cards):
        row=card.dossier.observation
        ident=html.escape(card.episode_id,quote=True)
        descriptor=catalog.item(row['item'])
        item_label=descriptor.label if descriptor is not None else row['item'].removeprefix('item_').replace('_',' ')
        state_labels={'hp':'Здоровье','max_hp':'Максимальное здоровье','mana':'Мана','level':'Уровень','alive':'Жив по полю replay'}
        state=" · ".join(f"{html.escape(state_labels[k])}: {('да' if v else 'нет') if type(v) is bool else round(v,1) if type(v) is float else v if v is not None else 'неизвестно'}" for k,v in row["own_state"])
        t=row['observation_time']
        aftermath=[a for a in result.actions if t is not None and a.game_time is not None
            and t<a.game_time<=t+10 and (a.actor==hero.internal_name or a.target==hero.internal_name)]
        observed_outcomes[card.episode_id]={'status':'retrospective_observations_only',
            'window_seconds':10,'events':[asdict(a) for a in aftermath],
            'death_absence_interpretation':'not_proof_of_survival_or_good_decision',
            'role':'outcome_pass_excluded_from_notebook_input'}
        outcomes=''.join(f"<li>{_time(a.game_time)} · {html.escape(a.kind)} · {html.escape(a.ability_or_item or a.target or 'неизвестно')}</li>" for a in aftermath)
        alternatives="".join(f"<tr><td>{html.escape(name)}</td><td>{html.escape(status)}</td><td>{html.escape(pro)}</td><td>{html.escape(con)}</td></tr>" for name,status,pro,con in row["alternatives"])
        resource=resource_reviews.get(card.episode_id)
        if resource is not None:
            labels={'exact_inventory_handle_resolves':'Предмет связан с точным собственным inventory handle',
                'raw_mana_at_least_reported_cost':'Сравнение собственной маны с полем стоимости',
                'raw_cooldown_end_not_after_clock':'Кулдаун: интерпретация сырого поля требует проверки',
                'control_allows_activation':'Ограничения контроля',
                'inventory_slot_allows_activation':'Доступность применения из слота',
                'target_and_command_constraints_satisfied':'Ограничения цели и команды'}
            checks=''.join(f"<li>{html.escape(labels.get(c['code'],c['code']))}: {'да по непроверенным полям' if c.get('value') is True else 'нет по непроверенным полям' if c.get('value') is False else 'неизвестно'}. Источники: {html.escape(str(c.get('evidence_record_indices',[])))}.</li>" for c in resource['checks'])
            resource_html=(f"<h4>Ресурсы и условия доступности</h4><p>{html.escape(resource['claim'])}</p><ul>{checks}</ul>"
                f"<p>Полная выполнимость неизвестна. {html.escape(resource['next_question'])}</p><a href='action-states.json'>Собственные слоты, кулдауны и источник каждого поля</a>")
            from dota_coach.learning.resource_plan import resource_plan_form
            resource_html += resource_plan_form(resource)
        else:
            resource_html='<p>Подробный собственный inventory/control prefix для этого аккаунта не предоставлен. Активация в журнале не заменяет проверку выполнимости альтернатив.</p>'
        detail=(f"<article class='card' id='{ident}'><h3>{_time(row['observation_time'])} · {html.escape(item_label)}</h3>"
            "<p class='status'>Недостаточно данных для оценки решения</p>"
            "<p>В боевом логе наблюдается активация. Она не доказывает, когда игрок выбрал действие и что он видел.</p>"
            +clip_card_html(clip_receipts[card.episode_id])+
            f"<button type='button' data-map-time='{row['observation_time'] if row['observation_time'] is not None else ''}'>Показать время на карте</button>"
            f"<details><summary>Решение → доказательства → альтернативы → следующая проверка</summary><p>Предшествующий собственный срез: {_time(row['own_state_time'])}. {state}</p><p>Источник среза: stream prefix record {row['own_state_source_record_index'] if row['own_state_source_record_index'] is not None else 'неизвестен'}. Доступность на экране и точность полей не подтверждены.</p>"
            "<h4>Возможные цели — гипотезы</h4><ul>"+"".join(f"<li>{html.escape(g)}</li>" for g in row["goals"])+"</ul>"
            "<div class='table-scroll'><table><thead><tr><th>Действие</th><th>Доступность</th><th>За</th><th>Цена и риск</th></tr></thead><tbody>"+alternatives+"</tbody></table></div>"
            +resource_html+
            "<h4>Неизвестно</h4><ul>"+"".join(f"<li>{html.escape(u)}</li>" for u in row["unknowns"])+"</ul>"
            f"<p>Источник: record_index {row['source_record_index']}; trace SHA-256 <code>{row['source_trace_hash']}</code>. <a href='observed-actions.json'>Боевые наблюдения</a></p>"
            "<p>Следующая проверка: перед активацией назовите действие, которое защищаете, и угрозу его прерывания. В записи проверьте сигнал и доступные альтернативы. Это вопрос для самостоятельного разбора, а не назначенное лечение ошибки.</p></details>"
            f"<details><summary>Наблюдаемый результат — отдельно от оценки</summary><p>События боевого лога с участием героя за следующие 10 секунд. Это окно просмотра, а не критерий качества выбора. Отсутствие записи смерти не доказывает выживание.</p><ul>{outcomes if outcomes else '<li>Связанных наблюдений в этом окне нет; результат неизвестен.</li>'}</ul></details>{feedback_controls(card)}</article>")
        parts.append(detail if i<4 else f"<details><summary>Ещё активация: {_time(row['observation_time'])} · {html.escape(item_label)}</summary>{detail}</details>")
    payload={"schema_version":"foresight.trace-review.v1","match_id":result.replay.match_id,
        "account_id":account_id,"dataset_kind":result.replay.manifest.dataset_kind,"identity_join":"source_hero_id_to_Valve_name_resource_slot_unverified",
        "catalog_snapshot_id":catalog.snapshot_id,"notebook":notebook,
        "cards":[asdict(c) for c in cards],"extensions":ext_payload,
        "source_match_hash":content_hash(raw_match),"study":study_payload,
        "build_advice":asdict(build_advice) if build_advice else None,
        "review_pack":review_pack,
        "observed_outcomes":observed_outcomes,"clip_navigation":clip_navigation,
        "profile":profile,"resource_reviews":resource_reviews,"semantic_events":semantics,
        "semantic_lifecycles":lifecycles,"resource_opportunities":resource_opportunities,"ward_observations":ward_observations,
        "objective_state":objective_state,
        "ward_analysis":ward_analysis,
        "choice_windows":choice_windows,
        "unit_control":unit_control,"replay_sources":replay_sources,"mechanics":mechanics,"movement_support":movement,
        "defensive_impact":defensive_impact,
        "impact_prefix":impact_prefix,"case_assessment":case_assessment,
        "terrain_support":terrain_support,"verified_history":verified_history,
        "quality":{"extraction":"not_client_validated","decision":"not_expert_validated",
            "explanation":"deterministic_observation_templates","usefulness":"not_measured","behavior_change":"not_measured"}}
    (out/"analysis.json").write_text(_safe_json(payload),encoding="utf-8")
    timeline=" · ".join(f"<a href='#{html.escape(c.episode_id,quote=True)}'>{_time(c.dossier.observation['observation_time'])}</a>" for c in cards)
    page=f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='icon' href='data:,'>
<title>Foresight · {result.replay.match_id}</title><style>
body{{font:16px system-ui;line-height:1.55;max-width:1080px;margin:30px auto;padding:0 20px;background:#101922;color:#e2edf5}}h1,h2,h3{{color:#f2f7fb}}a{{color:#94c9ff}}nav{{position:sticky;top:0;background:#101922;padding:14px 0;z-index:1}}section{{margin:26px 0}}.card,.coverage{{padding:20px;border:1px solid #34495c;background:#192936;border-radius:12px;margin:18px 0;scroll-margin-top:80px}}.status{{color:#efd39a}}details{{margin:12px 0}}summary{{cursor:pointer;color:#9fcbec}}code{{overflow-wrap:anywhere}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;vertical-align:top;border-bottom:1px solid #3b4b5a;text-align:left}}.table-scroll{{overflow:auto}}button{{padding:9px 13px;background:#294e6b;color:white;border:1px solid #6088a5;border-radius:8px;cursor:pointer}}textarea{{width:100%;box-sizing:border-box;display:block;background:#101d28;color:white;border:1px solid #58758b;padding:10px;margin:8px 0}}@media(max-width:600px){{body{{padding:0 12px;margin:16px auto}}nav{{position:static}}.card{{padding:12px}}table{{min-width:550px}}}}
</style></head><body><h1>Разбор наблюдаемых активаций</h1><p>Матч {result.replay.match_id} · {html.escape(hero.label)} · account {account_id}</p>
<div class='coverage'><b>{'Реальный публичный replay. Это проверка системы на публичном матче, а не история пользователя.' if result.replay.manifest.dataset_kind=='replay' else 'Синтетический пример: это не анализ реальной игры.' if result.replay.manifest.dataset_kind=='synthetic' else 'Происхождение replay не установлено; реальные игровые выводы недоступны.'}</b>
<p>Активаций для разбора: {notebook['activation_candidates']}. Оценено решений: 0. Возможности не нажать предмет ещё не установлены; охват выбора неизвестен.</p>
<p>Точность replay-извлечения требует просмотра в клиенте. Эпизоды показывают наблюдения, гипотезы цели и предмет проверки, не обвинение игрока.</p>
<a href='analysis.json'>Полный отчёт</a> · <a href='trace-audit.json'>Проверка извлечения</a> · <a href='source-match.json'>Данные OpenDota</a></div>
<nav><a href='#activations'>Активации</a> · <a href='#wards'>Карта</a> · <a href='#builds'>Предметы</a> · <a href='#study'>Учебные матчи</a> · <a href='#habits'>Привычки</a></nav>
<section id='activations'><h2>Таймлайн</h2><p>{timeline}</p>{''.join(parts) if parts else '<p>Идентифицированных защитных активаций нет. Это не означает, что они отсутствовали или игрок не ошибался.</p>'}</section>
{extensions}{build_html}{profile_html}{feedback_script(result.replay.match_id,cards)}
<script>document.querySelectorAll('[data-map-time]').forEach(b=>b.addEventListener('click',()=>{{const s=document.getElementById('ward-time');if(s&&b.dataset.mapTime!==''&&Number.isFinite(Number(b.dataset.mapTime))){{s.value=b.dataset.mapTime;s.dispatchEvent(new Event('input'));document.getElementById('wards').scrollIntoView();}}}}));document.querySelectorAll("a[href^='#']").forEach(a=>a.addEventListener('click',()=>{{let el=document.getElementById(a.hash.slice(1));for(let p=el;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;}}));</script></body></html>"""
    from dota_coach.semantic_surface import semantic_section,static_semantic_script
    from dota_coach.semantic_surface import lifecycle_section,resource_opportunity_section
    from dota_coach.analytics_surface import objective_state_section,ward_analysis_section,choice_window_section,replay_source_section,projectile_source_section,unit_control_section,mechanics_section,movement_section,defensive_impact_section
    from dota_coach.analytical_bundle import case_section,terrain_section,history_section
    from dota_coach.learning.build_plan_surface import render_build_plan_form
    from dota_coach.learning.ward_plan_surface import render_ward_plan_form
    planning_form=render_build_plan_form(payload,catalog)
    if build_html:
        page=page.replace(build_html,planning_form+"<details><summary>Предметы и источники исходного исследовательского вопроса</summary>"+build_html+"</details>")
    else:
        page=page.replace('</body>',planning_form+'</body>')
    page=page.replace("<section id='activations'>",replay_source_section(replay_sources)+projectile_source_section(replay_sources.get('projectiles'))+unit_control_section(unit_control)+mechanics_section(mechanics)+movement_section(movement)+defensive_impact_section(defensive_impact)+case_section(case_assessment)+terrain_section(terrain_support)+history_section(verified_history)+semantic_section(semantics)+lifecycle_section(lifecycles)+objective_state_section(objective_state)+resource_opportunity_section(resource_opportunities)+choice_window_section(choice_windows)+"<section id='activations'>")
    page=page.replace('</body>',ward_analysis_section(ward_analysis)+render_ward_plan_form(ward_observations)+'</body>')
    page=page.replace("<a href='#wards'>Карта</a>","<a href='#wards'>Карта</a> · <a href='#ward-plan'>Задача варда</a>")
    page=page.replace("<a href='#builds'>Предметы</a>","<a href='#build-plan'>План покупки</a> · <a href='#builds'>История покупок</a>")
    page=page.replace("<nav><a href='#activations'>","<nav><a href='#semantic-events'>События</a> · <a href='#activations'>")
    page=page.replace("<a href='analysis.json'>Полный отчёт</a>","<a href='independent-review/blinded/index.html'>Слепая экспертная проверка</a> · <a href='analysis.json'>Полный отчёт</a>")
    page=page.replace('</head>',"<style>body{overflow-wrap:anywhere}.resource-plan label{display:block;margin:10px 0}.resource-plan input:not([type=checkbox]){display:block;box-sizing:border-box;width:100%;max-width:420px;padding:9px;background:#101d28;color:white;border:1px solid #58758b;border-radius:5px}</style></head>")
    page=page.replace('</body>',static_semantic_script()+'</body>')
    from dota_coach.learning.resource_plan import static_resource_plan_script
    page=page.replace('</body>',static_resource_plan_script()+'</body>')
    (out/"index.html").write_text(page,encoding="utf-8")
    if witness_sink is not None:
        witness_sink(workflow,history_witness)
    return payload
