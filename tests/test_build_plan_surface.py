"""Form safety, source binding and explicit unknown/default user declarations."""
from dataclasses import replace
from html.parser import HTMLParser
import json
import re

import pytest

from dota_coach.learning.build_plan_surface import (
    attach_build_plan_submission, render_build_plan_form,
)
from tests.test_contextual_builds import catalog
from tests.test_live_report import sources


class Elements(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.tags = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def report(tmp_path):
    from dota_coach.live_report import render_live_report
    trace, raw = sources()
    payload = render_live_report(trace, raw, account_id=7, catalog=catalog(), out_dir=tmp_path)
    for row in payload['notebook']['entries']:
        row['decision_id'] = f"trace:{payload['match_id']}:record:{row['source_record_index']}"
    # Report artifacts crossing the frontend boundary are JSON values.
    return json.loads(json.dumps(payload))


def data(page):
    match = re.search(r"id='build-plan-data'>(.*?)</script>", page, re.S)
    assert match
    return json.loads(match.group(1))


def test_form_source_anchors_and_current_catalog_are_bound(tmp_path):
    from dota_coach.learning.build_planner import build_source_context
    payload = report(tmp_path)
    page = render_build_plan_form(payload, catalog())
    context = data(page)
    expected = [entry['decision_id'] for entry in payload['notebook']['entries']]
    assert context['episode_ids'] == expected
    assert context['episodes'][0]['source_context_hash'] == build_source_context(payload, expected[0])['source_context_hash']
    assert {item['item_id'] for item in context['items']} == {
        item.internal_name for item in catalog().items if item.detail_status == 'descriptor_available'}


def test_user_goal_money_and_confirmation_start_empty(tmp_path):
    page = render_build_plan_form(report(tmp_path), catalog())
    elements = Elements(page)
    inputs = [attrs for tag, attrs in elements.tags if tag == 'input']
    assert all('value' not in attrs for attrs in inputs)
    confirmed = next(attrs for attrs in inputs if attrs.get('name') == 'confirmed')
    assert 'checked' not in confirmed
    assert "name='goal_kind' required><option value=''>" in page
    assert "name='threat_kind'><option value='unknown'>" in page
    assert "name='free_inventory_slot'><option value='unknown'>" in page
    assert "name='purchase_available'><option value='unknown'>" in page
    assert "if(input.value.trim()==='')return null" in page
    assert "cost.value=" not in page


def test_synthetic_public_episode_is_not_a_personal_goal(tmp_path):
    payload = report(tmp_path)
    payload['dataset_kind'] = 'synthetic'
    payload['notebook']['dataset_kind'] = 'synthetic'
    page = render_build_plan_form(payload, catalog())
    assert 'Синтетический пример' in page
    assert 'не является историей пользователя' in page
    assert 'не доказывает намерение игрока в прошлом' in page
    assert "confirmed:true" in page  # only after explicit checked guard
    assert "if(!fields.namedItem('confirmed').checked)throw Error" in page


def test_catalog_markup_cannot_become_html_or_inline_javascript(tmp_path):
    snapshot = catalog()
    marker = "</script><img src=x onerror=window.compromised=true>"
    changed = replace(snapshot, items=tuple(replace(item, label=marker, description=marker)
                                            for item in snapshot.items))
    page = render_build_plan_form(report(tmp_path), changed)
    assert marker not in page
    assert all(item['label'] == marker for item in data(page)['items'])
    assert 'node.textContent=String(text)' in page
    assert '.innerHTML' not in page
    assert 'document.createTextNode' in page


def test_no_foreign_catalog_urls_are_embedded_in_form(tmp_path):
    page = render_build_plan_form(report(tmp_path), catalog())
    assert all('source_url' not in item for item in data(page)['items'])
    assert "url.protocol==='https:'" in page
    assert "['www.dota2.com','dota2.com'].includes(url.hostname)" in page
    assert '!url.username&&!url.password' in page
    assert "url.port==='443'" in page
    assert "a.rel='noopener noreferrer'" in page


def test_empty_anchors_and_catalog_offer_no_comparison(tmp_path):
    payload = report(tmp_path)
    payload['notebook']['entries'] = []
    snapshot = replace(catalog(), items=tuple(replace(item, detail_status='list_entry_only')
                                               for item in catalog().items))
    page = render_build_plan_form(payload, snapshot)
    assert data(page)['episode_ids'] == [] and data(page)['items'] == []
    assert 'Нет эпизодов для привязки' in page
    assert 'В каталоге нет описаний предметов' in page
    assert 'submit.disabled=true' in page


def test_submission_context_is_safe_and_fixed_to_local_backend(tmp_path):
    payload = report(tmp_path)
    page = '<html><body>' + render_build_plan_form(payload, catalog()) + '</body></html>'
    path = tmp_path / 'safe.html'
    path.write_text(page, encoding='utf-8')
    marker = '</script><script>throw Error("injected")</script>'
    attach_build_plan_submission(path, marker, marker)
    saved = path.read_text(encoding='utf-8')
    assert marker not in saved
    assert "fetch('/api/build-plan'" in saved
    assert "fetch('/api/build-plan/'+encodeURIComponent(ctx.job_id)" in saved
    assert "location.protocol!=='file:'" in saved
    assert "['127.0.0.1','localhost'].includes(location.hostname)" in saved
    assert "if(!supported)" in saved
    with pytest.raises(ValueError, match='already attached'):
        attach_build_plan_submission(path, 'job', 'token')


def test_attachment_requires_complete_form_and_nonempty_identity(tmp_path):
    path = tmp_path / 'bad.html'
    path.write_text('<html><body></body></html>', encoding='utf-8')
    with pytest.raises(ValueError, match='form'):
        attach_build_plan_submission(path, 'job', 'token')
    with pytest.raises(ValueError, match='nonempty'):
        attach_build_plan_submission(path, '', 'token')


def test_mobile_layout_and_revision_state_do_not_autofill_new_goal(tmp_path):
    page = render_build_plan_form(report(tmp_path), catalog())
    assert 'overflow-wrap:anywhere' in page
    assert 'minmax(min(240px,100%),1fr)' in page
    assert 'max-width:100%' in page
    assert 'previousPlanId=lastResult.plan_id' in page
    assert 'previousPlanId=plan.plan_id' in page
    assert 'previous_plan_id:previousPlanId' in page
    assert "goal_description').value=" not in page
    assert "confirmed').checked=" not in page
    assert "selected.size>=6" in page
    assert 'source_context_hash:data.episodes.find' in page
    assert "download='build-plan.json'" in page


def test_legacy_or_conflicting_anchors_are_not_submitted(tmp_path):
    payload = report(tmp_path)
    payload['notebook']['entries'][0]['decision_id'] = 'legacy-a1'
    page = render_build_plan_form(payload, catalog())
    assert data(page)['episode_ids'] == []
    assert 'Нет эпизодов для привязки' in page
    assert 'сравнение недоступно' in page


def test_amount_comparison_and_revision_are_not_behavior_or_utility_ranking(tmp_path):
    page = render_build_plan_form(report(tmp_path), catalog())
    assert 'Разница полезности не установлена; ранжирования нет' in page
    assert 'изменение не измеряет улучшение поведения' in page
    assert 'доступность покупки и применения: не установлена' in page
    assert 'По указанным вами числам' in page
    assert 'scenario_planning_not_behavior_progress' in page
    assert 'plan.source_binding?.decision_id' in page
    assert 'if(submitting||!hydrated)return' in page
