from dota_coach.coach.principles import principles_for
from dota_coach.leaks import detectors as _reg  # noqa: F401  (регистрация)
from dota_coach.leaks.registry import DETECTORS


def test_every_registered_key_has_a_principle_section():
    default = "Разбирай процесс и решения, а не исход. Дай конкретное проверяемое действие."
    missing = [d.key for d in DETECTORS if principles_for(d.key) == default]
    assert missing == [], f"нет секции принципов для ключей: {missing}"
