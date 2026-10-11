"""Prefix-scoped build questions and provisional alternatives, not optimal builds."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from dota_coach.evidence.contracts import Fact, TimeRef, content_hash
from dota_coach.ingest.valve_catalog import ValveCatalogSnapshot, primary_url
from dota_coach.learning.builds import PurchaseObservation, PurchaseSequence, describe_purchase_sequence

GOALS = frozenset({"survive_spells", "survive_attacks", "reposition", "protect_ally",
                   "sustain_mana", "accelerate_farm", "initiate", "unknown"})
THREATS = frozenset({"spell_damage", "physical_attacks", "control", "gap_close",
                     "resource_pressure", "unknown"})
GOAL_TEXT = {
    "survive_spells": "Сохранить возможность действовать под наблюдаемыми заклинаниями",
    "survive_attacks": "Пережить наблюдаемые атаки",
    "reposition": "Изменить позицию относительно доступной угрозы",
    "protect_ally": "Помочь конкретному союзнику сохранить возможность действовать",
    "sustain_mana": "Сохранить ресурс для выбранного действия",
    "accelerate_farm": "Увеличить доступ к ресурсам до следующего обязательства",
    "initiate": "Создать проверяемое окно начала действия",
    "unknown": "Уточнить цель следующей покупки",
}
CONTEXT_KEYS = frozenset({"self.available_gold", "self.mana", "self.control_available",
                          "self.free_inventory_slot"})
CONTEXT_PREFIXES = ("self.purchase_available:item_", "self.remaining_cost:item_",
                    "self.required_activation_mana:item_")


def _id(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _strings(values, name):
    if not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"immutable {name} strings required")


@dataclass(frozen=True)
class GoalHypothesis:
    goal_id: str
    kind: str = "unknown"
    description: str = "Цель требует уточнения у игрока."
    origin: str = "research_question"
    revision: int = 1
    previous_goal_id: str | None = None
    feedback_id: str | None = None

    def __post_init__(self):
        _id(self.goal_id, "goal_id")
        _id(self.description, "goal description")
        if self.kind not in GOALS or self.origin not in ("research_question", "user_hypothesis", "user_confirmed"):
            raise ValueError("invalid goal kind or origin")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("positive goal revision required")
        if self.revision > 1 and (not self.previous_goal_id or not self.feedback_id):
            raise ValueError("edited goal requires previous identity and user feedback")


@dataclass(frozen=True)
class GoalFeedback:
    feedback_id: str
    goal_id: str
    selected_kind: str
    description: str
    user_confirmed: bool = True

    def __post_init__(self):
        for value, name in ((self.feedback_id, "feedback id"), (self.goal_id, "goal id"),
                            (self.description, "goal feedback description")):
            _id(value, name)
        if self.selected_kind not in GOALS or type(self.user_confirmed) is not bool:
            raise ValueError("typed user goal feedback required")


def revise_goal(goal: GoalHypothesis, feedback: GoalFeedback) -> GoalHypothesis:
    if not isinstance(goal, GoalHypothesis) or not isinstance(feedback, GoalFeedback) or feedback.goal_id != goal.goal_id:
        raise ValueError("goal feedback identity mismatch")
    return GoalHypothesis(content_hash((goal.goal_id, asdict(feedback), goal.revision + 1)),
                          feedback.selected_kind, feedback.description,
                          "user_confirmed" if feedback.user_confirmed else "user_hypothesis",
                          goal.revision + 1, goal.goal_id, feedback.feedback_id)


@dataclass(frozen=True)
class ThreatEvidence:
    threat_id: str
    kind: str
    fact: Fact

    def __post_init__(self):
        _id(self.threat_id, "threat id")
        if self.kind not in THREATS or not isinstance(self.fact, Fact):
            raise ValueError("typed observed threat required")
        if self.fact.predicate != "observed.threat." + self.kind:
            raise ValueError("enemy world state cannot be relabeled as a threat")
        if self.fact.perspective not in ("team", "screen"):
            raise ValueError("threat requires own/team observation, not world state")
        if self.fact.status not in ("unknown", "conflict") and type(self.fact.value) is not bool:
            raise ValueError("observed threat is boolean or unknown")


@dataclass(frozen=True)
class BuildQuestion:
    question_id: str
    match_id: int
    subject_ref: str
    cutoff: TimeRef
    goal: GoalHypothesis
    match_patch: str | None = None
    hero_id: int | None = None
    role: str | None = None
    threats: tuple[ThreatEvidence, ...] = ()
    context_facts: tuple[Fact, ...] = ()
    purchases: tuple[PurchaseObservation, ...] = ()
    candidate_item_ids: tuple[str, ...] = ()
    freshness_ms: int = 5000

    def __post_init__(self):
        _id(self.question_id, "question id")
        _id(self.subject_ref, "subject ref")
        if type(self.match_id) is not int or self.match_id <= 0 or not isinstance(self.goal, GoalHypothesis):
            raise ValueError("match identity and typed goal required")
        if not isinstance(self.cutoff, TimeRef) or self.cutoff.game_time_ms is None:
            raise ValueError("build question requires a cutoff")
        if type(self.freshness_ms) is not int or self.freshness_ms < 0:
            raise ValueError("nonnegative explicit freshness required")
        for values, cls in ((self.threats, ThreatEvidence), (self.context_facts, Fact), (self.purchases, PurchaseObservation)):
            if not isinstance(values, tuple) or any(not isinstance(v, cls) for v in values):
                raise ValueError("typed immutable build evidence required")
        _strings(self.candidate_item_ids, "candidate item")
        if len(set(self.candidate_item_ids)) != len(self.candidate_item_ids):
            raise ValueError("duplicate build candidate")
        if len({f.predicate for f in self.context_facts}) != len(self.context_facts):
            raise ValueError("duplicate build context predicate")
        if len({t.threat_id for t in self.threats}) != len(self.threats):
            raise ValueError("duplicate threat identity")
        for fact in self.context_facts:
            if fact.predicate not in CONTEXT_KEYS and not fact.predicate.startswith(CONTEXT_PREFIXES):
                raise ValueError("build context predicate outside subject allowlist")
            if fact.perspective != "screen" or fact.subject_ref != self.subject_ref or fact.observer_ref != self.subject_ref:
                raise ValueError("own resource/control facts must be subject scoped")
            boolean = fact.predicate in ("self.control_available", "self.free_inventory_slot") or fact.predicate.startswith("self.purchase_available:")
            if fact.status not in ("unknown", "conflict"):
                if boolean and type(fact.value) is not bool:
                    raise ValueError("purchase/control condition must be boolean")
                if not boolean and (type(fact.value) not in (int, float) or not math.isfinite(fact.value) or fact.value < 0):
                    raise ValueError("own cost/resources must be nonnegative numbers")
        for threat in self.threats:
            if threat.fact.observer_ref != self.subject_ref:
                raise ValueError("team threat must name the actual observation recipient")
        all_facts = self.context_facts + tuple(t.fact for t in self.threats)
        if len({f.fact_id for f in all_facts}) != len(all_facts):
            raise ValueError("duplicate fact identity")
        for fact in all_facts:
            if fact.status not in ("unknown", "conflict") and (fact.available_at is None or
                    fact.available_at.game_time_ms is None or fact.available_at.game_time_ms > self.cutoff.game_time_ms):
                raise ValueError("future or missing availability cannot enter build prefix")
            if fact.valid_at.game_time_ms is not None and fact.valid_at.game_time_ms > self.cutoff.game_time_ms:
                raise ValueError("future validity cannot enter build prefix")
        for purchase in self.purchases:
            if purchase.match_id != self.match_id:
                raise ValueError("purchase match mismatch")
            if purchase.game_time_seconds is None:
                raise ValueError("unknown purchase time cannot enter a build prefix")
            earliest_cutoff = self.cutoff.game_time_ms - (self.cutoff.uncertainty_ms or 0)
            if purchase.game_time_seconds * 1000 >= earliest_cutoff:
                raise ValueError("future purchases or unresolved equal-time purchases cannot explain an earlier build choice")

    @property
    def input_hash(self):
        features = asdict(self)
        # The post-match receipt remains in purchases/report serialization, but
        # its whole-artifact hash and retrieval timestamp are not prefix features.
        # A changed outcome or later purchase must not change the same question's
        # analytical identity. This projection grants no stronger source status.
        for purchase in features["purchases"]:
            source = purchase["source"]
            source.pop("content_sha256")
            source.pop("checked_at")
        return content_hash(features)


@dataclass(frozen=True)
class MechanicMapping:
    mapping_id: str
    item_id: str
    descriptor_hash: str
    source_excerpt: str
    goal_kinds: tuple[str, ...]
    threat_kinds: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    revisit_conditions: tuple[str, ...]

    def __post_init__(self):
        for value, name in ((self.mapping_id, "mapping id"), (self.item_id, "item id"),
                            (self.descriptor_hash, "descriptor hash"), (self.source_excerpt, "source excerpt")):
            _id(value, name)
        for values, name in ((self.goal_kinds, "goal kinds"), (self.threat_kinds, "threat kinds"),
                             (self.tradeoffs, "tradeoffs"), (self.revisit_conditions, "revisit conditions")):
            _strings(values, name)
        if not self.goal_kinds or not set(self.goal_kinds) <= GOALS - {"unknown"}:
            raise ValueError("explicit scoped goals required")
        if not self.threat_kinds or not set(self.threat_kinds) <= THREATS - {"unknown"}:
            raise ValueError("explicit scoped observed threats required")
        if not self.tradeoffs or not self.revisit_conditions:
            raise ValueError("mechanic mapping requires tradeoffs and revisit conditions")


@dataclass(frozen=True)
class PatchMechanicBundle:
    bundle_id: str
    version: str
    patch: str
    snapshot_id: str
    reviewer_id: str
    reviewed_at: str
    patch_source_url: str
    mappings: tuple[MechanicMapping, ...]
    review_status: str = "declared_manual_review"
    validation_status: str = "unverified"

    def __post_init__(self):
        for value, name in ((self.bundle_id, "bundle id"), (self.version, "bundle version"),
                            (self.patch, "patch"), (self.snapshot_id, "snapshot id"),
                            (self.reviewer_id, "reviewer id"), (self.reviewed_at, "review time")):
            _id(value, name)
        if self.patch in ("unknown", "current", "latest") or not primary_url(self.patch_source_url):
            raise ValueError("explicit patch and primary Valve patch source required")
        if datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("review time requires timezone")
        if self.review_status != "declared_manual_review" or self.validation_status != "unverified":
            raise ValueError("manual patch import cannot self-promote validation")
        if not isinstance(self.mappings, tuple) or not self.mappings or any(not isinstance(m, MechanicMapping) for m in self.mappings):
            raise ValueError("immutable reviewed mechanic mappings required")
        if len({m.mapping_id for m in self.mappings}) != len(self.mappings) or len({m.item_id for m in self.mappings}) != len(self.mappings):
            raise ValueError("duplicate mechanic mapping")


def check_patch_bundle(bundle: PatchMechanicBundle, catalog: ValveCatalogSnapshot) -> None:
    if bundle.snapshot_id != catalog.snapshot_id:
        raise ValueError("mechanic patch bundle is bound to a different catalog snapshot")
    for mapping in bundle.mappings:
        item = catalog.item(mapping.item_id)
        if item is None or item.detail_status != "descriptor_available" or item.descriptor_hash != mapping.descriptor_hash:
            raise ValueError("reviewed mechanic descriptor absent, incomplete or changed")
        if mapping.source_excerpt not in item.description and not any(mapping.source_excerpt in note for note in item.notes):
            raise ValueError("mechanic excerpt does not occur in the hashed Valve descriptor")


def load_patch_bundle(path: str | Path, catalog: ValveCatalogSnapshot) -> PatchMechanicBundle:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate patch bundle JSON key")
            result[key] = value
        return result
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    data["mappings"] = tuple(MechanicMapping(**(row | {field: tuple(row[field]) for field in (
        "goal_kinds", "threat_kinds", "tradeoffs", "revisit_conditions")})) for row in data["mappings"])
    bundle = PatchMechanicBundle(**data)
    check_patch_bundle(bundle, catalog)
    return bundle


@dataclass(frozen=True)
class OptionTradeoff:
    option_id: str
    item_id: str | None
    label: str
    status: str
    purchase_observed: bool
    goal_condition: str
    advantages: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    feasibility: str
    feasibility_unknowns: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_urls: tuple[str, ...]
    revisit_conditions: tuple[str, ...]
    source_snapshot_id: str | None = None
    optimality: str = "not_established"


@dataclass(frozen=True)
class BuildAttentionRule:
    rule_id: str
    trigger: str
    check: str
    success_marker: str
    evidence_ids: tuple[str, ...]
    category: str = "planning_attention"
    training_eligible: bool = False


@dataclass(frozen=True)
class BuildAnalysis:
    question_id: str
    input_hash: str
    status: str
    active_goal: GoalHypothesis
    goal_hypotheses: tuple[GoalHypothesis, ...]
    options: tuple[OptionTradeoff, ...]
    purchases: PurchaseSequence
    attention_rule: BuildAttentionRule | None
    research_questions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    patch_applicability: str
    validation_status: str = "unverified"
    optimality: str = "not_established"


def _known(question: BuildQuestion, fact: Fact | None) -> bool:
    if fact is None or fact.status not in ("observed", "derived") or fact.quality_flags or fact.available_at is None:
        return False
    # Status="observed" cannot grant clock ordering or upgrade a legacy field
    # interpretation. Both validity and availability must precede the same
    # explicit cutoff; a well-ordered receipt does not repair another clock.
    def scoped_version(value):
        return (isinstance(value, str) and bool(value.strip()) and
                value.strip().lower() not in ("unknown", "unverified", "legacy", "legacy/unverified") and
                not value.strip().lower().startswith("legacy/"))
    if not scoped_version(fact.method_version):
        return False
    times = (question.cutoff, fact.valid_at, fact.available_at)
    if any(t.order_status != "verified" or not scoped_version(t.clock_mapping_version) for t in times):
        return False
    if (not fact.available_at.definitely_available_before(question.cutoff) or
            not fact.valid_at.definitely_available_before(question.cutoff)):
        return False
    # Require freshness for the entire admitted uncertainty interval.
    age = (question.cutoff.game_time_ms + question.cutoff.uncertainty_ms -
           (fact.valid_at.game_time_ms - fact.valid_at.uncertainty_ms))
    return 0 <= age <= question.freshness_ms


def _feasibility(question, item):
    context = {f.predicate: f for f in question.context_facts}
    keys = ("self.available_gold", f"self.remaining_cost:{item.internal_name}",
            f"self.purchase_available:{item.internal_name}", "self.free_inventory_slot")
    unknowns = tuple("context_unknown:" + key for key in keys if not _known(question, context.get(key)))
    refs = tuple(context[key].fact_id for key in keys if _known(question, context.get(key)))
    if unknowns:
        return "unknown", unknowns, refs
    gold, cost, available, free_slot = (context[key].value for key in keys)
    if not available or cost > gold:
        return "infeasible", (), refs
    if not free_slot:
        return "unknown", ("inventory_delivery_or_component_handling_unknown",), refs
    return "feasible", (), refs


def _goal_hypotheses(question, observed):
    kinds = [question.goal.kind] if question.goal.kind != "unknown" else []
    by_threat = {"spell_damage": "survive_spells", "physical_attacks": "survive_attacks",
                 "control": "reposition", "gap_close": "reposition", "resource_pressure": "sustain_mana"}
    kinds.extend(by_threat[kind] for kind in sorted(observed) if kind in by_threat)
    if not kinds:
        kinds = ["survive_spells", "reposition", "accelerate_farm"]
    hypotheses = [question.goal]
    for kind in dict.fromkeys(kinds):
        if kind != question.goal.kind:
            hypotheses.append(GoalHypothesis(content_hash((question.question_id, kind)), kind,
                                             "Была ли целью: " + GOAL_TEXT[kind] + "?"))
    return tuple(hypotheses)


def analyze_build_question(question: BuildQuestion, catalog: ValveCatalogSnapshot | None = None,
                           bundle: PatchMechanicBundle | None = None, *, limit: int = 6) -> BuildAnalysis:
    if not isinstance(question, BuildQuestion) or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("typed build question and bounded option limit required")
    if catalog is not None and not isinstance(catalog, ValveCatalogSnapshot):
        raise TypeError("typed Valve catalog required")
    if bundle is not None:
        if catalog is None:
            raise ValueError("patch mechanic review requires its source catalog")
        check_patch_bundle(bundle, catalog)
    observed = {t.kind: t for t in question.threats if t.kind != "unknown" and
                _known(question, t.fact) and t.fact.value is True}
    scope_known = (bundle is not None and question.match_patch is not None and
                   question.match_patch not in ("unknown", "current", "latest") and question.match_patch == bundle.patch)
    reasons, research = [], []
    if question.goal.kind == "unknown":
        reasons.append("goal_not_selected")
        research.append("Какая цель была приоритетной до покупки: сохранить действие, помочь союзнику, изменить позицию или получить ресурсы?")
    elif question.goal.origin != "user_confirmed":
        reasons.append("goal_is_hypothesis")
        research.append("Подтверди или измени цель; она влияет на сравнение вариантов и не выводится из смерти или победы.")
    if not observed:
        reasons.append("observed_threat_context_missing_or_stale")
        research.append("Какая конкретная угроза была доступна тебе или команде до покупки? Укажи источник и время, не полный replay после исхода.")
    if catalog is None:
        reasons.append("mechanic_catalog_unavailable")
        research.append("Сверить описание и стоимость выбранного предмета с источником механики соответствующего патча.")
    elif not scope_known:
        reasons.append("historical_patch_compatibility_not_established")
        research.append("Проверить описание предмета для патча этого матча; сегодняшнее описание не доказывает его историческую механику.")
    purchases = describe_purchase_sequence(question.purchases)
    purchased = {"item_" + p.item_id if not p.item_id.startswith("item_") else p.item_id for p in question.purchases}
    mapping_by_item = {catalog.item(m.item_id).internal_name: m for m in bundle.mappings} if bundle else {}
    candidates = ["item_" + name if not name.startswith("item_") else name for name in question.candidate_item_ids]
    candidates += [p.item_id if p.item_id.startswith("item_") else "item_" + p.item_id for p in question.purchases]
    if scope_known:
        candidates += [name for name, mapping in mapping_by_item.items() if question.goal.kind in mapping.goal_kinds
                       and set(mapping.threat_kinds) & set(observed)]
    # Literal descriptor retrieval supplies research candidates only. It never
    # interprets engine flags or ranks items by popularity or win rate.
    if catalog and not candidates:
        terms_by_goal = {"survive_spells": ("magic resistance", "dispel"),
                         "survive_attacks": ("attack", "armor"), "reposition": ("move", "push", "teleport"),
                         "protect_ally": ("ally", "allied"), "sustain_mana": ("mana",),
                         "accelerate_farm": ("cleave", "attack speed"), "initiate": ("blink", "stun")}
        terms = terms_by_goal.get(question.goal.kind, ())
        candidates += [i.internal_name for i in catalog.items if i.detail_status == "descriptor_available"
                       and any(term in i.description.lower() for term in terms)]
    options = []
    for name in dict.fromkeys(candidates):
        if len(options) >= limit:
            break
        item = catalog.item(name) if catalog else None
        mapping = mapping_by_item.get(name)
        conditional = bool(scope_known and mapping and question.goal.kind in mapping.goal_kinds
                           and set(mapping.threat_kinds) & set(observed))
        advantages, tradeoffs, revisit, evidence, urls = [], [], [], [], []
        feasibility, gaps, feasible_refs = _feasibility(question, item) if item and conditional else (
            "unknown", ("patch_scoped_mechanic_or_context_not_established",), ())
        if item:
            evidence.append(item.descriptor_hash)
            urls.append(item.source_url)
        if conditional:
            advantages.append("Если цель и наблюдаемая угроза соответствуют проверяемой привязке, сопоставь эффект из источника: " + mapping.source_excerpt)
            tradeoffs.extend(mapping.tradeoffs)
            revisit.extend(mapping.revisit_conditions)
            evidence.extend(t.fact.fact_id for kind, t in observed.items() if kind in mapping.threat_kinds)
            evidence.extend(feasible_refs)
            urls.append(bundle.patch_source_url)
        else:
            advantages.append("Вопрос для сравнения: решает ли этот предмет выбранную цель в механике патча матча?")
            if item and item.detail_status == "descriptor_available":
                if item.item_cost is not None:
                    tradeoffs.append(f"В полученном живом каталоге полная стоимость — {item.item_cost}; остаточная стоимость с компонентами и историческая цена требуют проверки.")
                if item.mana_costs:
                    tradeoffs.append("В живом источнике есть затрата маны: " + "/".join(str(x) for x in item.mana_costs) + "; проверь доступный ресурс и применимость патча.")
                if item.cooldowns:
                    tradeoffs.append("Живой источник задаёт перезарядку " + "/".join(str(x) for x in item.cooldowns) + "; расход ресурса может изменить следующее окно действий.")
            else:
                tradeoffs.append("Сначала уточни эффект, расход ресурса и ограничения предмета; название покупки не доказывает соответствие цели.")
        tradeoffs.append("Сравни расход золота и занятый слот с альтернативой; наличие покупки не доказывает текущую готовность или оптимальность.")
        revisit.extend(("Цель игрока изменилась.", "Появилась новая доступная угроза или изменились свои ресурсы.",
                        "Уточнены патч, компоненты, доставка или ограничения применения."))
        if feasibility == "unknown":
            detail = ("доступное золото, остаточную стоимость, доступ к покупке и свободный слот"
                      if any(gap.startswith("context_unknown:") for gap in gaps) else
                      "механику нужного патча, компоненты, доставку и ограничения применения")
            research.append("Для " + (item.label if item else name) + " проверить выполнимость: " + detail + ".")
        options.append(OptionTradeoff(content_hash((question.input_hash, name)), name,
                                     item.label if item else name.removeprefix("item_"),
                                     "conditional_option" if conditional else "research_question",
                                     name in purchased, "Если цель — " + GOAL_TEXT[question.goal.kind] + ".",
                                     tuple(advantages), tuple(tradeoffs), feasibility, gaps,
                                     tuple(dict.fromkeys(evidence)), tuple(dict.fromkeys(urls)),
                                     tuple(dict.fromkeys(revisit)), catalog.snapshot_id if catalog else None))
    options.append(OptionTradeoff(content_hash((question.input_hash, "defer")), None,
                                 "Отложить выбор до уточнения условия", "conditional_alternative", False,
                                 "Если неопределённость существенно меняет цель или выполнимость.",
                                 ("Сохраняет выбор до уточнения существенного условия.",),
                                 ("Может отложить нужный эффект; цену ожидания нельзя оценить без контекста следующего действия.",),
                                 "unknown", ("waiting_window_and_obligation_unknown",), (), (),
                                 ("Есть проверяемый дедлайн действия.", "Уточнены цель и значимая угроза.")))
    attention = None
    feasible = [o for o in options if o.status == "conditional_option" and o.feasibility == "feasible"]
    if scope_known and question.goal.origin == "user_confirmed" and observed and feasible:
        refs = tuple(dict.fromkeys(ref for option in feasible for ref in option.evidence_ids))
        attention = BuildAttentionRule(content_hash((question.input_hash, "planning-check")),
                                       "Перед следующей покупкой в сопоставимом доступном контексте.",
                                       "Назови свою цель, источник наблюдаемой угрозы, выполнимый вариант и его цену относительно альтернативы. При изменении контекста пересмотри выбор.",
                                       "Игрок может назвать условие выбора и условие пересмотра; упражнение не оценивает победу или смерть.", refs)
    limitations = (
        "Цель — сообщение игрока или редактируемая гипотеза, не чтение намерения из исхода.",
        "Командное наблюдение не доказывает внимание игрока; скрытый world state не используется.",
        "Ручная привязка механики требует независимой проверки и не включает validated-критерий.",
        "Покупка не доказывает наличие предмета сейчас; продажи, доставка, компоненты и ограничения учитываются отдельно.",
    )
    return BuildAnalysis(question.question_id, question.input_hash,
                         "conditional_analysis" if any(o.status == "conditional_option" for o in options) else "research_assistance",
                         question.goal, _goal_hypotheses(question, observed), tuple(options), purchases,
                         attention, tuple(dict.fromkeys(research)), tuple(reasons), limitations,
                         "matching_declared_patch_review" if scope_known else "not_established")
