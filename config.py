# Configuration for the alerts service

import os
from datetime import timezone, timedelta

# List of tickers to monitor (must match OHLC Handler: BTCUSDT, ETHUSDT)
TICKERS = [
    "BTCUSDT",
    "ETHUSDT",
]

# OHLC Handler API: trigger updates when data is missing/stale
# In production set OHLC_API_BASE_URL to the OHLC Handler host (e.g. http://ohlc-handler:8000)
OHLC_API_BASE_URL = os.getenv("OHLC_API_BASE_URL", "http://localhost:8000")

# Timeframes to monitor (must match OHLC Handler: 1h, 4h, 1d, 1w, 1M)
TIMEFRAMES = ["1h", "4h", "1d", "1w", "1M"]

# Monitoring intervals (in seconds)
HOURLY_CHECK_INTERVAL = int(os.getenv("HOURLY_CHECK_INTERVAL", "3600"))  # 1 hour
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "30"))

# Alert thresholds
PIVOT_THRESHOLD = 0.02  # 2% deviation for "price meets" monthly pivot

# Stale data: consider data stale if latest candle is older than this many seconds
STALE_DATA_SECONDS = int(os.getenv("STALE_DATA_SECONDS", "7200"))  # 2 hours

# Display timezone: DB stores UTC; messages show this zone (GMT-3)
DISPLAY_TIMEZONE = timezone(timedelta(hours=-3))


def format_utc_for_display(dt, fmt="%Y-%m-%d %H:%M GMT-3"):
    """Convert a UTC datetime to GMT-3 and return formatted string. Accepts naive (assumed UTC) or aware."""
    if dt is None:
        return "N/A"
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TIMEZONE).strftime(fmt)
