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
)
from .db import (
    fetch_latest_candle_with_indicators,
    check_connection as db_check_connection,
)
from .binance_client import fetch_current_ohlc
from .alerts.rules import run_all, DOJI_ALERT_MESSAGE
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


def process_ticker_timeframe(ticker: str, timeframe: str) -> None:
    """Fetch latest candle from DB; if missing/stale trigger OHLC update; then run alerts."""
    logger.info(f"Processing {ticker} {timeframe}")

    candle = fetch_latest_candle_with_indicators(ticker, timeframe)
    if not candle:
        logger.warning(f"No data for {ticker} {timeframe}. Triggering update...")
        trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
        time.sleep(5)
        candle = fetch_latest_candle_with_indicators(ticker, timeframe)
        if not candle:
            logger.error(f"Still no data for {ticker} {timeframe}")
            return

    if is_data_stale(candle, timeframe):
        logger.warning(f"Data for {ticker} {timeframe} is stale. Triggering update...")
        trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
        time.sleep(5)
        candle = fetch_latest_candle_with_indicators(ticker, timeframe)
        if not candle or is_data_stale(candle, timeframe):
            logger.error(f"Data still stale for {ticker} {timeframe}")
            return

    current_ohlc = fetch_current_ohlc(ticker, timeframe)
    if not current_ohlc:
        logger.warning(f"No current OHLC from Binance for {ticker} {timeframe}")
        return

    try:
        alerts = run_all(current_ohlc, candle)
        alerts = _filter_doji_dedupe(ticker, timeframe, candle, alerts)
        for msg in alerts:
            logger.info(f"Alert {ticker} {timeframe}: {msg}")
        if alerts:
            send_consolidated_alert(
                ticker, alerts, current_ohlc.get("close"), timeframe
            )
    except Exception as e:
        logger.error(f"Error checking alerts for {ticker} {timeframe}: {e}")


def process_ticker(ticker: str) -> None:
    """Process one ticker across all timeframes; send one consolidated message per ticker (respecting per-TF cooldown)."""
    logger.info(f"Processing ticker: {ticker}")
    timeframe_alerts = []  # (timeframe, msg)
    current_price = None

    for timeframe in TIMEFRAMES:
        try:
            candle = fetch_latest_candle_with_indicators(ticker, timeframe)
            if not candle:
                logger.warning(f"No data for {ticker} {timeframe}. Triggering update...")
                trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
                time.sleep(5)
                candle = fetch_latest_candle_with_indicators(ticker, timeframe)
                if not candle:
                    logger.error(f"No data for {ticker} {timeframe}")
                    continue

            current_ohlc = fetch_current_ohlc(ticker, timeframe)
            if not current_ohlc:
                logger.warning(f"No current OHLC from Binance for {ticker} {timeframe}")
                time.sleep(1)
                continue
            if current_price is None:
                current_price = current_ohlc.get("close")

            if is_data_stale(candle, timeframe):
                logger.warning(f"Data for {ticker} {timeframe} is stale. Triggering update...")
                trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
                time.sleep(5)
                candle = fetch_latest_candle_with_indicators(ticker, timeframe)
                if not candle or is_data_stale(candle, timeframe):
                    continue

            alerts = run_all(current_ohlc, candle)
            alerts = _filter_doji_dedupe(ticker, timeframe, candle, alerts)
            for msg in alerts:
                timeframe_alerts.append((timeframe, msg))
        except Exception as e:
            logger.error(f"Error processing {ticker} {timeframe}: {e}")
        time.sleep(1)

    if timeframe_alerts:
        now_utc = datetime.now(timezone.utc)
        all_alerts, timeframes_sent = _apply_cooldown(ticker, timeframe_alerts, now_utc)
        if all_alerts:
            send_consolidated_alert(ticker, all_alerts, current_price, "MULTI")
            for tf in timeframes_sent:
                _last_alert_sent[(ticker, tf)] = now_utc


def main():
    logger.info("Starting alerts service...")
    logger.info(f"Tickers: {', '.join(TICKERS)}")
    logger.info(f"Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"Check interval: {CHECK_INTERVAL}s")
    logger.info(f"OHLC API: {OHLC_API_BASE_URL}")

    if not db_check_connection():
        logger.error("Database connection failed. Check DB_* env vars.")
        return

    while True:
        try:
            logger.info("Starting check...")
            for ticker in TICKERS:
                try:
                    process_ticker(ticker)
                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}")
                time.sleep(2)
            logger.info("Check completed. Waiting for next run...")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Service stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info(f"Retrying in {RETRY_INTERVAL}s...")
            time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
