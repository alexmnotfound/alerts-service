"""
Database access for the alerts service.
Reads from the same PostgreSQL as the OHLC Handler (ohlc_data, ema_data, rsi_data, pivot_data, etc.).
All timestamps are UTC (timestamp without time zone).
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def get_db_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "ohlc"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        config = get_db_config()
        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=5, **config)
    return _pool


@contextmanager
def get_connection():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"DB error: {e}")
        raise
    finally:
        try:
            pool.putconn(conn)
        except Exception:
            pass


def fetch_latest_candle_with_indicators(
    ticker: str, timeframe: str
) -> Optional[Dict[str, Any]]:
    result = fetch_latest_candles_batch([(ticker, timeframe)])
    return result.get((ticker, timeframe))


def fetch_latest_candles_batch(
    pairs: List[Tuple[str, str]],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Fetch latest candles for multiple (ticker, timeframe) pairs in one DB round-trip.

    Returns {(ticker, timeframe): candle_dict}. Missing pairs are absent from the dict.
    Uses 1 connection and 7 queries regardless of how many pairs are requested.
    """
    if not pairs:
        return {}

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Latest ohlc row per (ticker, timeframe)
            cur.execute(
                """
                SELECT DISTINCT ON (ticker, timeframe)
                    ticker, timeframe, timestamp, open, high, low, close, volume, candle_pattern
                FROM ohlc_data
                WHERE (ticker, timeframe) IN %s
                ORDER BY ticker, timeframe, timestamp DESC
                """,
                (tuple(pairs),),
            )
            ohlc_rows = cur.fetchall()
            if not ohlc_rows:
                return {}

            result: Dict[Tuple[str, str], Dict[str, Any]] = {}
            triples: List[Tuple] = []
            tickers_set: set = set()

            for row in ohlc_rows:
                key = (row["ticker"], row["timeframe"])
                ts = row["timestamp"]
                triples.append((row["ticker"], row["timeframe"], ts))
                tickers_set.add(row["ticker"])
                result[key] = {
                    "ticker": row["ticker"],
                    "timeframe": row["timeframe"],
                    "timestamp": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if row["volume"] else None,
                    "candle_pattern": row["candle_pattern"],
                    "indicators": {},
                }

            triples_tuple = tuple(triples)
            tickers_list = list(tickers_set)

            # EMA
            cur.execute(
                """
                SELECT ticker, timeframe, period::text AS period, value
                FROM ema_data
                WHERE (ticker, timeframe, timestamp) IN %s
                """,
                (triples_tuple,),
            )
            for r in cur.fetchall():
                key = (r["ticker"], r["timeframe"])
                if key in result:
                    ind = result[key]["indicators"]
                    if "ema" not in ind:
                        ind["ema"] = {}
                    ind["ema"][r["period"]] = float(r["value"])

            # RSI
            cur.execute(
                """
                SELECT DISTINCT ON (ticker, timeframe) ticker, timeframe, value
                FROM rsi_data
                WHERE (ticker, timeframe, timestamp) IN %s
                ORDER BY ticker, timeframe
                """,
                (triples_tuple,),
            )
            for r in cur.fetchall():
                key = (r["ticker"], r["timeframe"])
                if key in result:
                    result[key]["indicators"]["rsi"] = float(r["value"])

            # OBV
            cur.execute(
                """
                SELECT DISTINCT ON (ticker, timeframe)
                    ticker, timeframe, obv, ma_value, upper_band, lower_band
                FROM obv_data
                WHERE (ticker, timeframe, timestamp) IN %s
                ORDER BY ticker, timeframe
                """,
                (triples_tuple,),
            )
            for r in cur.fetchall():
                key = (r["ticker"], r["timeframe"])
                if key in result:
                    result[key]["indicators"]["obv"] = {
                        "obv": float(r["obv"]) if r["obv"] is not None else None,
                        "ma_value": float(r["ma_value"]) if r["ma_value"] is not None else None,
                        "upper_band": float(r["upper_band"]) if r["upper_band"] is not None else None,
                        "lower_band": float(r["lower_band"]) if r["lower_band"] is not None else None,
                    }

            # Chandelier Exit
            cur.execute(
                """
                SELECT DISTINCT ON (ticker, timeframe)
                    ticker, timeframe, atr_value, long_stop, short_stop, direction, buy_signal, sell_signal
                FROM ce_data
                WHERE (ticker, timeframe, timestamp) IN %s
                ORDER BY ticker, timeframe
                """,
                (triples_tuple,),
            )
            for r in cur.fetchall():
                key = (r["ticker"], r["timeframe"])
                if key in result:
                    result[key]["indicators"]["ce"] = {
                        "atr_value": float(r["atr_value"]) if r["atr_value"] is not None else None,
                        "long_stop": float(r["long_stop"]) if r["long_stop"] is not None else None,
                        "short_stop": float(r["short_stop"]) if r["short_stop"] is not None else None,
                        "direction": r["direction"],
                        "buy_signal": r["buy_signal"],
                        "sell_signal": r["sell_signal"],
                    }

            # Pivot (most recent 1M pivot per ticker — no timeframe dependency)
            cur.execute(
                """
                SELECT DISTINCT ON (ticker)
                    ticker, pp, r1, r2, r3, r4, r5, s1, s2, s3, s4, s5
                FROM pivot_data
                WHERE ticker = ANY(%s) AND timeframe = '1M'
                ORDER BY ticker, timestamp DESC
                """,
                (tickers_list,),
            )
            pivot_by_ticker: Dict[str, Dict] = {}
            for r in cur.fetchall():
                pivot_by_ticker[r["ticker"]] = {
                    "PP": float(r["pp"]) if r["pp"] is not None else None,
                    "R1": float(r["r1"]) if r["r1"] is not None else None,
                    "R2": float(r["r2"]) if r["r2"] is not None else None,
                    "R3": float(r["r3"]) if r["r3"] is not None else None,
                    "R4": float(r["r4"]) if r["r4"] is not None else None,
                    "R5": float(r["r5"]) if r["r5"] is not None else None,
                    "S1": float(r["s1"]) if r["s1"] is not None else None,
                    "S2": float(r["s2"]) if r["s2"] is not None else None,
                    "S3": float(r["s3"]) if r["s3"] is not None else None,
                    "S4": float(r["s4"]) if r["s4"] is not None else None,
                    "S5": float(r["s5"]) if r["s5"] is not None else None,
                }
            for key in result:
                pivot = pivot_by_ticker.get(key[0])
                if pivot:
                    result[key]["indicators"]["pivot"] = pivot

            # Daily SMMA 99
            cur.execute(
                """
                SELECT DISTINCT ON (ticker) ticker, value
                FROM daily_smma_99
                WHERE ticker = ANY(%s)
                ORDER BY ticker, timestamp DESC
                """,
                (tickers_list,),
            )
            smma_by_ticker: Dict[str, Optional[float]] = {}
            for r in cur.fetchall():
                smma_by_ticker[r["ticker"]] = float(r["value"]) if r["value"] is not None else None
            for key in result:
                result[key]["indicators"]["daily_smma_99"] = smma_by_ticker.get(key[0])

    return result


