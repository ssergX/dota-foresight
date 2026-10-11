"""Finite conditional grid visibility/navigation; no built-in Dota terrain rules.

The caller supplies a historical map and explicit raster semantics. Candidate
calculations are inspectable without admission, but never establish actual game
vision, route safety, opponent positions or utility of a ward.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path

from dota_coach.evidence.contracts import SourceRef, TimeRef, content_hash
from .movement import NavigationGraph, RouteEdge
from .defensive_impact import _before, _refs, _sha, _text


def number(value, *, positive=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and abs(value) <= 2**53 - 1
    except OverflowError:
        valid = False
    if not valid or (positive and value <= 0):
        raise ValueError('finite bounded terrain operand required')


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    height: float | None
    walkable: bool | None
    opaque: bool | None

    def __post_init__(self):
        if any(type(v) is not int or not 0 <= v < 64 for v in (self.x, self.y)):
            raise ValueError('bounded cell coordinates required')
        if self.height is not None:
            number(self.height)
        if any(v is not None and type(v) is not bool for v in (self.walkable, self.opaque)):
            raise ValueError('tri-state cell properties required')


@dataclass(frozen=True)
class TerrainModel:
    patch: str
    game_build: str
    method_version: str
    width: int
    height: int
    cell_size: float
    cells: tuple[Cell, ...]
    source_refs: tuple[SourceRef, ...]
    available_at: TimeRef | None
    # Explicit conditional semantics, never defaults describing Dota.
    blocker_cell_visible: bool
    maximum_visible_height_above_observer: float

    def __post_init__(self):
        for value in (self.patch, self.game_build, self.method_version):
            _text(value)
        if any(type(v) is not int or not 1 <= v <= 64 for v in (self.width, self.height)):
            raise ValueError('bounded raster dimensions required')
        number(self.cell_size, positive=True)
        number(self.maximum_visible_height_above_observer)
        if self.maximum_visible_height_above_observer < 0 or type(self.blocker_cell_visible) is not bool:
            raise ValueError('explicit nonnegative height/opaque semantics required')
        if (not isinstance(self.cells, tuple) or len(self.cells) != self.width * self.height
                or any(not isinstance(c, Cell) or c.x >= self.width or c.y >= self.height for c in self.cells)
                or len({(c.x, c.y) for c in self.cells}) != len(self.cells)):
            raise ValueError('complete unique typed raster required; unknown cells must be explicit')
        _refs(self.source_refs)
        if self.available_at is not None and not isinstance(self.available_at, TimeRef):
            raise TypeError('typed terrain availability required')


@dataclass(frozen=True)
class TerrainScope:
    match_id: int
    subject_ref: str
    observer_ref: str
    patch: str
    game_build: str
    at: TimeRef
    prefix_record_index: int
    dataset_kind: str

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (self.match_id, self.prefix_record_index)):
            raise ValueError('exact match/prefix required')
        for v in (self.subject_ref, self.observer_ref, self.patch, self.game_build):
            _text(v)
        if not isinstance(self.at, TimeRef) or self.dataset_kind not in ('replay', 'synthetic', 'unknown'):
            raise ValueError('typed clock/source kind required')


@dataclass(frozen=True)
class KnownBlocker:
    blocker_id: str
    x: int
    y: int
    blocks_walk: bool | None
    blocks_vision: bool | None
    active: bool | None
    subject_ref: str
    observer_ref: str
    perspective: str
    valid_at: TimeRef
    available_at: TimeRef | None
    source_record_index: int
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        for v in (self.blocker_id, self.subject_ref, self.observer_ref):
            _text(v)
        Cell(self.x, self.y, None, None, None)
        if any(v is not None and type(v) is not bool for v in (self.blocks_walk, self.blocks_vision, self.active)):
            raise ValueError('tri-state blocker required')
        if self.perspective not in ('screen', 'team', 'public', 'world'):
            raise ValueError('explicit blocker perspective required')
        if type(self.source_record_index) is not int or self.source_record_index < 1:
            raise ValueError('exact blocker record required')
        if not isinstance(self.valid_at, TimeRef) or (self.available_at is not None and not isinstance(self.available_at, TimeRef)):
            raise TypeError('typed blocker times required')
        _refs(self.source_refs)


@dataclass(frozen=True)
class WardQuery:
    query_id: str
    x: int
    y: int
    radius: float
    observer_height_offset: float

    def __post_init__(self):
        _text(self.query_id)
        Cell(self.x, self.y, None, None, None)
        number(self.radius)
        number(self.observer_height_offset)
        if self.radius < 0:
            raise ValueError('nonnegative conditional radius required')


@dataclass(frozen=True)
class TerrainAdmission:
    packet_hash: str
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        _sha(self.packet_hash)
        _refs(self.review_sources)


@dataclass(frozen=True)
class TerrainRegistry:
    admissions: tuple[TerrainAdmission, ...]
    allowed_source_receipt_hashes: frozenset[str]
    review_context: str

    def __post_init__(self):
        if (not isinstance(self.admissions, tuple) or len(self.admissions) > 128
                or any(not isinstance(a, TerrainAdmission) for a in self.admissions)
                or len({a.packet_hash for a in self.admissions}) != len(self.admissions)):
            raise ValueError('bounded unique exact terrain admissions required')
        if not isinstance(self.allowed_source_receipt_hashes, frozenset):
            raise TypeError('immutable current source allowlist required')
        for value in self.allowed_source_receipt_hashes:
            _sha(value)
        if self.review_context not in ('testing', 'external_review'):
            raise ValueError('explicit caller review context required')


def _supercover(start, end):
    """All cells met by a centre-to-centre ray, including both corner neighbours."""
    x, y = start
    dx, dy = end[0] - x, end[1] - y
    nx, ny = abs(dx), abs(dy)
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    ix = iy = 0
    result = [(x, y)]
    while ix < nx or iy < ny:
        crossing_x = (1 + 2 * ix) * ny
        crossing_y = (1 + 2 * iy) * nx
        if crossing_x == crossing_y:
            result.extend(((x + sx, y), (x, y + sy)))
            x += sx; y += sy; ix += 1; iy += 1
        elif crossing_x < crossing_y:
            x += sx; ix += 1
        else:
            y += sy; iy += 1
        result.append((x, y))
    return tuple(dict.fromkeys(result))


def _view(model, cells, query):
    origin = cells[(query.x, query.y)]
    radius2 = Fraction(str(query.radius)) ** 2
    scale2 = Fraction(str(model.cell_size)) ** 2
    observer_height = None if origin.height is None else Fraction(str(origin.height)) + Fraction(str(query.observer_height_offset))
    ceiling = None if observer_height is None else observer_height + Fraction(str(model.maximum_visible_height_above_observer))
    visible, blocked, unknown = [], [], []
    for point, cell in sorted(cells.items()):
        if ((point[0] - query.x) ** 2 + (point[1] - query.y) ** 2) * scale2 > radius2:
            continue
        # The origin is included only when its height/occupancy is known.
        pending = ceiling is None
        stop = False
        for position in _supercover((query.x, query.y), point):
            c = cells[position]
            if c.height is None or ceiling is None:
                pending = True
            elif Fraction(str(c.height)) > ceiling:
                stop = True
            if position != (query.x, query.y):
                if c.opaque is None:
                    pending = True
                elif c.opaque and (position != point or not model.blocker_cell_visible):
                    stop = True
        (blocked if stop else unknown if pending else visible).append(point)
    return {'query': asdict(query), 'visible_cells': visible, 'blocked_cells': blocked, 'unknown_cells': unknown}


def _navigation(model, cells, scope, dependencies, packet_hash):
    nodes = tuple(f'{x},{y}' for (x, y), c in sorted(cells.items()) if c.walkable is True)
    edges = []
    for (x, y), c in sorted(cells.items()):
        if c.walkable is not True:
            continue
        for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if point in cells and cells[point].walkable is True:
                start, end = f'{x},{y}', f'{point[0]},{point[1]}'
                edges.append(RouteEdge(start + '>' + end, start, end, model.cell_size, model.cell_size))
    # Empty known terrain is represented explicitly, never by an invented node.
    if not nodes:
        return None
    lineage = SourceRef('terrain-prefix:' + packet_hash, packet_hash, 'foresight.terrain',
        'foresight.terrain-prefix.v1', f'match:{scope.match_id}:record:{scope.prefix_record_index}', 'terrain-grid.v1')
    sources = tuple({content_hash(s):s for s in dependencies + (lineage,)}.values())
    # Consumers must never drop provenance to fit a smaller downstream DTO.
    if len(sources) > 32:
        return None
    # The graph is compiled at this prefix boundary, not when the static map
    # first became available. This conservatively prevents use at an earlier
    # choice even when dynamic blockers were delivered after the map receipt.
    return NavigationGraph(model.patch, model.method_version + '/cardinal-grid.v1', nodes, tuple(edges), sources, scope.at)


def evaluate_terrain(scope, model, *, blockers=(), queries=(), registry=None):
    if not isinstance(scope, TerrainScope) or not isinstance(model, TerrainModel):
        raise TypeError('typed terrain scope/model required')
    for values, cls, limit in ((blockers, KnownBlocker, 1024), (queries, WardQuery, 16)):
        if not isinstance(values, tuple) or len(values) > limit or any(not isinstance(v, cls) for v in values):
            raise TypeError('bounded immutable typed terrain inputs required')
    if len({b.blocker_id for b in blockers}) != len(blockers) or len({q.query_id for q in queries}) != len(queries):
        raise ValueError('unique blocker/query IDs required')
    if any(q.x >= model.width or q.y >= model.height for q in queries):
        raise ValueError('query outside historical map')
    if registry is not None and not isinstance(registry, TerrainRegistry):
        raise TypeError('caller-owned typed registry required; JSON cannot grant terrain review')
    prefix = []
    for b in blockers:
        if b.subject_ref != scope.subject_ref or b.observer_ref != scope.observer_ref or b.perspective == 'world':
            raise ValueError('hidden/foreign blocker evidence forbidden')
        if b.x >= model.width or b.y >= model.height:
            raise ValueError('blocker outside historical map')
        if b.source_record_index < scope.prefix_record_index and _before(b.valid_at, scope.at) and _before(b.available_at, scope.at):
            prefix.append(b)
    packet = {'scope': asdict(scope), 'model': asdict(model), 'blockers': [asdict(b) for b in sorted(prefix, key=lambda v: v.blocker_id)],
              'queries': [asdict(q) for q in queries]}
    packet_hash = content_hash(packet)
    dependencies = model.source_refs + tuple(s for b in prefix for s in b.source_refs)
    reasons = []
    if (model.patch, model.game_build) != (scope.patch, scope.game_build):
        reasons.append('historical_map_patch_or_build_mismatch')
    if not _before(model.available_at, scope.at):
        reasons.append('map_availability_or_clock_unknown')
    candidate = None
    if not reasons:
        cells = {(c.x, c.y): c for c in model.cells}
        for b in prefix:
            if b.active is False:
                continue
            c = cells[(b.x, b.y)]
            # Union known active obstacles; uncertain obstacles can only degrade
            # known traversability/visibility, never remove a known obstruction.
            walk = c.walkable
            opaque = c.opaque
            if b.active is True and b.blocks_walk is True:
                walk = False
            elif walk is not False and b.blocks_walk is not False:
                walk = None
            if b.active is True and b.blocks_vision is True:
                opaque = True
            elif opaque is not True and b.blocks_vision is not False:
                opaque = None
            cells[(b.x, b.y)] = Cell(c.x, c.y, c.height, walk, opaque)
        views = [_view(model, cells, q) for q in queries]
        graph = _navigation(model, cells, scope, dependencies, packet_hash)
        nav_source_count = len({content_hash(s) for s in dependencies}) + 1
        if nav_source_count > 32:
            reasons.append('navigation_provenance_limit_exceeded_no_receipts_dropped')
        frequency = Counter(point for view in views for point in view['visible_cells'])
        candidate = {'ward_views': views, 'navigation_graph': asdict(graph) if graph else None,
            'unknown_navigation_cells': sum(c.walkable is None for c in cells.values()),
            'navigation_status': 'conditional_graph' if graph else 'provenance_limit' if nav_source_count > 32 else 'no_known_walkable_cells',
            'duplicate_visible_cells': sorted(point for point, count in frequency.items() if count > 1),
            'union_visible_cells': sorted(set.union(*(set(map(tuple, v['visible_cells'])) for v in views))) if views else []}
    admitted = False
    if registry:
        for a in registry.admissions:
            if a.packet_hash == packet_hash and all(content_hash(s) in registry.allowed_source_receipt_hashes for s in dependencies + a.review_sources):
                admitted = True
    if not admitted:
        reasons.append('independent_exact_map_and_prefix_review_missing')
    return {'schema_version': 'foresight.terrain-review.v1', 'packet_hash': packet_hash, 'scope': asdict(scope),
        'status': 'testing_only' if admitted and candidate is not None and registry.review_context == 'testing' else
                  'conditional_model_admitted' if admitted and candidate is not None else 'unknown',
        'candidate_geometry': candidate, 'reason_codes': sorted(set(reasons)),
        'dependency_receipts': [asdict(s) for s in dependencies],
        'actual_game_vision_established': False, 'route_safety_established': False, 'ward_utility_established': False,
        'training_eligible': False,
        'assumptions': ['cell_centre_static_raster_supercover_visibility', 'declared_height_and_opaque_rules',
                        'cardinal_grid_navigation_only', 'provided_last_known_blockers_persist',
                        'known_prefix_obstacles_only_dynamic_completeness_not_established']}


def load_terrain_input(value):
    from .batch import strict_json
    if not isinstance(value, dict):
        path = Path(value)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('bounded terrain proposal: maximum 4 MiB')
        value = strict_json(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'scope', 'model', 'blockers', 'queries'}
            or value['schema_version'] != 'foresight.terrain-input.v1'):
        raise ValueError('exact terrain proposal required; portable admission forbidden')
    def dto(cls, obj):
        if not isinstance(obj, dict) or set(obj) != {f.name for f in fields(cls)}:
            raise ValueError('exact terrain DTO fields required')
        args = dict(obj)
        for key in ('at', 'valid_at', 'available_at'):
            if key in args and args[key] is not None:
                args[key] = dto(TimeRef, args[key])
        if 'source_refs' in args:
            if not isinstance(args['source_refs'], list) or len(args['source_refs']) > 32:
                raise ValueError('bounded terrain sources required')
            args['source_refs'] = tuple(dto(SourceRef, s) for s in args['source_refs'])
        if 'cells' in args:
            if not isinstance(args['cells'], list) or len(args['cells']) > 4096:
                raise ValueError('bounded terrain cells required')
            args['cells'] = tuple(dto(Cell, c) for c in args['cells'])
        return cls(**args)
    for key, maximum in (('blockers', 1024), ('queries', 16)):
        if not isinstance(value[key], list) or len(value[key]) > maximum:
            raise ValueError('bounded terrain input list required')
    return dict(scope=dto(TerrainScope, value['scope']), model=dto(TerrainModel, value['model']),
                blockers=tuple(dto(KnownBlocker, b) for b in value['blockers']), queries=tuple(dto(WardQuery, q) for q in value['queries']))
