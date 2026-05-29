import os
import time
import hashlib
import logging
import threading

import requests
from telegram import Bot
from telegram.error import InvalidToken

logger = logging.getLogger(__name__)


def load_env():
    """Load .env file as fallback for local runs. Docker env vars take precedence."""
    try:
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


load_env()

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
    """Format consolidated alert message for a ticker with all alerts."""
    if current_price:
        formatted_price = f"${current_price:,.2f}"
    else:
        formatted_price = "N/A"
    formatted_message = f"""
📊 {ticker} @ {formatted_price}
━━━━━━━━━━━━━━━━━━━━
"""
    for alert in alerts:
        formatted_message += f"• {alert}\n"
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
    """Send consolidated alert for a ticker with all its alerts. Optional footer."""
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


class TelegramErrorHandler(logging.Handler):
    """Forwards ERROR+ log records to Telegram. Rate-limits identical messages to avoid spam."""

    _last_sent: dict = {}
    _COOLDOWN = 60

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not bot or not chat_id:
                return
            msg = self.format(record)
            key = hashlib.md5(msg.encode()).hexdigest()
            now = time.monotonic()
            if now - TelegramErrorHandler._last_sent.get(key, 0) < self._COOLDOWN:
                return
            TelegramErrorHandler._last_sent[key] = now
            _send_telegram_sync(msg)
        except Exception:
            pass


def setup_telegram_logging(level: int = logging.ERROR) -> None:
    """Attach TelegramErrorHandler to the root logger. Call once at startup."""
    handler = TelegramErrorHandler(level=level)
    handler.setFormatter(logging.Formatter("🚨 %(levelname)s [%(name)s]\n%(message)s"))
    logging.getLogger().addHandler(handler)


def _poll_commands(help_text: str) -> None:
    """Background thread: long-poll Telegram for /help and /start commands."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    offset = 0
    url_updates = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    url_send = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    while True:
        try:
            r = requests.get(url_updates, params={"offset": offset, "timeout": 30}, timeout=35)
            if r.status_code != 200:
                time.sleep(5)
                continue
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat = msg.get("chat", {}).get("id")
                if chat and (text.startswith("/help") or text.startswith("/start")):
                    requests.post(url_send, json={"chat_id": chat, "text": help_text}, timeout=15)
        except Exception as e:
            logger.warning(f"Command listener error: {e}")
            time.sleep(5)


def start_command_listener(help_text: str) -> None:
    """Start background thread that handles /help and /start bot commands."""
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return
    t = threading.Thread(target=_poll_commands, args=(help_text,), daemon=True)
    t.start()
    logger.info("Telegram command listener started")
