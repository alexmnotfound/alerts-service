#!/usr/bin/env python3
"""Send the real alert message format to Telegram (for testing). Uses notifier only."""

import os


def load_env():
    try:
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v
    except FileNotFoundError:
        pass


load_env()

if __name__ == "__main__":
    from alerts_service.notifier.notifier import send_test_format_alert

    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        print("❌ Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        exit(1)
    print("Sending real-format test alert...")
    send_test_format_alert()
    print("✅ Done. Check Telegram.")
