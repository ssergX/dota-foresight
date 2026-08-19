# импорт ради side-effect регистрации детекторов в DETECTORS
from dota_coach.leaks.detectors import (  # noqa: F401
    deaths, economy, fights, laning, objectives, vision,
)
