"""Pivot retest alert detection — mirrors PivotRetestShort/Long backtesting strategies."""
from __future__ import annotations

from collections import deque
from typing import Optional

_CE_MULTIPLIER = 3.0  # ATR is stored as ATR*3 in ce_data.atr_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sorted_levels(pivot: dict) -> list:
    out = []
    for k in ("s5", "s4", "s3", "s2", "s1", "pp", "r1", "r2", "r3", "r4", "r5"):
        v = pivot.get(k) or pivot.get(k.upper())
        if v is not None:
            out.append(float(v))
    out.sort()
    return out


def _level_name(lvl: float, pivot: dict) -> str:
    for k in ("s5", "s4", "s3", "s2", "s1", "pp", "r1", "r2", "r3", "r4", "r5"):
        v = pivot.get(k) or pivot.get(k.upper())
        if v is not None and abs(float(v) - lvl) < 1e-6:
            return k.upper()
    return f"{lvl:.2f}"


def _month_key(ts) -> int:
    try:
        return ts.year * 100 + ts.month
    except AttributeError:
        return -1


def _get_pivot(candle: dict) -> Optional[dict]:
    return candle.get("indicators", {}).get("pivot")


def _get_atr(candle: dict) -> Optional[float]:
    ce = candle.get("indicators", {}).get("ce")
    if ce is None:
        return None
    raw = ce.get("atr_value")
    if raw is None:
        return None
    return float(raw) / _CE_MULTIPLIER


# ---------------------------------------------------------------------------
# detect_pivot_retest_short
# ---------------------------------------------------------------------------

def detect_pivot_retest_short(
    candles: list,
    vol_mult: float = 1.5,
    wick_min_atr: float = 0.3,
    vol_sma_period: int = 20,
) -> Optional[str]:
    """Return alert string if the last candle is a pivot retest short entry, else None."""
    if len(candles) < 2:
        return None

    last = candles[-1]
    pivot_last = _get_pivot(last)
    atr_last = _get_atr(last)
    if pivot_last is None or atr_last is None:
        return None

    vol_hist: deque = deque(maxlen=vol_sma_period)
    broken: dict = {}   # level -> {"atr": float, "pivot": dict, "bars_since": int}
    prev_close: Optional[float] = None
    current_month: int = -1

    for candle in candles[:-1]:
        ts = candle.get("timestamp")
        mk = _month_key(ts)
        if mk != current_month:
            broken = {}
            current_month = mk

        close = float(candle["close"])
        volume = float(candle["volume"])
        vol_hist.append(volume)
        vol_sma = sum(vol_hist) / len(vol_hist) if vol_hist else 0.0
        vol_pass = volume > vol_mult * vol_sma

        pivot = _get_pivot(candle)
        atr = _get_atr(candle)

        if pivot is not None and atr is not None and prev_close is not None:
            for lvl in _sorted_levels(pivot):
                if close < lvl and prev_close >= lvl and vol_pass:
                    if lvl not in broken:
                        broken[lvl] = {"atr": atr, "pivot": pivot, "bars_since": 0}

        for lvl in list(broken):
            broken[lvl]["bars_since"] = broken[lvl].get("bars_since", 0) + 1

        prev_close = close

    # Check last candle for retest
    high = float(last["high"])
    open_ = float(last["open"])
    close_last = float(last["close"])

    for lvl, info in broken.items():
        atr = info["atr"]
        upper_wick = high - max(open_, close_last)
        if high >= lvl and close_last < lvl and upper_wick >= atr * wick_min_atr:
            name = _level_name(lvl, info["pivot"])
            return (
                f"Pivot Retest SHORT — {name} @ {lvl:,.2f} "
                f"| wick {upper_wick:.2f} | atr {atr:.2f}"
            )

    return None


# ---------------------------------------------------------------------------
# detect_pivot_retest_long
# ---------------------------------------------------------------------------

def detect_pivot_retest_long(
    candles: list,
    vol_mult: float = 1.5,
    wick_min_atr: float = 0.3,
    vol_sma_period: int = 20,
) -> Optional[str]:
    """Return alert string if the last candle is a pivot retest long entry, else None."""
    if len(candles) < 2:
        return None

    last = candles[-1]
    pivot_last = _get_pivot(last)
    atr_last = _get_atr(last)
    if pivot_last is None or atr_last is None:
        return None

    vol_hist: deque = deque(maxlen=vol_sma_period)
    broken: dict = {}   # level -> {"atr": float, "pivot": dict, "bars_since": int}
    prev_close: Optional[float] = None
    current_month: int = -1

    for candle in candles[:-1]:
        ts = candle.get("timestamp")
        mk = _month_key(ts)
        if mk != current_month:
            broken = {}
            current_month = mk

        close = float(candle["close"])
        volume = float(candle["volume"])
        vol_hist.append(volume)
        vol_sma = sum(vol_hist) / len(vol_hist) if vol_hist else 0.0
        vol_pass = volume > vol_mult * vol_sma

        pivot = _get_pivot(candle)
        atr = _get_atr(candle)

        if pivot is not None and atr is not None and prev_close is not None:
            for lvl in _sorted_levels(pivot):
                if close > lvl and prev_close <= lvl and vol_pass:
                    if lvl not in broken:
                        broken[lvl] = {"atr": atr, "pivot": pivot, "bars_since": 0}

        for lvl in list(broken):
            broken[lvl]["bars_since"] = broken[lvl].get("bars_since", 0) + 1

        prev_close = close

    # Check last candle for retest
    low = float(last["low"])
    open_ = float(last["open"])
    close_last = float(last["close"])

    for lvl, info in broken.items():
        atr = info["atr"]
        lower_wick = min(open_, close_last) - low
        if low <= lvl and close_last > lvl and lower_wick >= atr * wick_min_atr:
            name = _level_name(lvl, info["pivot"])
            return (
                f"Pivot Retest LONG — {name} @ {lvl:,.2f} "
                f"| wick {lower_wick:.2f} | atr {atr:.2f}"
            )

    return None
