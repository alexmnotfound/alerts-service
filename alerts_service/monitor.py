import time
import requests
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

from .config import (
    TICKERS,
    OHLC_API_BASE_URL,
    TIMEFRAMES,
    PRICE_PASS_TIMEFRAMES,
    CHECK_INTERVAL,
    RETRY_INTERVAL,
    STALE_DATA_SECONDS_BY_TIMEFRAME,
    STALE_DATA_SECONDS_DEFAULT,
    ALERT_COOLDOWN_SECONDS,
    CANDLE_PATTERN_CHECK_INTERVAL,
    CANDLE_PATTERN_TIMEFRAMES,
    is_within_1_min_after_close,
)
from .db import (
    fetch_latest_candle_with_indicators,
    fetch_latest_candles_batch,
    fetch_recent_candles_with_indicators,
    check_connection as db_check_connection,
    get_db_config,
)
from .alerts.pivot_retest import detect_pivot_retest_short, detect_pivot_retest_long
from .binance_client import fetch_all_prices, fetch_current_ohlc
from .alerts.rules import (
    run_price_rules,
    run_candle_pattern_rules,
    DOJI_ALERT_MESSAGE,
    TWEEZER_TOP_ALERT_MESSAGE,
    TWEEZER_BOTTOM_ALERT_MESSAGE,
)
from .notifier.notifier import send_consolidated_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Candle patterns: alert only once per closed candle (ticker, timeframe, candle timestamp)
_candle_pattern_alerted: set = set()
CANDLE_PATTERN_RULE_IDS = frozenset({"doji", "tweezer_top", "tweezer_bottom"})

# Per (ticker, timeframe, rule_id): last time we sent this alert type (UTC). Cooldown is per rule.
_last_alert_sent: Dict[tuple, datetime] = {}


def _apply_cooldown(ticker: str, timeframe_alerts: list, now_utc: datetime):
    """
    timeframe_alerts: [(tf, msg, rule_id), ...].
    Keep only entries for which cooldown has passed for that (ticker, tf, rule_id).
    Returns (list of '[TF] msg' strings, set of (tf, rule_id) that were allowed).
    Caller sets _last_alert_sent[(ticker, tf, rule_id)] = now_utc for each allowed (tf, rule_id) after sending.
    """
    allowed = []
    sent_keys = set()
    for tf, msg, rule_id in timeframe_alerts:
        key = (ticker, tf, rule_id)
        last = _last_alert_sent.get(key)
        cooldown = ALERT_COOLDOWN_SECONDS.get(tf, 24 * 3600)
        if last is None or (now_utc - last).total_seconds() >= cooldown:
            # Pivot is monthly, same for all TFs; don't add timeframe prefix
            allowed.append(msg if rule_id == "pivot" else f"[{tf.upper()}] {msg}")
            sent_keys.add((tf, rule_id))
    return allowed, sent_keys


def _filter_candle_pattern_dedupe(ticker: str, timeframe: str, candle: Dict[str, Any], alerts: list) -> list:
    """One alert per closed candle for candle patterns. If we already sent for this candle, drop pattern alerts. alerts: [(msg, rule_id), ...]."""
    key = (ticker, timeframe, candle.get("timestamp"))
    if key in _candle_pattern_alerted:
        return [(m, rid) for m, rid in alerts if rid not in CANDLE_PATTERN_RULE_IDS]
    if any(rid in CANDLE_PATTERN_RULE_IDS for _, rid in alerts):
        _candle_pattern_alerted.add(key)
    return alerts


