from dota_coach.analytics_surface import objective_state_section
from dota_coach.ingest.objective_state import build_objective_state
from tests.test_semantic_lifecycle import marker, report
from tests.test_semantic_surface import semantic_workbench


def test_command_binding_surface_keeps_raw_references_distinct_from_casts():
    from dota_coach.analytics_surface import replay_source_section
    page = replay_source_section({'orders':None,'constraints':None,'event_visibility':None,
        'command_binding':{'association_counts':{'raw_ability_index_link_association':1314},
                           'linked_class_counts':{'CDOTA_Item_Black_King_Bar':38}}})
    assert 'Сообщений со ссылкой на объект BKB: 38.' in page
    assert 'эти потоки описывают разные события.</p>' in page
    assert page.count('<p>') == page.count('</p>')


def test_objective_surface_escapes_source_names_and_preserves_unknown_ownership():
    payload = report(marker(2, 'buyback_observed', actor='<img src=x onerror=alert(1)>'))
    result = build_objective_state(payload)
    page = objective_state_section(result)
    assert '<img src=x' not in page and '&lt;img' in page
    assert 'Владелец и доступность игроку неизвестны' in page
    assert 'не задаёт время возрождения' in page
    assert 'objective-state.json' in page


def test_objective_api_prefix_is_bound_and_future_marker_cannot_change_it(semantic_workbench):
    from dota_coach.evidence.contracts import content_hash
    work, ident, source, save = semantic_workbench
    source['lanes']['combat_names'].insert(0, marker(1, 'buyback_observed'))
    save()
    first = work.semantic_prefix(ident, 'combat_names', 4)
    objective = first['objective_prefix']
    assert len(objective['lanes']['combat_names']['objects']) == 1
    assert objective['prefix_sha256'] == content_hash({k:v for k,v in objective.items() if k!='prefix_sha256'})
    source['lanes']['combat_names'].append({'source_record_index':999,'future_state':'hidden'})
    save()
    assert work.semantic_prefix(ident, 'combat_names', 4) == first
