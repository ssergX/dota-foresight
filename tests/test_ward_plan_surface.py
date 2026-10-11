"""The ward UI preserves source binding and unconfirmed user hypotheses."""
from html.parser import HTMLParser
import json
import re

import pytest

from dota_coach.learning.ward_plan import ward_source_context
from dota_coach.learning.ward_plan_surface import render_ward_plan_form,attach_ward_plan_submission
from dota_coach.models import WardEvent
from dota_coach.wards import render_ward_map
from tests.test_ward_plan import observations,ward_trace,callback


class Elements(HTMLParser):
    def __init__(self,page):
        super().__init__();self.tags=[];self.feed(page)
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))


def data(page):
    match=re.search(r"id='ward-plan-data'>(.*?)</script>",page,re.S)
    assert match
    return json.loads(match.group(1))


def test_form_only_selects_placements_with_bound_source_context():
    source=observations();page=render_ward_plan_form(source)
    choices=data(page)
    assert len(choices)==3
    for choice in choices:
        assert choice['source_context_hash']==ward_source_context(source,choice['ward_id'])['source_context_hash']
    assert not any(':record:30' in choice['ward_id'] for choice in choices)


def test_goal_and_confirmation_are_blank_without_prior_intent_prefill():
    page=render_ward_plan_form(observations());elements=Elements(page)
    confirmed=next(a for tag,a in elements.tags if tag=='input' and a.get('name')=='confirmed')
    assert 'checked' not in confirmed
    goal=next(a for tag,a in elements.tags if tag=='select' and a.get('name')=='goal_kind')
    assert 'value' not in goal
    assert "<option value=''>Выберите задачу" in page
    assert "goal_description').value=" not in page
    assert "if(!f.namedItem('confirmed').checked)throw Error" in page
    assert 'цель прошлой постановки' in page


def test_unavailable_subject_placements_are_not_reported_as_no_wards():
    source=observations(ward_trace([callback(10,100,team=3)]))
    page=render_ward_plan_form(source)
    assert data(page)==[]
    assert 'Это не отсутствие вардов в игре' in page
    assert 'Нет привязанной постановки' in page


def test_unknown_original_clock_is_labelled_and_not_replaced_by_displaytime():
    source=observations(ward_trace([callback(10,100,refs=[])]))
    page=render_ward_plan_form(source)
    assert 'время неизвестно' in data(page)[0]['label']
    assert '9999' not in page


def test_submission_context_cannot_break_json_script_or_inject_markup(tmp_path):
    page='<html><body>'+render_ward_plan_form(observations())+'</body></html>'
    path=tmp_path/'report.html';path.write_text(page,encoding='utf-8')
    marker='</script><img src=x onerror=alert(1)>'
    attach_ward_plan_submission(path,job_id=marker,token=marker)
    saved=path.read_text(encoding='utf-8')
    assert marker not in saved
    context=re.search(r"id='ward-plan-context'>(.*?)</script>",saved,re.S)
    assert json.loads(context.group(1))=={'job_id':marker,'token':marker}
    assert 'node.textContent=String(text)' in saved and '.innerHTML' not in saved


def test_static_report_cannot_submit_to_external_or_absent_backend():
    page=render_ward_plan_form(observations())
    assert "['127.0.0.1','localhost'].includes(location.hostname)" in page
    assert "location.protocol!=='file:'" in page
    assert 'статический отчёт сохраняет наблюдения' in page
    assert "fetch('/api/ward-plan'" in page
    assert "fetch('/api/ward-plan/'+encodeURIComponent(ctx.job_id))" in page
    assert 'if(!supported||!hydrated||busy)return' in page
    assert 'previous_plan_id:last?.plan_id??null' in page


@pytest.mark.parametrize('page,job,token', (
    ('<html><body></body></html>','job','token'),
    ('<html><body>form</body></html>','','token'),
    ('<html><body>form</body></html>','job',''),
))
def test_attachment_requires_complete_form_and_identity(tmp_path,page,job,token):
    path=tmp_path/'report.html';path.write_text(page,encoding='utf-8')
    with pytest.raises(ValueError):attach_ward_plan_submission(path,job_id=job,token=token)


def test_duplicate_attachment_is_rejected_without_changing_context(tmp_path):
    path=tmp_path/'report.html'
    path.write_text('<html><body>'+render_ward_plan_form(observations())+'</body></html>',encoding='utf-8')
    attach_ward_plan_submission(path,job_id='one',token='first')
    saved=path.read_text(encoding='utf-8')
    with pytest.raises(ValueError):attach_ward_plan_submission(path,job_id='two',token='second')
    assert path.read_text(encoding='utf-8')==saved


def test_map_selection_and_keyboard_activation_share_source_ward_identity():
    trace=ward_trace();trace.replay.wards.append(WardEvent(100,1,'obs',2,10,20,'placed'))
    page=render_ward_map(trace.replay)
    assert "new CustomEvent('foresight:ward-selected'" in page
    assert 'entity_id:w.id,generation:w.generation' in page
    assert "setAttribute('role','button')" in page and "setAttribute('tabindex','0')" in page
    assert re.search(r"\.key\s*===\s*'Enter'",page)
    assert re.search(r"\.key\s*===\s*' '",page)
    form=render_ward_plan_form(observations())
    assert "document.addEventListener('foresight:ward-selected'" in form
    assert 'e.entity_id===event.detail.entity_id&&e.generation===event.detail.generation' in form
    assert "form.elements.namedItem('confirmed').checked=false" in form


def test_result_rendering_calls_unknowns_out_without_claiming_behavior_change():
    page=render_ward_plan_form(observations())
    assert 'Изменение плана не измеряет прогресс поведения' in page
    assert 'не доказывают активный обзор или дублирование' in page
    assert 'Доступность и безопасность неизвестны' in page
    assert 'overflow-wrap:anywhere' in page and 'max-width:100%' in page
