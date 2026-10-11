from dataclasses import asdict
import json

import pytest

from dota_coach.cli import main
from tests.test_terrain import fixture


def proposal():
    scope, model, _ = fixture()
    return {'schema_version':'foresight.terrain-input.v1', 'scope':asdict(scope), 'model':asdict(model),
        'blockers':[], 'queries':[{'query_id':'<script>bad()</script>', 'x':1,'y':1,'radius':20,'observer_height_offset':0}]}


def test_cli_conditional_geometry_source_link_and_escaped_html(tmp_path):
    source=tmp_path/'input.json';source.write_text(json.dumps(proposal()),encoding='utf-8')
    out=tmp_path/'geometry.json';page=tmp_path/'index.html'
    assert main(['terrain-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['candidate_geometry'] is not None and result['status']=='unknown'
    assert not result['actual_game_vision_established'] and not result['ward_utility_established']
    text=page.read_text(encoding='utf-8')
    assert '<svg ' in text and '<script>bad()</script>' not in text
    assert 'href="geometry.json"' in text and 'Фактический обзор Dota' in text


@pytest.mark.parametrize('overlap',['json-input','html-input','same-output','foreign-directory'])
def test_cli_protects_inputs_and_adjacent_outputs(tmp_path,overlap):
    source=tmp_path/'input.json';source.write_text(json.dumps(proposal()),encoding='utf-8');before=source.read_bytes()
    out=tmp_path/'geometry.json';page=tmp_path/'index.html'
    if overlap=='json-input':out=source
    if overlap=='html-input':page=source
    if overlap=='same-output':page=out
    if overlap=='foreign-directory':page=tmp_path/'other/index.html'
    assert main(['terrain-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==1
    assert source.read_bytes()==before and not (tmp_path/'geometry.json').exists()
