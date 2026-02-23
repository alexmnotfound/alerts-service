# Configuration for the alerts service

import os
from datetime import datetime, timezone, timedelta

# List of tickers to monitor (must match OHLC Handler: BTCUSDT, ETHUSDT)
TICKERS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'LINKUSDT']

# OHLC Handler API: trigger updates when data is missing/stale
# In production set OHLC_API_BASE_URL to the OHLC Handler host (e.g. http://ohlc-handler:8000)
OHLC_API_BASE_URL = os.getenv("OHLC_API_BASE_URL", "http://localhost:8000")

# Timeframes to monitor (must match OHLC Handler: 1h, 4h, 1d, 1w, 1M)
TIMEFRAMES = ["1h", "4h", "1d", "1w", "1M"]

# How often to run a full check (fetch Binance price + DB indicators + run rules). Shorter = faster alerts.
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", os.getenv("HOURLY_CHECK_INTERVAL", "300")))  # default 5 min
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "30"))

# Alert thresholds
PIVOT_THRESHOLD = 0.02  # 2% deviation for "price meets" monthly pivot

# Stale data: per-timeframe max age (seconds) for latest candle before we trigger an OHLC update.
# ~2× the candle period so we allow one closed candle plus some slack.
STALE_DATA_SECONDS_BY_TIMEFRAME = {
    "1h": 2 * 3600,           # 2 hours
    "4h": 2 * 4 * 3600,       # 8 hours
    "1d": 2 * 24 * 3600,      # 2 days
    "1w": 2 * 7 * 24 * 3600,  # 14 days
    "1M": 60 * 24 * 3600,     # 60 days (2 months)
}
# Fallback if timeframe unknown (e.g. env override for all)
STALE_DATA_SECONDS_DEFAULT = int(os.getenv("STALE_DATA_SECONDS", "7200"))  # 2 hours

# Candle pattern: only fire when we're within this many seconds after the candle close (1 min).
CANDLE_PATTERN_GRACE_AFTER_CLOSE = 60  # 1 minute
# How often to check for "1 min after close" (run candle-pattern pass).
CANDLE_PATTERN_CHECK_INTERVAL = 60  # 1 min

# Min seconds between sending any alert for the same (ticker, timeframe). Avoids spamming same TF.
# 1h -> 4h, 4h -> 1 day, 1d -> 2 days, 1w -> 7 days, 1M -> 30 days
ALERT_COOLDOWN_SECONDS = {
    "1h": 4 * 3600,   # 4 hours
    "4h": 24 * 3600,  # 1 day
    "1d": 2 * 24 * 3600,
    "1w": 7 * 24 * 3600,
    "1M": 30 * 24 * 3600,
}

# Display timezone: DB stores UTC; messages show this zone (GMT-3)
DISPLAY_TIMEZONE = timezone(timedelta(hours=-3))


def get_last_close_utc(timeframe: str) -> datetime:
    """Return the close time (UTC) of the candle that most recently closed for this timeframe."""
    now = datetime.now(timezone.utc)
    tf = (timeframe or "").strip().lower()
    if tf == "1h":
        t = now.replace(minute=0, second=0, microsecond=0)
        return t if now > t else t - timedelta(hours=1)
    if tf == "4h":
        h = (now.hour // 4) * 4
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        return t if now > t else t - timedelta(hours=4)
    if tf == "1d":
        t = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return t if now > t else t - timedelta(days=1)
    if tf == "1w":
        # Monday = 0
        days_since_monday = (now.weekday()) % 7
        t = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        return t if now > t else t - timedelta(days=7)
    if tf == "1m" or tf == "1M":
        t = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now <= t:
            prev = (t - timedelta(days=1))
            t = prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return t
    return now  # fallback


def is_within_1_min_after_close(timeframe: str) -> bool:
    """True if we're within CANDLE_PATTERN_GRACE_AFTER_CLOSE seconds of the candle close for this timeframe."""
    last = get_last_close_utc(timeframe)
    now = datetime.now(timezone.utc)
    age = (now - last).total_seconds()
    return 0 <= age <= CANDLE_PATTERN_GRACE_AFTER_CLOSE


def format_utc_for_display(dt, fmt="%Y-%m-%d %H:%M GMT-3"):
    """Convert a UTC datetime to GMT-3 and return formatted string. Accepts naive (assumed UTC) or aware."""
    if dt is None:
        return "N/A"
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TIMEZONE).strftime(fmt)
