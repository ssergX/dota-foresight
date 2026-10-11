"""Activation observations from real replay, without treating them as choices.

This is an observation notebook, not a replacement for a validated feasibility
or attention extractor. Its projection deliberately accepts neither outcomes
nor opponents. Candidate discovery counts the full supplied action stream.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult

DEFENSIVE_ITEMS = frozenset(("item_black_king_bar", "item_manta", "item_cyclone",
    "item_wind_waker", "item_force_staff", "item_hurricane_pike", "item_glimmer_cape",
    "item_ghost", "item_lotus_orb", "item_satanic"))


@dataclass(frozen=True)
class ActivationObservation:
    decision_id: str
    match_id: int
    actor: str
    item: str
    observation_time: float | None
    source_record_index: int
    source_trace_hash: str
    own_state: tuple[tuple[str, int | float | bool | None], ...]
    own_state_time: float | None
    own_state_source_record_index: int | None
    goals: tuple[str, ...]
    alternatives: tuple[tuple[str, str, str, str], ...]
    unknowns: tuple[str, ...]
    verdict: str = "insufficient_evidence"
    boundary_status: str = "activation_observation_choice_unresolved"
    coverage_status: str = "observed_activations_only"
    rubric_version: str = "defensive-activation-notebook.v1"

    @property
    def input_hash(self):
        # The stream's full hash is a provenance link, not an evaluator feature.
        return content_hash({k:v for k,v in asdict(self).items() if k != "source_trace_hash"})


def activation_notebook(result: TraceResult, *, actor: str, resource_slot: int) -> dict:
    if not isinstance(actor, str) or not actor.startswith("npc_dota_hero_"):
        raise ValueError("source-backed canonical hero identity required")
    if type(resource_slot) is not int or not 0 <= resource_slot <= 9:
        raise ValueError("canonical replay resource slot required")
    if result.replay.manifest is None:
        raise ValueError("trace manifest required")
    own_actions = tuple(a for a in result.actions if a.actor == actor)
    candidates = tuple(a for a in own_actions if a.kind == "item" and a.ability_or_item in DEFENSIVE_ITEMS)
    rows = []
    timing={p["frame_time"]:p["prefix_record_index"] for p in result.audit.get("timing_provenance",())}
    # Only the subject's state is projected. Do not pass raw_match or a combat
    # aftermath to this function: that separation is part of the API contract.
    for action in candidates:
        t = action.game_time
        frame = None
        if t is not None and math.isfinite(t):
            # Strictly preceding snapshot, with explicit staleness limit; never
            # take the first later frame, even if it is temporally closer.
            for f in result.replay.frames:
                if f.time >= t:
                    break
                # Delivery can lag the combat timestamp. A retrospectively
                # matching second still cannot import a later stream prefix.
                prefix=timing.get(f.time)
                if t - f.time <= 1.1 and type(prefix) is int and prefix < action.event_record_index:
                    frame = f
        unit = frame.units.get(resource_slot) if frame is not None else None
        state = tuple((key, getattr(unit, key) if unit is not None else None)
                      for key in ("hp", "max_hp", "mana", "level", "alive"))
        unknowns = ["Момент выбора не отделён от команды и эффекта активации.",
            "Нет записи экрана или проверенного сигнала, который устанавливает замеченную игроком угрозу.",
            "Контроль, возможность каста и перемещения для альтернативы не проверены.",
            "Историческая механика предмета и критерий пользы не прошли независимую проверку.",
            "Собственный срез предшествует событию; это не точное состояние на момент выбора."]
        if unit is None:
            unknowns.append("Достаточно свежий собственный срез недоступен.")
        rows.append(ActivationObservation(action.action_id, result.replay.match_id, actor,
            action.ability_or_item, t, action.event_record_index,
            result.audit.get("trace_sha256", result.replay.manifest.replay_hash), state, frame.time if frame else None,
            timing.get(frame.time) if frame else None,
            ("Защитить намеченное действие от прерывания.",
             "Сохранить ресурс для следующей угрозы.",
             "Отойти или создать пространство союзнику; намерение не наблюдалось."),
            (("Активировать", "наблюдается в combat log", "Может защитить намеченное действие, если механика предмета отвечает доступной угрозе.",
              "Расходует активный ресурс; его ценность и цена относительно следующего окна зависят от непроверенного контекста."),
             ("Удержать ресурс", "выполнимость неизвестна", "Сохраняет активный ресурс, если угрозу можно обработать иначе.",
              "Может оставить действие уязвимым к прерыванию; альтернативный исход не установлен.")),
            tuple(unknowns)))
    return {"schema_version": "foresight.activation-notebook.v1",
        "match_id": result.replay.match_id, "actor": actor, "resource_slot": resource_slot,
        "dataset_kind": result.replay.manifest.dataset_kind,
        "coverage_status": "observed_activations_only",
        "supplied_combat_actions": len(result.actions), "resolved_own_actions": len(own_actions),
        "activation_candidates": len(rows), "assessed_decisions": 0,
        "non_activation_opportunities": None,
        "unknown_actor_actions": sum(a.actor is None for a in result.actions),
        "entries": [asdict(row) | {"input_hash": row.input_hash} for row in rows],
        "next_check": "Перед следующей активацией назови действие, которое защищаешь, и угрозу прерывания. В записи игрока проверь сигнал и выполнимые альтернативы.",
        "exercise_status": "optional_self_review_not_confirmed_habit",
        "limitations": ["An observed cast does not establish the earlier choice boundary.",
            "Non-activation opportunities, successful choices and unpunished errors require a verified cue/feasibility extractor.",
            "No absence of mistakes or numerical confidence is inferred from abstention."]}
