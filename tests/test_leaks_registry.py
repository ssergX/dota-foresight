from dota_coach.leaks.registry import DETECTORS, applicable, detector, filter_rows
from dota_coach.leaks.rows import Row
from dota_coach.models import PlayerMatch


def _row(mid, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=4, me=PlayerMatch(**base))


def test_detector_registers_and_applicable_filters_by_role():
    before = len(DETECTORS)

    @detector(key="t_only_pos4", title="x", roles=(4,), requires=(),
              impact=0.5, phase="vision", family="vision")
    def _d(rows, role, th):
        return None

    try:
        assert len(DETECTORS) == before + 1
        keys4 = {d.key for d in applicable(4)}
        keys3 = {d.key for d in applicable(3)}
        assert "t_only_pos4" in keys4 and "t_only_pos4" not in keys3
    finally:
        # DETECTORS — глобальный мутируемый список; убираем тестовый детектор,
        # иначе он утекает в другие тесты (например, проверку полноты principles.md).
        DETECTORS.pop()


def test_filter_rows_excludes_missing_and_never_zeros():
    rows = [
        _row(1, life_state_dead=500),   # есть
        _row(2, life_state_dead=None),  # нет -> исключить
        _row(3, life_state_dead=0),     # ноль -> это данные, оставить
    ]
    kept = [r.match_id for r in filter_rows(rows, ("life_state_dead",))]
    assert kept == [1, 3]


def test_filter_rows_empty_list_field_is_absent():
    rows = [_row(1, dn_t=[1, 2]), _row(2, dn_t=[])]
    assert [r.match_id for r in filter_rows(rows, ("dn_t",))] == [1]
