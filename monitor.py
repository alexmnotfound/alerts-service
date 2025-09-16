import time
import requests
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from config import TICKERS, API_BASE_URL, TIMEFRAMES, HOURLY_CHECK_INTERVAL, RETRY_INTERVAL
from alerts.rules import check_pivot_alert, check_ema_alert
from notifier.notifier import send_alert, send_consolidated_alert

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_current_hour_timestamp() -> int:
    """Get the current hour timestamp in milliseconds."""
    now = datetime.now(timezone.utc)
    # Round down to the current hour
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    return int(current_hour.timestamp() * 1000)


def fetch_data(ticker: str, timeframe: str) -> Optional[List[Dict[str, Any]]]:
    """Fetch OHLC data for a specific ticker and timeframe."""
    url = f"{API_BASE_URL}/ohlc/{ticker}/{timeframe}"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Failed to fetch data for {ticker} {timeframe}: HTTP {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error for {ticker} {timeframe}: {e}")
        return None


def update_ticker_data(ticker: str, timeframe: str) -> bool:
    """Send POST request to update ticker data."""
    url = f"{API_BASE_URL}/ohlc/{ticker}/{timeframe}"
    try:
        response = requests.post(url, timeout=30)
        if response.status_code == 200:
            logger.info(f"Successfully updated data for {ticker} {timeframe}")
            return True
        else:
            logger.warning(f"Failed to update data for {ticker} {timeframe}: HTTP {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error updating {ticker} {timeframe}: {e}")
        return False


def is_data_current(candle: Dict[str, Any], current_hour_timestamp: int) -> bool:
    """Check if the candle data corresponds to the current hour."""
    candle_timestamp = candle.get('timestamp', 0)
    # Allow for some tolerance (within 1 hour)
    return abs(candle_timestamp - current_hour_timestamp) < 3600000  # 1 hour in milliseconds


def process_ticker_timeframe(ticker: str, timeframe: str) -> None:
    """Process a single ticker for a specific timeframe: fetch data, check if current, update if needed, check alerts."""
    logger.info(f"Processing ticker: {ticker} {timeframe}")
    
    # Get current hour timestamp
    current_hour_timestamp = get_current_hour_timestamp()
    
    # Fetch data
    data = fetch_data(ticker, timeframe)
    if not data:
        logger.error(f"No data received for {ticker} {timeframe}")
        return
    
    latest_candle = data[0]  # Assuming the first item is the latest candle
    
    # Check if data is current
    if not is_data_current(latest_candle, current_hour_timestamp):
        logger.warning(f"Data for {ticker} {timeframe} is not current. Attempting to update...")
        if update_ticker_data(ticker, timeframe):
            # Wait a bit and try to fetch updated data
            time.sleep(5)
            data = fetch_data(ticker, timeframe)
            if data:
                latest_candle = data[0]
            else:
                logger.error(f"Failed to fetch updated data for {ticker} {timeframe}")
                return
        else:
            logger.error(f"Failed to update data for {ticker} {timeframe}")
            return
    
    # Check for alerts
    try:
        pivot_alert = check_pivot_alert(latest_candle)
        ema_alert = check_ema_alert(latest_candle)
        
        # Collect all alerts for this ticker and timeframe
        alerts = []
        if pivot_alert:
            alerts.append(pivot_alert)
            logger.info(f"Pivot alert for {ticker} {timeframe}: {pivot_alert}")
            
        if ema_alert:
            alerts.append(ema_alert)
            logger.info(f"EMA alert for {ticker} {timeframe}: {ema_alert}")
        
        # Send consolidated alert if there are any alerts
        if alerts:
            current_price = latest_candle.get('close', None)
            send_consolidated_alert(ticker, alerts, current_price, timeframe)
            
    except Exception as e:
        logger.error(f"Error checking alerts for {ticker} {timeframe}: {e}")


def process_ticker(ticker: str) -> None:
    """Process a single ticker for all timeframes and send consolidated alerts."""
    logger.info(f"Processing ticker: {ticker}")
    
    all_alerts = []
    current_price = None
    
    for timeframe in TIMEFRAMES:
        try:
            # Get current hour timestamp
            current_hour_timestamp = get_current_hour_timestamp()
            
            # Fetch data
            data = fetch_data(ticker, timeframe)
            if not data:
                logger.error(f"No data received for {ticker} {timeframe}")
                continue
            
            latest_candle = data[0]
            
            # Set current price from first successful fetch
            if current_price is None:
                current_price = latest_candle.get('close', None)
            
            # Check if data is current
            if not is_data_current(latest_candle, current_hour_timestamp):
                logger.warning(f"Data for {ticker} {timeframe} is not current. Attempting to update...")
                if update_ticker_data(ticker, timeframe):
                    # Wait a bit and try to fetch updated data
                    time.sleep(5)
                    data = fetch_data(ticker, timeframe)
                    if data:
                        latest_candle = data[0]
                    else:
                        logger.error(f"Failed to fetch updated data for {ticker} {timeframe}")
                        continue
                else:
                    logger.error(f"Failed to update data for {ticker} {timeframe}")
                    continue
            
            # Check for alerts
            pivot_alert = check_pivot_alert(latest_candle)
            ema_alert = check_ema_alert(latest_candle)
            
            # Add alerts with timeframe prefix
            if pivot_alert:
                all_alerts.append(f"[{timeframe.upper()}] {pivot_alert}")
                logger.info(f"Pivot alert for {ticker} {timeframe}: {pivot_alert}")
                
            if ema_alert:
                all_alerts.append(f"[{timeframe.upper()}] {ema_alert}")
                logger.info(f"EMA alert for {ticker} {timeframe}: {ema_alert}")
                
        except Exception as e:
            logger.error(f"Error processing {ticker} {timeframe}: {e}")
            # Continue with other timeframes even if one fails
            continue
        
        # Small delay between timeframes to avoid overwhelming the API
        time.sleep(1)
    
    # Send consolidated alert if there are any alerts
    if all_alerts:
        send_consolidated_alert(ticker, all_alerts, current_price, "MULTI")


def main():
    """Main monitoring loop."""
    logger.info("Starting alerts service...")
    logger.info(f"Monitoring tickers: {', '.join(TICKERS)}")
    logger.info(f"Check interval: {HOURLY_CHECK_INTERVAL} seconds")
    
    while True:
        try:
            logger.info("Starting hourly check...")
            
            for ticker in TICKERS:
                try:
                    process_ticker(ticker)
                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}")
                    # Continue with other tickers even if one fails
                    continue
                
                # Small delay between tickers to avoid overwhelming the API
                time.sleep(2)
            
            logger.info("Hourly check completed. Waiting for next check...")
            time.sleep(HOURLY_CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Service stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            logger.info(f"Retrying in {RETRY_INTERVAL} seconds...")
            time.sleep(RETRY_INTERVAL)


if __name__ == '__main__':
    main() 