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
# Private shared implementation
# ---------------------------------------------------------------------------

def _detect_pivot_retest(
    candles,
    direction: str,  # "short" or "long"
    vol_mult: float,
    wick_min_atr: float,
    vol_sma_period: int,
) -> Optional[str]:
    if len(candles) < 2:
        return None

    vol_hist: deque = deque(maxlen=vol_sma_period)
    broken: dict = {}
    prev_close: Optional[float] = None
    month_key = -1

    for candle in candles[:-1]:
        close = float(candle["close"])
        volume = float(candle.get("volume") or 0.0)
        ts = candle.get("timestamp")
        vol_hist.append(volume)

        mk = _month_key(ts)
        if mk != month_key:
            broken = {}
            month_key = mk

        pivot = _get_pivot(candle)
        atr = _get_atr(candle)
        if pivot is None or atr is None:
            prev_close = close
            continue

        levels = _sorted_levels(pivot)
        vol_sma = sum(vol_hist) / len(vol_hist) if vol_hist else 0.0
        vol_pass = vol_sma > 0 and volume > vol_sma * vol_mult

        if prev_close is not None and vol_pass:
            for lvl in levels:
                if lvl not in broken:
                    if direction == "short" and close < lvl and prev_close >= lvl:
                        broken[lvl] = {"atr": atr, "pivot": pivot}
                    elif direction == "long" and close > lvl and prev_close <= lvl:
                        broken[lvl] = {"atr": atr, "pivot": pivot}

        prev_close = close

    # Check last candle
    last = candles[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    open_ = float(last["open"])
    pivot = _get_pivot(last)
    atr = _get_atr(last)
    if pivot is None or atr is None:
        return None

    levels = _sorted_levels(pivot)

    if direction == "short":
        upper_wick = high - max(open_, close)
        for lvl in levels:
            if lvl not in broken:
                continue
            if high >= lvl and close < lvl and upper_wick >= atr * wick_min_atr:
                name = _level_name(lvl, pivot)
                return f"Pivot Retest SHORT — {name} @ {lvl:,.2f} | wick {upper_wick:.2f} | atr {atr:.2f}"
    else:
        lower_wick = min(open_, close) - low
        for lvl in levels:
            if lvl not in broken:
                continue
            if low <= lvl and close > lvl and lower_wick >= atr * wick_min_atr:
                name = _level_name(lvl, pivot)
                return f"Pivot Retest LONG — {name} @ {lvl:,.2f} | wick {lower_wick:.2f} | atr {atr:.2f}"

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_pivot_retest_short(candles, vol_mult=1.5, wick_min_atr=0.3, vol_sma_period=20):
    return _detect_pivot_retest(candles, "short", vol_mult, wick_min_atr, vol_sma_period)


def detect_pivot_retest_long(candles, vol_mult=1.5, wick_min_atr=0.3, vol_sma_period=20):
    return _detect_pivot_retest(candles, "long", vol_mult, wick_min_atr, vol_sma_period)
