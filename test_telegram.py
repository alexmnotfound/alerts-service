#!/usr/bin/env python3
import os
import asyncio
from telegram import Bot

# Load .env file
def load_env():
    try:
        with open('.env', 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
    except FileNotFoundError:
        pass

load_env()

async def test_telegram():
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    print(f"Bot Token: {bot_token}")
    print(f"Chat ID: {chat_id}")
    
    if not bot_token or not chat_id:
        print("❌ Missing credentials!")
        return
    
    try:
        bot = Bot(token=bot_token)
        
        # Test bot info
        bot_info = await bot.get_me()
        print(f"✅ Bot connected: @{bot_info.username}")
        
        # Test sending message
        message = await bot.send_message(chat_id=chat_id, text="🧪 Test message from alerts service!")
        print(f"✅ Message sent successfully! Message ID: {message.message_id}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure you've sent /start to your bot")
        print("2. Check if the chat ID is correct")
        print("3. For group chats, make sure the bot is added to the group")

if __name__ == "__main__":
    asyncio.run(test_telegram())
