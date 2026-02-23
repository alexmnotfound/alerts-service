"""
Alert rules. Each rule is a function (current_ohlc, db_candle) -> str | None.
Register new rules in RULES; the monitor runs all of them without code changes.

Contract (for current and future indicators: OBV, RSI, etc.):
- current_ohlc: live OHLC from Binance (current price = close). Fetched every check cycle.
- db_candle: last CLOSED candle for this timeframe (1H, 4H, etc.) with fixed indicators
  from the DB (pivot, EMA, RSI, OBV, candle_pattern, etc.). Each timeframe is evaluated
  separately: we compare current price to that timeframe's fixed indicator values.
"""

from datetime import datetime, timezone
from typing import Optional, List

from ..config import PIVOT_THRESHOLD, CANDLE_PATTERN_GRACE_AFTER_CLOSE

# Doji message (used by monitor for dedupe: one alert per closed candle)
DOJI_ALERT_MESSAGE = "Doji candle pattern on last closed candle"


def _candle_just_closed(db_candle) -> bool:
    """True if the candle close time is within the grace window (1 min after close)."""
    ts = db_candle.get("timestamp")
    if ts is None:
        return False
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_seconds = (now - ts).total_seconds()
    return 0 <= age_seconds <= CANDLE_PATTERN_GRACE_AFTER_CLOSE


def _check_pivot_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when current price is within PIVOT_THRESHOLD of any monthly pivot level. Only on 1H timeframe."""
    tf = (db_candle or {}).get("timeframe") or ""
    if str(tf).strip().lower() != "1h":
        return None
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
    """Alert when the candle that just closed (this timeframe) has Doji. Only at close: within grace window."""
    if not db_candle:
        return None
    if not _candle_just_closed(db_candle):
        return None
    pattern = db_candle.get("candle_pattern")
    if not pattern or str(pattern).strip().upper() != "DOJI":
        return None
    return DOJI_ALERT_MESSAGE


# EMA50/EMA200 on 1h, 4h, 1d, 1M
EMA_TIMEFRAMES = ("1h", "4h", "1d", "1M")
EMA_PERIODS = (50, 200)
EMA_CLOSE_TOLERANCE = 0.01  # 1%: alert when price close is within 1% of EMA


def _check_ema_50_200_alert(current_ohlc, db_candle) -> Optional[str]:
    """Alert when price close is within 1% of EMA50/200, or touches/crosses. For 1h, 4h, 1d, 1M."""
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
        if ema_value <= 0:
            continue
        try:
            distance = abs(close - ema_value) / abs(ema_value)
        except (TypeError, ZeroDivisionError):
            continue
        # Only send any EMA alert when price is within 1% of the EMA
        if distance > EMA_CLOSE_TOLERANCE:
            continue
        if low <= ema_value <= high:
            if close > ema_value:
                return f"Price touched and is above EMA{period}"
            if close < ema_value:
                return f"Price touched and is below EMA{period}"
            return f"Price touched EMA{period}"
        # Within 1% but candle range did not touch EMA: say "near" / "above/below", not "crossed"
        if close > ema_value:
            return f"Price above EMA{period} (within 1%)"
        if close < ema_value:
            return f"Price below EMA{period} (within 1%)"
        return f"Price within 1% of EMA{period} at ${ema_value:,.2f}"
    return None


# Price rules: pivot (1H only) + EMA. Run on 1H every 5 min.
RULES_PRICE = [_check_pivot_alert, _check_ema_50_200_alert]
# Candle pattern rules: only at close (1 min after). Run for all TFs when in that window.
RULES_CANDLE_PATTERN = [_check_doji_alert]


def _run_rules(current_ohlc, db_candle, rules: list) -> List[str]:
    alerts = []
    for rule in rules:
        try:
            msg = rule(current_ohlc, db_candle)
            if msg and msg not in alerts:
                alerts.append(msg)
        except Exception:
            continue
    return alerts


def run_price_rules(current_ohlc, db_candle) -> List[str]:
    """Pivot + EMA only. Used for 1H every 5 min."""
    return _run_rules(current_ohlc, db_candle, RULES_PRICE)


def run_candle_pattern_rules(current_ohlc, db_candle) -> List[str]:
    """Doji etc. Only when candle just closed (1 min after). Used for all TFs in at-close pass."""
    return _run_rules(current_ohlc, db_candle, RULES_CANDLE_PATTERN)


def run_all(current_ohlc, db_candle) -> List[str]:
    """Run all rules (legacy). Prefer run_price_rules / run_candle_pattern_rules."""
    return _run_rules(current_ohlc, db_candle, RULES_PRICE + RULES_CANDLE_PATTERN)
