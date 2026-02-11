"""
Alert rules. Each rule is a function (current_ohlc, db_candle) -> str | None.
Register new rules in RULES; the monitor will run all of them without code changes.
"""

from typing import Optional, List

from config import PIVOT_THRESHOLD


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
        if level_value is None:
            continue
        try:
            if abs(close - level_value) / level_value <= threshold:
                formatted_price = f"${level_value:,.2f}"
                return f"Price within {pct}% of {level_name} at {formatted_price}"
        except (TypeError, ZeroDivisionError):
            continue
    return None


def _check_doji_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when the last closed candle pattern is Doji (from DB)."""
    if not db_candle:
        return None
    pattern = db_candle.get("candle_pattern")
    if not pattern or str(pattern).strip().upper() != "DOJI":
        return None
    return "Doji candle pattern on last closed candle"


# Register rules here. Monitor runs run_all(current_ohlc, db_candle) and sends any returned messages.
RULES = [
    _check_pivot_alert,
    _check_doji_alert,
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
