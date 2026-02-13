"""
Alert rules. Each rule is a function (current_ohlc, db_candle) -> str | None.
Register new rules in RULES; the monitor runs all of them without code changes.

Contract (for current and future indicators: OBV, RSI, etc.):
- current_ohlc: live OHLC from Binance (current price = close). Fetched every check cycle.
- db_candle: last CLOSED candle for this timeframe (1H, 4H, etc.) with fixed indicators
  from the DB (pivot, EMA, RSI, OBV, candle_pattern, etc.). Each timeframe is evaluated
  separately: we compare current price to that timeframe's fixed indicator values.
"""

from typing import Optional, List

from ..config import PIVOT_THRESHOLD

# Doji message (used by monitor for dedupe: one alert per closed candle)
DOJI_ALERT_MESSAGE = "Doji candle pattern on last closed candle"


def _check_pivot_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when current price is within PIVOT_THRESHOLD of any monthly pivot level."""
    close = current_ohlc.get("close") if current_ohlc else None
    if close is None:
        return None
    indicators = (db_candle or {}).get("indicators") or {}
    pivot = indicators.get("pivot")
    if not pivot:
        return None
    threshold = PIVOT_THRESHOLD
    pct = int(threshold * 100)
    for level_name, level_value in pivot.items():
        if level_value is None or level_value <= 0:
            continue
        try:
            distance = abs(close - level_value) / abs(level_value)
            if distance <= threshold:
                formatted_price = f"${level_value:,.2f}"
                return f"Price within {pct}% of {level_name} at {formatted_price}"
        except (TypeError, ZeroDivisionError):
            continue
    return None


def _check_doji_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when the last closed candle (this timeframe) has Doji pattern. Evaluated at close only."""
    if not db_candle:
        return None
    pattern = db_candle.get("candle_pattern")
    if not pattern or str(pattern).strip().upper() != "DOJI":
        return None
    return DOJI_ALERT_MESSAGE


# EMA50/EMA200 only on 4h, 1d, 1M (per your config)
EMA_TIMEFRAMES = ("4h", "1d", "1M")
EMA_PERIODS = (50, 200)


def _check_ema_50_200_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when current price touches or crosses EMA50 or EMA200. Only for 4h, 1d, 1M."""
    if not current_ohlc or not db_candle:
        return None
    tf = (db_candle.get("timeframe") or "").strip().lower()
    if tf not in EMA_TIMEFRAMES:
        return None
    close = current_ohlc.get("close")
    high = current_ohlc.get("high")
    low = current_ohlc.get("low")
    if close is None or high is None or low is None:
        return None
    ema = (db_candle.get("indicators") or {}).get("ema")
    if not ema:
        return None
    for period in EMA_PERIODS:
        key = str(period)
        if key not in ema or ema[key] is None:
            continue
        ema_value = ema[key]
        if low <= ema_value <= high:
            if close > ema_value:
                return f"Price touched and closed above EMA{period}"
            if close < ema_value:
                return f"Price touched and closed below EMA{period}"
            return f"Price touched EMA{period}"
        if close > ema_value:
            return f"Price crossed above EMA{period}"
        if close < ema_value:
            return f"Price crossed below EMA{period}"
    return None


# Register rules here. Monitor runs run_all(current_ohlc, db_candle) and sends any returned messages.
RULES = [
    _check_pivot_alert,
    _check_doji_alert,
    _check_ema_50_200_alert,
]


def run_all(current_ohlc, db_candle) -> List[str]:
    """Run all registered rules. Returns list of alert messages (no duplicates, order preserved)."""
    alerts = []
    for rule in RULES:
        try:
            msg = rule(current_ohlc, db_candle)
            if msg and msg not in alerts:
                alerts.append(msg)
        except Exception:
            continue
    return alerts
