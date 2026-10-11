"""Exact declared decimal clocks and conservative numeric interval exports.

Comparisons must use rational bounds; exported floats cannot enlarge guaranteed
regions. This code verifies clock structure, not the caller's clock mapping.
"""
from fractions import Fraction
import math
from dota_coach.evidence.contracts import TimeRef

RESERVED = frozenset(('', 'unknown', 'unavailable', 'unverified', 'legacy',
                      'legacy/unknown', 'legacy/unverified'))


def decimal(value):
    return Fraction(str(value))


def verified_bounds(value, clock):
    if (not isinstance(value,TimeRef) or value.clock_mapping_version!=clock
            or not isinstance(clock,str) or clock.strip()!=clock or clock.casefold() in RESERVED
            or value.order_status!='verified' or value.game_time_ms is None or value.uncertainty_ms is None):
        return None
    center,width=decimal(value.game_time_ms),decimal(value.uncertainty_ms)
    return center-width,center+width


def numeric_bound(value, *, upper):
    """Round a decimal rational outward in the requested direction for JSON."""
    value=decimal(value) if not isinstance(value,Fraction) else value
    if value.denominator==1:return value.numerator
    result=float(value)
    if not math.isfinite(result):raise ValueError('time interval exceeds finite numeric representation')
    if (decimal(result)<value if upper else decimal(result)>value):
        result=math.nextafter(result,math.inf if upper else -math.inf)
    if not math.isfinite(result):raise ValueError('time interval exceeds finite numeric representation')
    return result


def numeric_interval(interval, *, guaranteed):
    if interval is None:return None
    return [numeric_bound(interval[0],upper=guaranteed),
            numeric_bound(interval[1],upper=not guaranteed)]
