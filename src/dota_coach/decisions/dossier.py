from __future__ import annotations

from dataclasses import dataclass

from dota_coach.decisions.contracts import ActionCandidate, Assessment, DecisionBoundary
from dota_coach.evidence.contracts import ReplayManifest, content_hash
from dota_coach.evidence.knowledge import KnowledgeSnapshot, project_knowledge
from dota_coach.models import ParsedReplay

REASON_RU = {
    "decision_boundary_unresolved": "Момент выбора не установлен; время события его не заменяет.",
    "replay_unavailable": "Реплей недоступен; состояние и действия не проверены.",
    "extraction_unverified": "Извлечение пока не сверено с реальным replay и клиентом.",
    "exact_visibility_unavailable": "Точная наблюдаемость угрозы не извлечена.",
    "inventory_abilities_unavailable": "Нет проверенных предметов, способностей и ограничений применения.",
    "cast_control_events_unavailable": "Нет проверенного журнала кастов, контроля и попыток команд.",
    "reaction_cue_unavailable": "Не подтверждено, какой сигнал был своевременно доступен игроку.",
    "criterion_not_validated": "Критерий оценки ещё не прошёл независимую проверку.",
}


@dataclass(frozen=True)
class DecisionDossier:
    dossier_id: str
    incident_time: float
    boundary: DecisionBoundary
    assessment: Assessment
    snapshot: KnowledgeSnapshot | None
    alternatives: tuple[ActionCandidate, ...]
    raw_artifact_hash: str | None
    manifest: ReplayManifest | None
    perspective: str = "retrospective_incident"


def build_dossier(episode_id: str, parsed: ParsedReplay | None,
                  incident_time: float, my_slot: int) -> DecisionDossier:
    # This is incident navigation. Never convert death/t-N into a decision.
    boundary = DecisionBoundary(f"{episode_id}:boundary", None)
    snapshot = project_knowledge(parsed, incident_time, my_slot) if parsed else None
    reasons = ["decision_boundary_unresolved", "criterion_not_validated"]
    if parsed is None:
        reasons.append("replay_unavailable")
    else:
        reasons.append("extraction_unverified")
        manifest = parsed.manifest
        for capability, reason in (
            ("exact_team_visibility", "exact_visibility_unavailable"),
            ("inventory_abilities", "inventory_abilities_unavailable"),
            ("cast_control_events", "cast_control_events_unavailable"),
            ("reaction_cue_available_to_subject", "reaction_cue_unavailable"),
        ):
            if manifest is None or not manifest.supports(capability):
                reasons.append(reason)
    assessment = Assessment(f"assessment:{content_hash((episode_id, tuple(reasons)))}",
                            reason_codes=tuple(reasons))
    return DecisionDossier(
        f"dossier:{episode_id}", incident_time, boundary, assessment, snapshot,
        (ActionCandidate("activate_defense", "Применить защитный ресурс",
                         unknown_requirements=("timing", "availability", "threat", "goal")),
         ActionCandidate("preserve_resource", "Не применять ресурс в рассматриваемом окне",
                         unknown_requirements=("choice_window", "goal", "competing_actions"))),
        parsed.manifest.replay_hash if parsed and parsed.manifest else None,
        parsed.manifest if parsed else None)
