from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import compare_focus
from dota_coach.models import Leak


def _leak(value=9., role=5):
    return Leak(key="feeding", title="Смерти", magnitude="", metric="deaths_per_game", value=value,
                threshold=8., direction="lower_is_better", role=role)


def _prior():
    return CoachBrief("feeding", "", "", "", focus_metric="deaths_per_game",
                      focus_value=11., focus_role=5, generated_for_matches=[1, 2],
                      detector_version="v1", source_version="patch1", coverage_signature="covered")


def _compare(prior, leaks, **kw):
    meta = dict(match_ids=[3, 4], detector_version="v1", source_version="patch1",
                coverage_signature="covered")
    meta.update(kw)
    return compare_focus(prior, leaks, **meta)


def test_no_history():
    assert _compare(None, [_leak()]).status == "no_history"


def test_missing_signal_is_unknown_even_with_matching_metadata():
    note = _compare(_prior(), [])
    assert note.status == "insufficient_data"
    assert note.curr_value is None
    assert "не доказывает" in note.text


def test_descriptive_change_requires_comparable_periods():
    assert _compare(_prior(), [_leak(9.)]).status == "improved"
    assert _compare(_prior(), [_leak(12.)]).status == "regressed"
    assert _compare(_prior(), [_leak(11.)]).status == "flat"
    assert "Качество решений" in _compare(_prior(), [_leak(9.)]).text


def test_overlap_and_duplicate_ids_block_progress():
    for ids in ([1, 3], [3, 3]):
        assert _compare(_prior(), [_leak()], match_ids=ids).status == "insufficient_data"


def test_unknown_or_changed_role_version_coverage_block_progress():
    for meta in (dict(source_version=""), dict(source_version="patch2"),
                 dict(detector_version="v2"), dict(coverage_signature="partial")):
        assert _compare(_prior(), [_leak()], **meta).status == "insufficient_data"
    assert _compare(_prior(), [_leak(role=4)]).status == "insufficient_data"
    assert compare_focus(_prior(), [_leak()]).status == "insufficient_data"


def test_metadata_does_not_upgrade_missing_signal_to_resolved():
    for meta in (dict(match_ids=[1, 2]), dict(source_version="patch2"),
                 dict(coverage_signature="")):
        assert _compare(_prior(), [], **meta).status == "insufficient_data"