def trigger_ohlc_update_timeframe(timeframe: str) -> bool:
    """POST /timeframe/{timeframe}/update — update all symbols for one timeframe."""
    url = f"{OHLC_API_BASE_URL}/timeframe/{timeframe}/update"
    try:
        response = requests.post(url, timeout=240)
        if response.status_code == 200:
            logger.info(f"Triggered OHLC update for timeframe {timeframe}")
            return True
        logger.warning(f"OHLC update {timeframe}: HTTP {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"OHLC update {timeframe}: {e}")
        return False


def trigger_ohlc_update_symbol_timeframe(symbol: str, timeframe: str) -> bool:
    """POST /update/{symbol}/{timeframe} — update one symbol + timeframe."""
    url = f"{OHLC_API_BASE_URL}/update/{symbol}/{timeframe}"
    try:
        response = requests.post(url, timeout=240)
        if response.status_code == 200:
            logger.info(f"Triggered OHLC update for {symbol} {timeframe}")
            return True
        logger.warning(f"OHLC update {symbol} {timeframe}: HTTP {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"OHLC update {symbol} {timeframe}: {e}")
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


def _build_candles_map_with_fallback(
    pairs: list,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Batch-fetch candles. Trigger one OHLC update per stale timeframe, then re-fetch once."""
    candles_map = fetch_latest_candles_batch(pairs)

    stale_timeframes = {
        timeframe
        for ticker, timeframe in pairs
        if not candles_map.get((ticker, timeframe)) or is_data_stale(candles_map.get((ticker, timeframe)), timeframe)
    }

    if stale_timeframes:
        for timeframe in stale_timeframes:
            logger.warning(f"Stale/missing data for timeframe {timeframe}. Triggering bulk update...")
            trigger_ohlc_update_timeframe(timeframe)
        time.sleep(5)
        candles_map = fetch_latest_candles_batch(pairs)

    return candles_map


def _run_price_pass(prices: Dict[str, float]) -> None:
    """Price rules for all tickers/timeframes: EMA200 + SMMA99.
    One batch DB fetch + pre-fetched prices dict (no per-ticker Binance calls).
    """
    pairs = [(t, tf) for t in TICKERS for tf in PRICE_PASS_TIMEFRAMES]
    candles_map = _build_candles_map_with_fallback(pairs)

    now_utc = datetime.now(timezone.utc)
    for ticker in TICKERS:
        price = prices.get(ticker)
        if not price:
            continue
        current_ohlc = {"open": price, "high": price, "low": price, "close": price, "volume": None}
        timeframe_alerts = []
        for timeframe in PRICE_PASS_TIMEFRAMES:
            candle = candles_map.get((ticker, timeframe))
            if not candle:
                continue
            try:
                alerts = run_price_rules(current_ohlc, candle)
                for msg, rule_id in alerts:
                    timeframe_alerts.append((timeframe, msg, rule_id))
            except Exception as e:
                logger.error(f"Error price rules {ticker} {timeframe}: {e}")

        if timeframe_alerts:
            all_alerts, sent_keys = _apply_cooldown(ticker, timeframe_alerts, now_utc)
            if all_alerts:
                send_consolidated_alert(ticker, all_alerts, price, "MULTI")
                for tf, rule_id in sent_keys:
                    _last_alert_sent[(ticker, tf, rule_id)] = now_utc


def _run_candle_pattern_pass(prices: Dict[str, float]) -> None:
    """Candle-pattern rules (Doji, Tweezer) for timeframes currently within 1 min of close.
    One batch DB fetch + pre-fetched prices dict (no per-ticker Binance calls).
    """
    active_tfs = [tf for tf in CANDLE_PATTERN_TIMEFRAMES if is_within_1_min_after_close(tf)]
    if not active_tfs:
        return

    pairs = [(t, tf) for t in TICKERS for tf in active_tfs]
    candles_map = _build_candles_map_with_fallback(pairs)

    now_utc = datetime.now(timezone.utc)
    for ticker in TICKERS:
        price = prices.get(ticker)
        if not price:
            continue
        current_ohlc = {"open": price, "high": price, "low": price, "close": price, "volume": None}
        timeframe_alerts = []
        for timeframe in active_tfs:
            candle = candles_map.get((ticker, timeframe))
            if not candle:
                continue
            try:
                alerts = run_candle_pattern_rules(current_ohlc, candle)
                alerts = _filter_candle_pattern_dedupe(ticker, timeframe, candle, alerts)
                for msg, rule_id in alerts:
                    timeframe_alerts.append((timeframe, msg, rule_id))
            except Exception as e:
                logger.error(f"Error candle pattern {ticker} {timeframe}: {e}")

        if timeframe_alerts:
            all_alerts, sent_keys = _apply_cooldown(ticker, timeframe_alerts, now_utc)
            if all_alerts:
                send_consolidated_alert(ticker, all_alerts, price, "MULTI")
                for tf, rule_id in sent_keys:
                    _last_alert_sent[(ticker, tf, rule_id)] = now_utc


PIVOT_RETEST_LOOKBACK = 50  # 1h candles (~2 days of history for breakdown detection)


def process_ticker_pivot_retest(ticker: str) -> None:
    """Pivot retest pass: runs after each 1h close. Replays breakdown logic over last 50 candles."""
    try:
        candles = fetch_recent_candles_with_indicators(ticker, "1h", limit=PIVOT_RETEST_LOOKBACK)
    except Exception as e:
        logger.error(f"fetch_recent_candles {ticker}: {e}")
        return
    if len(candles) < 2:
        return

    alerts = []
    for detect_fn, rule_id in [
        (detect_pivot_retest_short, "pivot_retest_short"),
        (detect_pivot_retest_long, "pivot_retest_long"),
    ]:
        try:
            msg = detect_fn(candles)
            if msg:
                alerts.append(("1h", msg, rule_id))
        except Exception as e:
            logger.error(f"pivot_retest rule {rule_id} {ticker}: {e}")

    if not alerts:
        return

    now_utc = datetime.now(timezone.utc)
    allowed, sent_keys = _apply_cooldown(ticker, alerts, now_utc)
    if allowed:
        current_price = float(candles[-1]["close"])
        send_consolidated_alert(ticker, allowed, current_price, "MULTI")
        for tf, rule_id in sent_keys:
            _last_alert_sent[(ticker, tf, rule_id)] = now_utc


def main():
    logger.info("Starting alerts service...")
    logger.info(f"Tickers: {', '.join(TICKERS)}")
    logger.info(f"Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"Price pass (1h/4h/1d/1M): every {CHECK_INTERVAL}s. Candle pattern: every {CANDLE_PATTERN_CHECK_INTERVAL}s, 1 min after close.")
    logger.info(f"OHLC API: {OHLC_API_BASE_URL}")
    logger.info(f"DB host: {get_db_config().get('host', '?')}")

    if not db_check_connection():
        logger.error("Database connection failed. Check DB_* env vars.")
        return

    last_price_pass = 0  # Run price pass immediately on startup, then every CHECK_INTERVAL
    while True:
        try:
            now = time.time()

            # Single Binance call for all tickers — shared by both passes this cycle
            prices = fetch_all_prices(TICKERS)
            if not prices:
                logger.warning("Binance price fetch failed, retrying...")
                time.sleep(RETRY_INTERVAL)
                continue

            # Candle-pattern pass: every cycle, fires only for TFs within 1 min of close
            try:
                _run_candle_pattern_pass(prices)
            except Exception as e:
                logger.error(f"Candle pattern pass error: {e}")

            # pivot retest disabled
            # if is_within_1_min_after_close("1h"):
            #     for ticker in TICKERS:
            #         try:
            #             process_ticker_pivot_retest(ticker)
            #         except Exception as e:
            #             logger.error(f"Error pivot retest {ticker}: {e}")

            # Price pass (EMA200 + SMMA99): every CHECK_INTERVAL
            if now - last_price_pass >= CHECK_INTERVAL:
                last_price_pass = now
                try:
                    _run_price_pass(prices)
                except Exception as e:
                    logger.error(f"Price pass error: {e}")

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
