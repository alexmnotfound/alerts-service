"""
Database access for the alerts service.
Reads from the same PostgreSQL as the OHLC Handler (ohlc_data, ema_data, rsi_data, pivot_data, etc.).
All timestamps are UTC (timestamp without time zone).
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, List

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def get_db_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "ohlc"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


@contextmanager
def get_connection():
    config = get_db_config()
    conn = None
    try:
        conn = psycopg2.connect(**config)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def fetch_latest_candle_with_indicators(
    ticker: str, timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest candle for (ticker, timeframe) with all indicators from the DB.
    Returns a dict compatible with alert rules: open, high, low, close, volume, timestamp,
    and indicators: { pivot, ema, rsi, obv, ce }.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ticker, timeframe, timestamp, open, high, low, close, volume, candle_pattern
                FROM ohlc_data
                WHERE ticker = %s AND timeframe = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (ticker, timeframe),
            )
            row = cur.fetchone()
    if not row:
        return None

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _build_candle_with_indicators(conn, cur, ticker, timeframe, row)


def _build_candle_with_indicators(
    conn, cur, ticker: str, timeframe: str, row: Dict[str, Any]
) -> Dict[str, Any]:
    """Build one candle dict with indicators (shared by fetch_latest and fetch_range)."""
    ts = row["timestamp"]
    candle = {
        "ticker": row["ticker"],
        "timeframe": row["timeframe"],
        "timestamp": row["timestamp"],
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]) if row["volume"] else None,
        "candle_pattern": row["candle_pattern"],
        "indicators": {},
    }
    cur.execute(
        "SELECT period, value FROM ema_data WHERE ticker = %s AND timeframe = %s AND timestamp = %s",
        (ticker, timeframe, ts),
    )
    ema_rows = cur.fetchall()
    if ema_rows:
        candle["indicators"]["ema"] = {str(r["period"]): float(r["value"]) for r in ema_rows}
    cur.execute(
        "SELECT period, value FROM rsi_data WHERE ticker = %s AND timeframe = %s AND timestamp = %s LIMIT 1",
        (ticker, timeframe, ts),
    )
    rsi_row = cur.fetchone()
    if rsi_row:
        candle["indicators"]["rsi"] = float(rsi_row["value"])
    cur.execute(
        "SELECT obv, ma_period, ma_value, bb_std, upper_band, lower_band FROM obv_data WHERE ticker = %s AND timeframe = %s AND timestamp = %s LIMIT 1",
        (ticker, timeframe, ts),
    )
    obv_row = cur.fetchone()
    if obv_row:
        candle["indicators"]["obv"] = {
            "obv": float(obv_row["obv"]) if obv_row["obv"] is not None else None,
            "ma_value": float(obv_row["ma_value"]) if obv_row["ma_value"] is not None else None,
            "upper_band": float(obv_row["upper_band"]) if obv_row["upper_band"] is not None else None,
            "lower_band": float(obv_row["lower_band"]) if obv_row["lower_band"] is not None else None,
        }
    cur.execute(
        "SELECT atr_value, long_stop, short_stop, direction, buy_signal, sell_signal FROM ce_data WHERE ticker = %s AND timeframe = %s AND timestamp = %s LIMIT 1",
        (ticker, timeframe, ts),
    )
    ce_row = cur.fetchone()
    if ce_row:
        candle["indicators"]["ce"] = {
            "atr_value": float(ce_row["atr_value"]) if ce_row["atr_value"] is not None else None,
            "long_stop": float(ce_row["long_stop"]) if ce_row["long_stop"] is not None else None,
            "short_stop": float(ce_row["short_stop"]) if ce_row["short_stop"] is not None else None,
            "direction": ce_row["direction"],
            "buy_signal": ce_row["buy_signal"],
            "sell_signal": ce_row["sell_signal"],
        }
    cur.execute(
        """
        SELECT pp, r1, r2, r3, r4, r5, s1, s2, s3, s4, s5 FROM pivot_data
        WHERE ticker = %s AND timeframe = '1M' AND timestamp <= %s ORDER BY timestamp DESC LIMIT 1
        """,
        (ticker, ts),
    )
    pivot_row = cur.fetchone()
    if pivot_row:
        candle["indicators"]["pivot"] = {
            "PP": float(pivot_row["pp"]) if pivot_row["pp"] is not None else None,
            "R1": float(pivot_row["r1"]) if pivot_row["r1"] is not None else None,
            "R2": float(pivot_row["r2"]) if pivot_row["r2"] is not None else None,
            "R3": float(pivot_row["r3"]) if pivot_row["r3"] is not None else None,
            "R4": float(pivot_row["r4"]) if pivot_row["r4"] is not None else None,
            "R5": float(pivot_row["r5"]) if pivot_row["r5"] is not None else None,
            "S1": float(pivot_row["s1"]) if pivot_row["s1"] is not None else None,
            "S2": float(pivot_row["s2"]) if pivot_row["s2"] is not None else None,
            "S3": float(pivot_row["s3"]) if pivot_row["s3"] is not None else None,
            "S4": float(pivot_row["s4"]) if pivot_row["s4"] is not None else None,
            "S5": float(pivot_row["s5"]) if pivot_row["s5"] is not None else None,
        }
    return candle


def fetch_candles_with_indicators(
    ticker: str,
    timeframe: str,
    start_time: Any,
    end_time: Any,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    Fetch candles with indicators for (ticker, timeframe) in [start_time, end_time] (UTC).
    start_time, end_time: datetime or date string YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.
    Returns list of candle dicts (same shape as fetch_latest_candle_with_indicators), oldest first.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ticker, timeframe, timestamp, open, high, low, close, volume, candle_pattern
                FROM ohlc_data
                WHERE ticker = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC
                LIMIT %s
                """,
                (ticker, timeframe, start_time, end_time, limit),
            )
            rows = cur.fetchall()
    if not rows:
        return []
    candles = []
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for row in rows:
                candles.append(_build_candle_with_indicators(conn, cur, ticker, timeframe, row))
    return candles


def fetch_latest_timestamp(ticker: str, timeframe: str) -> Optional[Any]:
    """Return the latest candle timestamp for (ticker, timeframe), or None if no data."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp FROM ohlc_data
                WHERE ticker = %s AND timeframe = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (ticker, timeframe),
            )
            row = cur.fetchone()
    return row[0] if row else None


def check_connection() -> bool:
    """Check DB connectivity. Returns True if connection succeeds."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"DB check failed: {e}")
        return False
