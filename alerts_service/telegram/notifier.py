import os
import telegram
from telegram.ext import Updater
from dotenv import load_dotenv

load_dotenv()

class TelegramNotifier:
    def __init__(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not token or not self.chat_id:
            raise ValueError("Telegram bot token and chat ID must be set in environment variables")
        
        self.bot = telegram.Bot(token=token)
        
    async def send_message(self, message):
        """Send a message to the configured chat"""
        try:
            # For python-telegram-bot v13.x, we need to use the non-async version
            self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=telegram.ParseMode.MARKDOWN
            )
            return True
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False
    
    async def send_alert(self, alert_data):
        """Format and send an alert notification"""
        ticker = alert_data.get('ticker', 'UNKNOWN')
        timeframe = alert_data.get('timeframe', 'UNKNOWN')
        alert_type = alert_data.get('alert_type', 'UNKNOWN')
        price = alert_data.get('price', 0)
        message = alert_data.get('message', '')
        
        formatted_message = (
            f"🚨 *ALERT: {alert_type}* 🚨\n\n"
            f"*Symbol:* {ticker}\n"
            f"*Timeframe:* {timeframe}\n"
            f"*Price:* {price}\n\n"
            f"{message}"
        )
        
        return await self.send_message(formatted_message) 