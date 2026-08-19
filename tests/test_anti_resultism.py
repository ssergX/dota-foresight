from dataclasses import asdict

from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch

# radiant_* — сырые токены исхода, проверяем ВЕЗДЕ; русские слова — только в user-данных
# (системный промпт нарочно называет «Побед/поражений тебе не дают»).
_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _series():
    return [Match(match_id=i, duration=1800, radiant_win=(i % 2 == 0),
                  players=[_me(position_est=4, deaths=18, obs_placed=1,
                               benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}})],
                  parsed=True) for i in range(8)]


def test_leaks_and_prompt_carry_no_outcome():
    leaks = detect_leaks(_series(), 7)
    assert leaks
    for leak in leaks:
        blob = str(asdict(leak)).lower()
        assert not any(t in blob for t in _BANNED_TOKENS)
        assert not any(w in blob for w in _BANNED_WORDS)
    msgs = build_coach_prompt(leaks, None, "p", None, leaks[0].key)
    whole = "".join(m["content"] for m in msgs).lower()
    assert not any(t in whole for t in _BANNED_TOKENS)
    user = msgs[1]["content"].lower()
    assert not any(w in user for w in _BANNED_WORDS)


def test_every_leak_has_complete_metadata():   # спека, инвариант #4 «целостность метаданных»
    leaks = detect_leaks(_series(), 7)
    assert leaks
    for leak in leaks:
        assert leak.key and leak.metric and leak.source
        assert leak.sample_size >= 5
        assert leak.role in (1, 2, 3, 4, 5)
