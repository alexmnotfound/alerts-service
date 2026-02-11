import os
import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import InvalidToken

from config import format_utc_for_display

logger = logging.getLogger(__name__)

# Load environment variables from .env file
def load_env():
    try:
        with open('.env', 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
    except FileNotFoundError:
        pass

# Load .env file
load_env()

# Initialize bot and chat_id with error handling
bot = None
chat_id = None

try:
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if bot_token and chat_id:
        bot = Bot(token=bot_token)
        logger.info("Telegram bot initialized successfully")
    else:
        logger.warning("Telegram credentials not found. Alerts will be logged only.")
except InvalidToken as e:
    logger.warning(f"Invalid Telegram token: {e}. Alerts will be logged only.")
except Exception as e:
    logger.warning(f"Failed to initialize Telegram bot: {e}. Alerts will be logged only.")


def format_consolidated_alert(ticker, alerts, current_price=None, timeframe="1h"):
    """Format consolidated alert message for a ticker with all alerts. Time shown in GMT-3."""
    if current_price:
        formatted_price = f"${current_price:,.2f}"
    else:
        formatted_price = "N/A"
    now_gmt3 = format_utc_for_display(datetime.now(timezone.utc))
    formatted_message = f"""
📊 {ticker} @ {formatted_price}
🕐 {now_gmt3}
━━━━━━━━━━━━━━━━━━━━
"""
    for alert in alerts:
        formatted_message += f"• {alert}\n"
    formatted_message += "━━━━━━━━━━━━━━━━━━━━"
    return formatted_message

def send_consolidated_alert(ticker, alerts, current_price=None, timeframe="1h", footer=None):
    """Send consolidated alert for a ticker with all its alerts. Optional footer (e.g. 'This is a test message')."""
    if bot and chat_id:
        try:
            import asyncio
            import threading
            formatted_message = format_consolidated_alert(ticker, alerts, current_price, timeframe)
            if footer:
                formatted_message += f"\n\n{footer}"
            def send_message():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(bot.send_message(
                        chat_id=chat_id,
                        text=formatted_message,
                    ))
                    loop.close()
                except Exception as e:
                    logger.error(f"Failed to send message in thread: {e}")
            
            # Run in a separate thread to avoid event loop issues
            thread = threading.Thread(target=send_message)
            thread.start()
            thread.join(timeout=10)  # Wait up to 10 seconds
            
            logger.info(f"Consolidated alert sent to Telegram for {ticker}: {len(alerts)} alerts")
        except Exception as e:
            logger.error(f"Failed to send consolidated Telegram alert: {e}")
            logger.info(f"Alert (not sent) for {ticker}: {alerts}")
    else:
        logger.info(f"Alert (Telegram not configured) for {ticker}: {alerts}")

def send_test_format_alert():
    """Send a sample alert using the real message format (for testing Telegram)."""
    sample_alerts = [
        "Price within 2% of PP at $97,500.00",
        "Doji candle pattern on last closed candle",
    ]
    send_consolidated_alert(
        "BTCUSDT", sample_alerts, current_price=97500.50, timeframe="1h",
        footer="⚠️ This is a test message.",
    )


def send_alert(message):
    if bot and chat_id:
        try:
            import asyncio
            # Create new event loop for each call
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(bot.send_message(chat_id=chat_id, text=message))
                logger.info(f"Alert sent to Telegram: {message}")
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            logger.info(f"Alert (not sent): {message}")
    else:
        logger.info(f"Alert (Telegram not configured): {message}") 