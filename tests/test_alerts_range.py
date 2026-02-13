#!/usr/bin/env python3
"""
Run alert rules over a range of timestamps using historical DB data.
For each candle in the range, uses that candle's OHLC as "current" and runs all rules.

Usage (from project root):
  python tests/test_alerts_range.py --start 2025-01-01 --end 2025-01-31
  python tests/test_alerts_range.py --ticker ETHUSDT --timeframe 4h --start 2025-01-01 --end 2025-01-15 --limit 200

Dates are UTC (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS).
"""

import argparse
import os
import sys
from datetime import datetime, timezone


def _load_env():
    try:
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_env()

from alerts_service.db import fetch_candles_with_indicators, check_connection
from alerts_service.alerts.rules import run_all
from alerts_service.config import TICKERS, TIMEFRAMES, format_utc_for_display


def parse_ts(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Invalid date/time: {s!r}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (UTC).")


def main():
    ap = argparse.ArgumentParser(description="Test alert rules over a timestamp range (DB data, UTC)")
    ap.add_argument("--ticker", default="BTCUSDT", choices=TICKERS, help="Ticker symbol")
    ap.add_argument("--timeframe", default="1h", choices=TIMEFRAMES, help="Timeframe")
    ap.add_argument("--start", required=True, help="Start date/time UTC (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    ap.add_argument("--end", required=True, help="End date/time UTC (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    ap.add_argument("--limit", type=int, default=500, help="Max candles to fetch (default 500)")
    args = ap.parse_args()

    start = parse_ts(args.start)
    end = parse_ts(args.end)
    if start >= end:
        print("Error: --start must be before --end", file=sys.stderr)
        sys.exit(1)

    if not check_connection():
        print("Error: DB connection failed. Set DB_* env vars.", file=sys.stderr)
        sys.exit(1)

    candles = fetch_candles_with_indicators(
        args.ticker, args.timeframe, start, end, limit=args.limit
    )
    if not candles:
        print(f"No candles in DB for {args.ticker} {args.timeframe} between {start} and {end}")
        return

    print(f"Testing {len(candles)} candles from {format_utc_for_display(candles[0]['timestamp'])} to {format_utc_for_display(candles[-1]['timestamp'])}")
    print(f"Ticker: {args.ticker}  Timeframe: {args.timeframe}")
    print("-" * 60)

    for c in candles:
        current_ohlc = {
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c.get("volume"),
        }
        alerts = run_all(current_ohlc, c)
        ts_str = format_utc_for_display(c["timestamp"])
        close = c["close"]
        if alerts:
            print(f"{ts_str}  close={close:,.2f}  ALERTS: {' | '.join(alerts)}")
        else:
            print(f"{ts_str}  close={close:,.2f}")


if __name__ == "__main__":
    main()
