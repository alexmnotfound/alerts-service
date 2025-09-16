# Configuration for the alerts service

# List of tickers to monitor
TICKERS = [
    "BTCUSDT",
    "ETHUSDT", 
]

# API configuration
API_BASE_URL = "http://localhost:8000"
TIMEFRAMES = ["1h", "4h"]  # Monitor both 1H and 4H timeframes

# Monitoring intervals (in seconds)
HOURLY_CHECK_INTERVAL = 60  # 1 minute for testing
RETRY_INTERVAL = 30  # 30 seconds for retries

# Alert thresholds
PIVOT_THRESHOLD = 0.01  # 1% threshold for pivot alerts
