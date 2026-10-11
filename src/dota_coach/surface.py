"""Small report surfaces over provenance-preserving APIs."""
from __future__ import annotations

from dataclasses import asdict
import html
import json

from dota_coach.evidence.contracts import content_hash
from dota_coach.learning.portfolio import build_descriptive_portfolio
from dota_coach.learning.study import select_study_matches
from dota_coach.wards import render_ward_map


def context_sections(raw_match: dict | None, account_id: int | None, parsed=None,
                     catalog=()) -> tuple[str, dict]:
    payload = {"ward_analysis": {"status": "retrospective_observations" if parsed and parsed.wards else "unavailable",
                                  "vision_geometry": "unverified", "utility": "not_established"}}
    body = render_ward_map(parsed)
    missing = ("<section id='builds'><h2>Предметы</h2><p>Контекст предметов недоступен.</p></section>"
               "<section id='study'><h2>Матчи для изучения</h2><p>Подтверждённые кандидаты недоступны.</p></section>"
               "<section id='habits'><h2>Привычки</h2><p>Проверенных оценок недостаточно.</p></section>")
    if raw_match is None or account_id is None:
        return body + missing, payload
    try:
        portfolio = build_descriptive_portfolio(raw_match, account_id)
    except (TypeError, ValueError, KeyError):
        payload["portfolio"] = {"status": "unavailable", "reason_codes": ["context_source_invalid"]}
        return body + missing, payload
    payload["portfolio"] = asdict(portfolio)
    purchases = "".join(f"<tr><td>{html.escape(p.item_id)}</td>"
        f"<td>{p.game_time_seconds if p.game_time_seconds is not None else 'неизвестно'}</td>"
        f"<td><code>{html.escape(p.source_event_id)}</code></td></tr>" for p in portfolio.purchases.purchases)
    body += f"""<section id='builds'><h2>Предметы и контекст</h2>
<p>Герой ID: {portfolio.hero_id if portfolio.hero_id is not None else 'неизвестен'}.
Роль не подтверждена. Патч: {html.escape(portfolio.patch)} — это идентификатор источника, не проверенная механика.</p>
<p>Покупки описывают матч. Оценка оптимальности и контекстная рекомендация пока недоступны.</p>
<details><summary>Наблюдаемая последовательность покупок ({len(portfolio.purchases.purchases)})</summary>
<table><thead><tr><th>Предмет</th><th>Время, s</th><th>Источник</th></tr></thead><tbody>{purchases}</tbody></table>
{'<p>Журнал покупок не предоставлен.</p>' if not portfolio.purchases.purchases else ''}</details></section>"""
    selection = select_study_matches(tuple(catalog), hero_id=portfolio.hero_id,
        role=portfolio.role, patch=portfolio.patch) if portfolio.hero_id is not None else None
    payload["study_selection"] = asdict(selection) if selection else {"status": "unavailable", "reason_codes": ["hero_unknown"]}
    exclusions = "".join(f"<li>Матч {mid}: {html.escape(', '.join(reasons))}</li>"
                          for mid, reasons in selection.exclusions) if selection else ""
    body += f"""<section id='study'><h2>Матчи для изучения</h2>
<p>Подходящие учебные матчи с проверенными источниками, ролью, патчем и эпизодами пока недоступны.</p>
{'<details><summary>Почему кандидаты не допущены</summary><ul>'+exclusions+'</ul></details>' if exclusions else ''}
<p>Совпадение героя и роли само по себе не доказывает сходство стиля или переносимость решения.</p></section>
<section id='habits'><h2>Привычки и следующая проверка</h2>
<p>Повторяющаяся ошибка не установлена: нет полного учёта возможностей и подтверждённых оценок.
Упражнение по этим данным не назначается. Сравнение периодов станет доступно после независимой проверки критерия.</p></section>"""
    return body, payload


def feedback_controls(card) -> str:
    if card.dossier is None:
        return ""
    identity = html.escape(card.episode_id, quote=True)
    return (f"<div class='feedback' data-id='{identity}'><p>Обратная связь по этому эпизоду</p>"
            f"<label for='comment-{identity}'>Цель или уточнение (до 2000 символов)</label>"
            f"<textarea id='comment-{identity}' maxlength='2000' rows='2'></textarea>"
            "<div><button type='button' data-kind='disagree'>Не согласен</button> "
            "<button type='button' data-kind='different_goal'>Цель была другая</button> "
            "<button type='button' data-kind='useful'>Совет полезен</button></div>"
            "<p class='feedback-status' aria-live='polite'></p></div>")


def feedback_script(match_id: int, cards) -> str:
    hashes = {c.episode_id: c.dossier.assessment.assessment_hash for c in cards if c.dossier}
    contexts = {c.episode_id: content_hash(c.dossier) for c in cards if c.dossier}
    payload = json.dumps({"match_id": match_id, "hashes": hashes, "contexts": contexts}, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<section id='feedback-export'><h2>Ваши отметки</h2>
<p>Отметки остаются в этом браузере и доступны для экспорта. Это материал для проверки, а не экспертный эталон.
Если браузер запрещает локальное хранение, экспорт доступен до закрытия страницы.</p>
<button type='button' id='export-feedback'>Скачать обратную связь JSON</button><p id='export-status' aria-live='polite'></p></section>
<script type='application/json' id='feedback-context'>{payload}</script>
<script>(()=>{{const ctx=JSON.parse(document.getElementById('feedback-context').textContent);
 const key='foresight.feedback.v1:'+ctx.match_id+':'+JSON.stringify(ctx.contexts);let rows=[];
 try{{const saved=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(saved))rows=saved;}}catch(e){{}}
 const status=document.getElementById('export-status');
 document.querySelectorAll('.feedback').forEach(box=>{{box.querySelectorAll('button[data-kind]').forEach(button=>{{
 button.addEventListener('click',()=>{{const id=box.dataset.id,comment=box.querySelector('textarea').value.slice(0,2000);
 rows.push({{schema_version:'foresight.feedback.v1',match_id:ctx.match_id,decision_id:id,
 assessment_hash:ctx.hashes[id],context_hash:ctx.contexts[id],kind:button.dataset.kind,comment,created_at:new Date().toISOString(),status:'unreviewed'}});
 let persisted=true;try{{localStorage.setItem(key,JSON.stringify(rows));}}catch(e){{persisted=false;}}
 box.querySelector('.feedback-status').textContent=persisted?'Отметка сохранена в браузере.':'Отметка добавлена в текущей странице; скачайте JSON.';
 status.textContent='Всего отметок: '+rows.length;}});}});}});
 document.getElementById('export-feedback').addEventListener('click',()=>{{const blob=new Blob([JSON.stringify(rows,null,2)],{{type:'application/json'}});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='foresight-feedback-'+ctx.match_id+'.json';
 a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status.textContent='Экспортировано отметок: '+rows.length;}});
 }})();</script>"""
