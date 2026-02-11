import time
import requests
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from config import (
    TICKERS,
    OHLC_API_BASE_URL,
    TIMEFRAMES,
    HOURLY_CHECK_INTERVAL,
    RETRY_INTERVAL,
    STALE_DATA_SECONDS,
)
from db import (
    fetch_latest_candle_with_indicators,
    check_connection as db_check_connection,
)
from binance_client import fetch_current_ohlc
from alerts.rules import run_all
from notifier.notifier import send_consolidated_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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


def is_data_stale(candle: Dict[str, Any]) -> bool:
    """True if the candle timestamp is older than STALE_DATA_SECONDS (UTC)."""
    ts = candle.get("timestamp")
    if ts is None:
        return True
    # DB returns timestamp without time zone (UTC)
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = (now - ts).total_seconds()
    return delta > STALE_DATA_SECONDS


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

    if is_data_stale(candle):
        logger.warning(f"Data for {ticker} {timeframe} is stale. Triggering update...")
        trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
        time.sleep(5)
        candle = fetch_latest_candle_with_indicators(ticker, timeframe)
        if not candle or is_data_stale(candle):
            logger.error(f"Data still stale for {ticker} {timeframe}")
            return

    current_ohlc = fetch_current_ohlc(ticker, timeframe)
    if not current_ohlc:
        logger.warning(f"No current OHLC from Binance for {ticker} {timeframe}")
        return

    try:
        alerts = run_all(current_ohlc, candle)
        for msg in alerts:
            logger.info(f"Alert {ticker} {timeframe}: {msg}")
        if alerts:
            send_consolidated_alert(
                ticker, alerts, current_ohlc.get("close"), timeframe
            )
    except Exception as e:
        logger.error(f"Error checking alerts for {ticker} {timeframe}: {e}")


def process_ticker(ticker: str) -> None:
    """Process one ticker across all timeframes; send one consolidated message per ticker."""
    logger.info(f"Processing ticker: {ticker}")
    all_alerts = []
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

            if is_data_stale(candle):
                logger.warning(f"Data for {ticker} {timeframe} is stale. Triggering update...")
                trigger_ohlc_update_symbol_timeframe(ticker, timeframe)
                time.sleep(5)
                candle = fetch_latest_candle_with_indicators(ticker, timeframe)
                if not candle or is_data_stale(candle):
                    continue

            for msg in run_all(current_ohlc, candle):
                all_alerts.append(f"[{timeframe.upper()}] {msg}")
        except Exception as e:
            logger.error(f"Error processing {ticker} {timeframe}: {e}")
        time.sleep(1)

    if all_alerts:
        send_consolidated_alert(ticker, all_alerts, current_price, "MULTI")


def main():
    logger.info("Starting alerts service...")
    logger.info(f"Tickers: {', '.join(TICKERS)}")
    logger.info(f"Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"Check interval: {HOURLY_CHECK_INTERVAL}s")
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
            time.sleep(HOURLY_CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Service stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info(f"Retrying in {RETRY_INTERVAL}s...")
            time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
