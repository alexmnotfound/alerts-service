"""
Sync Binance client for fetching current OHLC (klines).
Used to get live price/candle to compare with TA indicators from the DB.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)

# Binance kline response: [open_time, open, high, low, close, volume, close_time, ...]
# OHLC and volume are strings.
BINANCE_BASE_URL = "https://api.binance.com/api/v3"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 1


def _timeframe_to_interval(timeframe: str) -> str:
    """Map our timeframe to Binance interval. 1h, 4h, 1d, 1w, 1M are valid."""
    return timeframe


def get_klines(
    symbol: str,
    interval: str,
    limit: int = 2,
) -> List[List]:
    """Fetch klines from Binance (sync). Returns raw kline arrays."""
    url = f"{BINANCE_BASE_URL}/klines"
    params = {"symbol": symbol, "interval": _timeframe_to_interval(interval), "limit": limit}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                return data if data else []
            logger.warning(f"Binance klines {symbol} {interval}: HTTP {resp.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Binance klines attempt {attempt + 1}: {e}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return []


def fetch_current_ohlc(symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest kline(s) from Binance and return current OHLC.
    Uses the most recent kline (index -1): its close is the current price for the interval.
    Returns dict with open, high, low, close (floats), or None on failure.
    """
    raw = get_klines(symbol, timeframe, limit=2)
    if not raw:
        return None
    k = raw[-1]
    try:
        return {
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
    except (IndexError, TypeError, ValueError) as e:
        logger.warning(f"Parse Binance kline failed: {e}")
        return None


def fetch_all_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices for all symbols in one Binance API call.

    Uses /ticker/price?symbols=[...] — one HTTP request regardless of how many symbols.
    Returns {symbol: price_float}. Empty dict on failure.
    """
    if not symbols:
        return {}
    url = f"{BINANCE_BASE_URL}/ticker/price?symbols={json.dumps(symbols, separators=(',', ':'))}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return {item["symbol"]: float(item["price"]) for item in resp.json()}
            logger.warning(f"Binance batch prices: HTTP {resp.status_code}")
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warning(f"Binance batch prices attempt {attempt + 1}: {e}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return {}


def fetch_all_5m_klines(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch the current (forming) 5m kline for all symbols in parallel.

    Returns {symbol: {open, high, low, close, volume}}. Missing symbols are absent.
    Uses the last kline (limit=1) which is the currently-forming 5m candle — its high/low
    capture the full price range since the last 5m boundary.
    """
    if not symbols:
        return {}

    def _fetch_one(symbol: str):
        raw = get_klines(symbol, "5m", limit=1)
        if not raw:
            return symbol, None
        k = raw[-1]
        try:
            return symbol, {
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
        except (IndexError, TypeError, ValueError) as e:
            logger.warning(f"Parse 5m kline {symbol}: {e}")
            return symbol, None

    result: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for symbol, ohlc in executor.map(_fetch_one, symbols):
            if ohlc:
                result[symbol] = ohlc
    return result
