"""Run the monitor when executing the package: python -m alerts_service"""

from .monitor import main
from .notifier.notifier import setup_telegram_logging, start_command_listener
from .config import TICKERS, CANDLE_PATTERN_TIMEFRAMES, PRICE_PASS_TIMEFRAMES

_HELP_TEXT = f"""📊 Crypto Alerts Bot

Monitors {len(TICKERS)} USDT pairs on Binance and sends alerts when technical conditions are met.

📌 Active alerts:
• EMA 200 — price within 2% ({', '.join(PRICE_PASS_TIMEFRAMES)})
• Daily SMMA 99 — price within 2% (1d)
• Doji — indecision candle ({', '.join(CANDLE_PATTERN_TIMEFRAMES)})
• Tweezer Top/Bottom — reversal pattern ({', '.join(CANDLE_PATTERN_TIMEFRAMES)})

🕐 Frequency:
• Price/EMA: every hour
• Candle patterns: 1 min after each candle close
"""

if __name__ == "__main__":
    setup_telegram_logging()
    start_command_listener(_HELP_TEXT)
    main()
