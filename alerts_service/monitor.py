import time
import requests
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from .config import (
    TICKERS,
    OHLC_API_BASE_URL,
    TIMEFRAMES,
    CHECK_INTERVAL,
    RETRY_INTERVAL,
    STALE_DATA_SECONDS_BY_TIMEFRAME,
    STALE_DATA_SECONDS_DEFAULT,
    ALERT_COOLDOWN_SECONDS,
    CANDLE_PATTERN_CHECK_INTERVAL,
    is_within_1_min_after_close,
)
from .db import (
    fetch_latest_candle_with_indicators,
    check_connection as db_check_connection,
    get_db_config,
)
from .binance_client import fetch_current_ohlc
from .alerts.rules import run_price_rules, run_candle_pattern_rules, DOJI_ALERT_MESSAGE
from .notifier.notifier import send_consolidated_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Doji: alert only once per closed candle (ticker, timeframe, candle timestamp)
_doji_alerted: set = set()

# Per (ticker, timeframe): last time we sent any alert (UTC). Used for cooldown.
_last_alert_sent: Dict[tuple, datetime] = {}


def _apply_cooldown(ticker: str, timeframe_alerts: list, now_utc: datetime):
    """
    Keep only (timeframe, msg) for which cooldown has passed.
    Returns (list of '[TF] msg' strings, set of timeframes included).
    Caller should set _last_alert_sent[(ticker, tf)] = now_utc for each tf in the set after sending.
    """
    allowed = []
    timeframes_sent = set()
    for tf, msg in timeframe_alerts:
        key = (ticker, tf)
        last = _last_alert_sent.get(key)
        cooldown = ALERT_COOLDOWN_SECONDS.get(tf, 24 * 3600)
        if last is None or (now_utc - last).total_seconds() >= cooldown:
            allowed.append(f"[{tf.upper()}] {msg}")
            timeframes_sent.add(tf)
    return allowed, timeframes_sent


def _filter_doji_dedupe(ticker: str, timeframe: str, candle: Dict[str, Any], alerts: list) -> list:
    """Remove Doji alert if we already sent for this closed candle."""
    key = (ticker, timeframe, candle.get("timestamp"))
    if key in _doji_alerted:
        return [a for a in alerts if a != DOJI_ALERT_MESSAGE]
    if DOJI_ALERT_MESSAGE in alerts:
        _doji_alerted.add(key)
    return alerts


