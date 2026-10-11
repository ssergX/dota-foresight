"""Conditional route/arrival bounds from player-known operands.

Graph distances are not arrival times. Only caller-owned review bindings admit
the finite walking model; portable JSON cannot certify terrain or mechanics.
Even admitted calculations assume route/control/speed persistence and never
establish safety, ward utility, actual ally arrival or a gameplay verdict.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import heapq
import math
from pathlib import Path

from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from .choice_window import PrefixFact


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _number(value, *, positive=False):
    if not _finite(value) or value < 0 or (positive and value == 0):
        raise ValueError('finite nonnegative distance/speed required')


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError('explicit identity/version required')


@dataclass(frozen=True)
class MovementScope:
    match_id: int
    subject_ref: str
    observer_ref: str
    patch: str
    at: TimeRef
    prefix_record_index: int
    max_fact_age_ms: float = 1000
    dataset_kind: str = 'unknown'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or type(self.prefix_record_index) is not int or self.prefix_record_index <= 0:
            raise ValueError('exact match and prefix required')
        for value in (self.subject_ref, self.observer_ref, self.patch):
            _text(value)
        if not isinstance(self.at, TimeRef) or self.dataset_kind not in ('replay', 'synthetic', 'unknown'):
            raise ValueError('typed cutoff and dataset kind required')
        _number(self.max_fact_age_ms)


@dataclass(frozen=True)
class RouteEdge:
    edge_id: str
    start: str
    end: str
    distance_min: float
    distance_max: float

    def __post_init__(self):
        for value in (self.edge_id, self.start, self.end):
            _text(value)
        _number(self.distance_min)
        _number(self.distance_max)
        if self.distance_max < self.distance_min:
            raise ValueError('ordered route distance bounds required')


@dataclass(frozen=True)
class NavigationGraph:
    patch: str
    method_version: str
    nodes: tuple[str, ...]
    edges: tuple[RouteEdge, ...]
    source_refs: tuple[SourceRef, ...]
    available_at: TimeRef | None

    def __post_init__(self):
        _text(self.patch)
        _text(self.method_version)
        if not isinstance(self.nodes, tuple) or not self.nodes or len(self.nodes) > 4096 or len(set(self.nodes)) != len(self.nodes):
            raise ValueError('bounded distinct graph nodes required')
        for node in self.nodes:
            _text(node)
        if not isinstance(self.edges, tuple) or len(self.edges) > 16384 or any(not isinstance(e, RouteEdge) for e in self.edges):
            raise ValueError('bounded typed edges required')
        if len({e.edge_id for e in self.edges}) != len(self.edges) or any(e.start not in self.nodes or e.end not in self.nodes for e in self.edges):
            raise ValueError('exact unique edge topology required')
        if not isinstance(self.source_refs, tuple) or not self.source_refs or any(not isinstance(s, SourceRef) for s in self.source_refs):
            raise ValueError('graph source receipts required')
        if self.available_at is not None and not isinstance(self.available_at, TimeRef):
            raise TypeError('typed graph availability required')

    @property
    def semantic_hash(self):
        # An artifact-wide digest is a receipt, not a player-visible feature.
        return content_hash({'patch': self.patch, 'method': self.method_version,
            'nodes': self.nodes, 'edges': [asdict(e) for e in self.edges]})

    @property
    def admission_hash(self):
        """Bind the separate review to this graph's exact source receipts."""
        return content_hash(self)


@dataclass(frozen=True)
class MovementSemantics:
    patch: str
    method_version: str
    alive_life_state: int
    movement_block_mask: int

    def __post_init__(self):
        _text(self.patch)
        _text(self.method_version)
        if any(type(v) is not int or v < 0 for v in (self.alive_life_state, self.movement_block_mask)):
            raise ValueError('explicit interpreted life/control semantics required')


@dataclass(frozen=True)
class MovementAdmission:
    """Exact caller-owned research review registry; never loaded from JSON."""
    match_id: int
    subject_ref: str
    observer_ref: str
    patch: str
    graph_hashes: frozenset[str]
    semantic_hashes: frozenset[str]
    fact_hashes: frozenset[str]
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError('exact admission match required')
        for value in (self.subject_ref, self.observer_ref, self.patch):
            _text(value)
        for hashes in (self.graph_hashes, self.semantic_hashes, self.fact_hashes):
            if not isinstance(hashes, frozenset) or any(not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in hashes):
                raise ValueError('immutable exact review hashes required')
        if not isinstance(self.review_sources, tuple) or not self.review_sources or any(not isinstance(s, SourceRef) for s in self.review_sources):
            raise ValueError('independent review receipts required')


