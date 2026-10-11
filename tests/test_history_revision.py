from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.history import load_history, save_brief


def test_reanalysis_of_same_match_set_replaces_period_without_new_progress(tmp_path):
    brief = CoachBrief("feeding", "first", "", "", generated_for_matches=[1, 2],
                       detector_version="v1")
    save_brief(7, brief, tmp_path)
    brief.headline = "revised"
    brief.generated_for_matches = [2, 1]
    save_brief(7, brief, tmp_path)
    history = load_history(7, tmp_path)
    assert len(history) == 1 and history[0].headline == "revised"
    brief.generated_for_matches = [3, 4]
    save_brief(7, brief, tmp_path)
    assert len(load_history(7, tmp_path)) == 2