def _build_candle_with_indicators(
    conn, cur, ticker: str, timeframe: str, row: Dict[str, Any]
) -> Dict[str, Any]:
    """Build one candle dict with indicators. Used for range-based fetches (pivot retest etc.)."""
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
    cur.execute(
        "SELECT value FROM daily_smma_99 WHERE ticker = %s ORDER BY timestamp DESC LIMIT 1",
        (ticker,),
    )
    smma_row = cur.fetchone()
    if smma_row and smma_row["value"] is not None:
        candle["indicators"]["daily_smma_99"] = float(smma_row["value"])
    else:
        candle["indicators"]["daily_smma_99"] = None
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
            return [_build_candle_with_indicators(conn, cur, ticker, timeframe, row) for row in rows]


def fetch_recent_candles_with_indicators(
    ticker: str,
    timeframe: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch the most recent `limit` closed candles for (ticker, timeframe), oldest first.
    Returns list of candle dicts with indicators (same shape as fetch_latest_candle_with_indicators).
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ticker, timeframe, timestamp, open, high, low, close, volume, candle_pattern
                FROM ohlc_data
                WHERE ticker = %s AND timeframe = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (ticker, timeframe, limit),
            )
            rows = cur.fetchall()
            if not rows:
                return []
            ordered_rows = list(reversed(rows))
            return [_build_candle_with_indicators(conn, cur, ticker, timeframe, row) for row in ordered_rows]


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