def trigger_ohlc_update_timeframe(timeframe: str) -> bool:
    """POST /timeframe/{timeframe}/update — update all symbols for one timeframe."""
    url = f"{OHLC_API_BASE_URL}/timeframe/{timeframe}/update"
    try:
        response = requests.post(url, timeout=120)
        if response.status_code == 200:
            logger.info(f"Triggered OHLC update for timeframe {timeframe}")
            return True
        logger.warning(f"OHLC update {timeframe}: HTTP {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"OHLC update {timeframe}: {e}")
        return False


def trigger_ohlc_update_symbol_timeframe(symbol: str, timeframe: str) -> bool:
    """POST /update/{symbol}/{timeframe} — update one symbol + timeframe."""
    url = f"{OHLC_API_BASE_URL}/update/{symbol}/{timeframe}"
    try:
        response = requests.post(url, timeout=120)
        if response.status_code == 200:
            logger.info(f"Triggered OHLC update for {symbol} {timeframe}")
            return True
        logger.warning(f"OHLC update {symbol} {timeframe}: HTTP {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"OHLC update {symbol} {timeframe}: {e}")
        return False


def is_data_stale(candle: Dict[str, Any], timeframe: Optional[str] = None) -> bool:
    """True if the candle timestamp is older than the staleness threshold for this timeframe (UTC)."""
    ts = candle.get("timestamp")
    if ts is None:
        return True
    tf = timeframe or candle.get("timeframe")
    threshold = (
        STALE_DATA_SECONDS_BY_TIMEFRAME.get(tf, STALE_DATA_SECONDS_DEFAULT)
        if tf
        else STALE_DATA_SECONDS_DEFAULT
    )
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = (now - ts).total_seconds()
    return delta > threshold


def _ensure_candle(ticker: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Fetch latest candle; trigger update if missing/stale and retry once. Return candle or None."""
    candle = fetch_latest_candle_with_indicators(ticker, timeframe)
    if not candle:
        logger.warning(f"No data for {ticker} {timeframe}. Triggering update...")
        trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
        time.sleep(5)
        candle = fetch_latest_candle_with_indicators(ticker, timeframe)
        if not candle:
            return None
    if is_data_stale(candle, timeframe):
        logger.warning(f"Data for {ticker} {timeframe} is stale. Triggering update...")
        trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
        time.sleep(5)
        candle = fetch_latest_candle_with_indicators(ticker, timeframe)
        if not candle or is_data_stale(candle, timeframe):
            return None
    return candle


def process_ticker_price_1h(ticker: str) -> None:
    """Price pass: 1H only. Pivot + EMA. Run every CHECK_INTERVAL (e.g. 5 min)."""
    timeframe = "1h"
    candle = _ensure_candle(ticker, timeframe)
    if not candle:
        return
    current_ohlc = fetch_current_ohlc(ticker, timeframe)
    if not current_ohlc:
        return
    try:
        alerts = run_price_rules(current_ohlc, candle)
        if not alerts:
            return
        now_utc = datetime.now(timezone.utc)
        timeframe_alerts = [(timeframe, msg) for msg in alerts]
        all_alerts, timeframes_sent = _apply_cooldown(ticker, timeframe_alerts, now_utc)
        if all_alerts:
            send_consolidated_alert(ticker, all_alerts, current_ohlc.get("close"), "MULTI")
            for tf in timeframes_sent:
                _last_alert_sent[(ticker, tf)] = now_utc
    except Exception as e:
        logger.error(f"Error price rules {ticker} {timeframe}: {e}")


def process_ticker_candle_pattern(ticker: str) -> None:
    """Candle-pattern pass: all TFs where we're within 1 min after candle close. Doji etc. Run every CANDLE_PATTERN_CHECK_INTERVAL."""
    timeframe_alerts = []
    current_price = None
    for timeframe in TIMEFRAMES:
        if not is_within_1_min_after_close(timeframe):
            continue
        try:
            candle = _ensure_candle(ticker, timeframe)
            if not candle:
                continue
            current_ohlc = fetch_current_ohlc(ticker, timeframe)
            if not current_ohlc:
                time.sleep(1)
                continue
            if current_price is None:
                current_price = current_ohlc.get("close")
            alerts = run_candle_pattern_rules(current_ohlc, candle)
            alerts = _filter_doji_dedupe(ticker, timeframe, candle, alerts)
            for msg in alerts:
                timeframe_alerts.append((timeframe, msg))
        except Exception as e:
            logger.error(f"Error candle pattern {ticker} {timeframe}: {e}")
        time.sleep(1)
    if timeframe_alerts:
        now_utc = datetime.now(timezone.utc)
        all_alerts, timeframes_sent = _apply_cooldown(ticker, timeframe_alerts, now_utc)
        if all_alerts:
            send_consolidated_alert(ticker, all_alerts, current_price or 0, "MULTI")
            for tf in timeframes_sent:
                _last_alert_sent[(ticker, tf)] = now_utc


def main():
    logger.info("Starting alerts service...")
    logger.info(f"Tickers: {', '.join(TICKERS)}")
    logger.info(f"Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"Price pass (1H): every {CHECK_INTERVAL}s. Candle pattern: every {CANDLE_PATTERN_CHECK_INTERVAL}s, 1 min after close.")
    logger.info(f"OHLC API: {OHLC_API_BASE_URL}")
    logger.info(f"DB host: {get_db_config().get('host', '?')}")

    if not db_check_connection():
        logger.error("Database connection failed. Check DB_* env vars.")
        return

    last_price_pass = time.time()  # Skip price pass on startup; first run after CHECK_INTERVAL
    while True:
        try:
            now = time.time()
            # Candle-pattern pass: every 1 min, only for TFs in the 1-min-after-close window
            for ticker in TICKERS:
                try:
                    process_ticker_candle_pattern(ticker)
                except Exception as e:
                    logger.error(f"Error candle pattern {ticker}: {e}")
                time.sleep(2)
            # Price pass (1H pivot + EMA): every CHECK_INTERVAL
            if now - last_price_pass >= CHECK_INTERVAL:
                last_price_pass = now
                for ticker in TICKERS:
                    try:
                        process_ticker_price_1h(ticker)
                    except Exception as e:
                        logger.error(f"Error price pass {ticker}: {e}")
                    time.sleep(2)
            time.sleep(CANDLE_PATTERN_CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Service stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info(f"Retrying in {RETRY_INTERVAL}s...")
            time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
