from dota_coach.coach.principles import principles_for


def test_principles_for_known_leak_returns_text():
    text = principles_for("feeding")
    assert isinstance(text, str)
    assert len(text) > 0
    assert "смерт" in text.lower()


def test_principles_for_unknown_leak_returns_default():
    text = principles_for("totally_unknown_leak_key")
    assert isinstance(text, str)
    assert len(text) > 0