def _visible(scope, observation):
    fact = observation.fact
    if fact.subject_ref != scope.subject_ref or fact.observer_ref != scope.observer_ref or fact.perspective not in ('team', 'screen', 'public'):
        raise ValueError('hidden world/foreign movement context forbidden')
    if observation.source_record_index >= scope.prefix_record_index:
        return False
    if fact.available_at is None or fact.valid_at.order_status != 'verified' or fact.available_at.order_status != 'verified' or scope.at.order_status != 'verified':
        return False
    if not fact.available_at.definitely_available_before(scope.at) or not fact.valid_at.definitely_available_before(scope.at):
        return False
    times = (fact.valid_at.game_time_ms, fact.valid_at.uncertainty_ms, scope.at.game_time_ms, scope.at.uncertainty_ms)
    if None in times or scope.at.game_time_ms + scope.at.uncertainty_ms - (fact.valid_at.game_time_ms - fact.valid_at.uncertainty_ms) > scope.max_fact_age_ms:
        return False
    return fact.status in ('observed', 'derived')


def _path(graph, start, end, allowed, *, upper):
    adjacency = {node: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.edge_id in allowed:
            adjacency[edge.start].append(edge)
    queue = [(0, start)]
    distances, previous = {start: 0}, {}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        if node == end:
            edges = []
            while node != start:
                prior, edge = previous[node]
                edges.append(edge)
                node = prior
            return distance, tuple(reversed(edges))
        for edge in sorted(adjacency[node], key=lambda e: e.edge_id):
            candidate = distance + (edge.distance_max if upper else edge.distance_min)
            if not _finite(candidate):
                raise ValueError('accumulated route distance is not finite')
            if candidate < distances.get(edge.end, math.inf):
                distances[edge.end] = candidate
                previous[edge.end] = node, edge.edge_id
                heapq.heappush(queue, (candidate, edge.end))
    return None


def evaluate_movement(scope: MovementScope, *, graph: NavigationGraph | None,
                      start_node: str, destination_node: str, facts: tuple[PrefixFact, ...],
                      semantics: MovementSemantics | None = None,
                      admission: MovementAdmission | None = None) -> dict:
    if not isinstance(scope, MovementScope) or not isinstance(facts, tuple) or any(not isinstance(f, PrefixFact) for f in facts):
        raise TypeError('typed immutable movement context required')
    if graph is not None and (not isinstance(graph, NavigationGraph) or graph.patch != scope.patch):
        raise ValueError('foreign historical graph')
    if semantics is not None and (not isinstance(semantics, MovementSemantics) or semantics.patch != scope.patch):
        raise ValueError('foreign historical movement semantics')
    if admission is not None and (not isinstance(admission, MovementAdmission) or
            (admission.match_id, admission.subject_ref, admission.observer_ref, admission.patch) !=
            (scope.match_id, scope.subject_ref, scope.observer_ref, scope.patch)):
        raise ValueError('portable/foreign admission forbidden')
    _text(start_node)
    _text(destination_node)
    if graph is not None and (start_node not in graph.nodes or destination_node not in graph.nodes):
        raise ValueError('query node absent from graph')
    allowed = {'movement.start_node', 'movement.speed_min', 'movement.speed_max',
               'movement.life_state', 'movement.control_bits'} | ({'route.passable:' + e.edge_id for e in graph.edges} if graph else set())
    prefix = {}
    for observation in facts:
        if observation.fact.predicate not in allowed:
            raise ValueError('movement operand allowlist required')
        if not _visible(scope, observation):
            continue
        if observation.fact.predicate in prefix:
            raise ValueError('ambiguous current movement operand')
        prefix[observation.fact.predicate] = observation
    features = []
    for key, observation in sorted(prefix.items()):
        value = asdict(observation)
        value['fact']['source_refs'] = [{k: getattr(s, k) for k in ('provider', 'schema_version', 'locator', 'extractor_version')} for s in observation.fact.source_refs]
        features.append(value)
    graph_known = bool(graph and graph.available_at and scope.at.order_status == 'verified' and graph.available_at.order_status == 'verified' and graph.available_at.definitely_available_before(scope.at))
    graph_admitted = bool(graph_known and admission and graph.admission_hash in admission.graph_hashes)
    semantics_admitted = bool(semantics and admission and content_hash(semantics) in admission.semantic_hashes)
    def value(key):
        fact = prefix.get(key)
        return fact.fact.value if fact and admission and fact.input_hash in admission.fact_hashes else None
    reasons = []
    if not graph_admitted:
        reasons.append('historical_navigation_not_independently_bound')
    if not semantics_admitted:
        reasons.append('movement_mechanics_not_independently_bound')
    state, control = value('movement.life_state'), value('movement.control_bits')
    can_begin = None
    if semantics_admitted and type(state) is int and type(control) is int and min(state, control) >= 0:
        can_begin = state == semantics.alive_life_state and (control & semantics.movement_block_mask) == 0
    if can_begin is None:
        reasons.append('alive_or_movement_control_unknown')
    if value('movement.start_node') != start_node:
        reasons.append('current_location_not_bound_to_graph')
    speed_min, speed_max = value('movement.speed_min'), value('movement.speed_max')
    speed_known = (type(speed_min) in (int, float) and type(speed_max) in (int, float) and
        _finite(speed_min) and _finite(speed_max) and 0 < speed_min <= speed_max)
    if not speed_known:
        reasons.append('movement_speed_bounds_unknown')
    possible = definite = None
    if graph_admitted:
        decisions = {e.edge_id: value('route.passable:' + e.edge_id) for e in graph.edges}
        if any(type(v) not in (bool, type(None)) for v in decisions.values()):
            raise ValueError('route passability must be boolean or unknown')
        possible = _path(graph, start_node, destination_node, {k for k, v in decisions.items() if v is not False}, upper=False)
        definite = _path(graph, start_node, destination_node, {k for k, v in decisions.items() if v is True}, upper=True)
        if definite is None and possible is not None:
            reasons.append('path_contains_unknown_traversability')
    status = 'unknown'
    travel = None
    if graph_admitted and semantics_admitted and value('movement.start_node') == start_node:
        if can_begin is False or possible is None:
            status = 'excluded_in_reviewed_movement_model'
        elif can_begin is True and definite is not None and speed_known:
            status = 'conditional_route_supported'
            travel = {'minimum_ms': possible[0] / speed_max * 1000,
                      'maximum_ms': definite[0] / speed_min * 1000}
            if any(not _finite(v) for v in travel.values()):
                raise ValueError('derived movement duration is not finite')
    result = {'schema_version': 'foresight.movement-review.v1', 'status': status,
        'subject_ref': scope.subject_ref, 'observer_ref': scope.observer_ref, 'dataset_kind': scope.dataset_kind,
        'start_node': start_node, 'destination_node': destination_node,
        'path_edge_ids': list(definite[1]) if definite else [], 'travel_duration_bounds': travel,
        'reason_codes': reasons, 'safety': 'not_established', 'actual_arrival': 'not_established',
        'assumptions': ['reviewed graph covers this finite walking query', 'traversability, speed and movement control persist during transit',
                        'no additional turns, attacks, channels, collision or repositioning beyond the supplied model'],
        'evidence_refs': [f.fact.fact_id for f in prefix.values()], 'training_eligible': False,
        'strategic_quality': 'not_established', 'validation_status': 'conditional_research_not_certified',
        'input_hash': content_hash({'scope': asdict(scope), 'graph': graph.semantic_hash if graph_known else None,
            'start': start_node, 'end': destination_node, 'facts': features, 'semantics': asdict(semantics) if semantics else None})}
    result['payload_sha256'] = content_hash(result)
    return result


def load_movement_input(source: str | Path | dict) -> dict:
    from .batch import strict_json, read_fact
    if not isinstance(source, dict) and Path(source).stat().st_size > 4 * 1024 * 1024:
        raise ValueError('bounded movement input required')
    data = source if isinstance(source, dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    keys = {'schema_version', 'scope', 'graph', 'start_node', 'destination_node', 'facts', 'semantics'}
    if not isinstance(data, dict) or set(data) != keys or data['schema_version'] != 'foresight.movement-input.v1':
        raise ValueError('strict movement proposal required; admission is not portable')
    try:
        scope = dict(data['scope']); scope['at'] = TimeRef(**scope['at'])
        graph = data['graph']
        if graph is not None:
            graph = dict(graph)
            graph['nodes'] = tuple(graph['nodes']); graph['edges'] = tuple(RouteEdge(**e) for e in graph['edges'])
            graph['source_refs'] = tuple(SourceRef(**r) for r in graph['source_refs'])
            graph['available_at'] = TimeRef(**graph['available_at']) if graph['available_at'] is not None else None
            graph = NavigationGraph(**graph)
        if not isinstance(data['facts'], list) or len(data['facts']) > 16389 or any(not isinstance(f, dict) or set(f) != {'fact', 'source_record_index'} for f in data['facts']):
            raise ValueError('bounded exact prefix facts required')
        facts = tuple(PrefixFact(read_fact(f['fact']), f['source_record_index']) for f in data['facts'])
        semantics = MovementSemantics(**data['semantics']) if data['semantics'] is not None else None
        return {'scope': MovementScope(**scope), 'graph': graph, 'start_node': data['start_node'],
                'destination_node': data['destination_node'], 'facts': facts, 'semantics': semantics}
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError('malformed typed movement input') from exc
