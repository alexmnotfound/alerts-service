import os
import logging
from datetime import datetime, timezone

import requests
from telegram import Bot
from telegram.error import InvalidToken

from ..config import format_utc_for_display

logger = logging.getLogger(__name__)

# Load environment variables from .env file (project root)
def load_env():
    try:
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value
    except FileNotFoundError:
        pass


load_env()

# Initialize bot and chat_id with error handling
bot = None
chat_id = None

try:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

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


def _send_telegram_sync(text: str) -> bool:
    """Send text to Telegram via HTTP. Returns True on success, False on failure. No asyncio."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id_val = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id_val:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id_val, "text": text},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        logger.error(f"Telegram send failed: HTTP {r.status_code} - {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def send_consolidated_alert(ticker, alerts, current_price=None, timeframe="1h", footer=None):
    """Send consolidated alert for a ticker with all its alerts. Optional footer (e.g. 'This is a test message')."""
    if not bot or not chat_id:
        logger.info(f"Alert (Telegram not configured) for {ticker}: {alerts}")
        return
    try:
        formatted_message = format_consolidated_alert(ticker, alerts, current_price, timeframe)
        if footer:
            formatted_message += f"\n\n{footer}"
        ok = _send_telegram_sync(formatted_message)
        if ok:
            logger.info(f"Consolidated alert sent to Telegram for {ticker}: {len(alerts)} alerts")
        else:
            logger.error(f"Consolidated alert NOT sent for {ticker}: {len(alerts)} alerts (send failed)")
            logger.info(f"Alert (not sent) for {ticker}: {alerts}")
    except Exception as e:
        logger.error(f"Failed to send consolidated Telegram alert: {e}")
        logger.info(f"Alert (not sent) for {ticker}: {alerts}")


def send_test_format_alert():
    """Send a sample alert using the real message format (for testing Telegram)."""
    sample_alerts = [
        "Price within 2% of PP at $97,500.00",
        "Doji candle pattern on last closed candle",
    ]
    send_consolidated_alert(
        "BTCUSDT",
        sample_alerts,
        current_price=97500.50,
        timeframe="1h",
        footer="This is a test message.",
    )


def send_alert(message):
    if not bot or not chat_id:
        logger.info(f"Alert (Telegram not configured): {message}")
        return
    ok = _send_telegram_sync(message)
    if ok:
        logger.info(f"Alert sent to Telegram: {message}")
    else:
        logger.error(f"Alert NOT sent (send failed): {message}")
        logger.info(f"Alert (not sent): {message}")
