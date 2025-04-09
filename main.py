import asyncio
import os
from alerts_service.alert_engine import (
    AlertManager,
    PriceThresholdAlert,
    EMAAlert,
    RSIAlert,
    ChandelierExitAlert
)
from dotenv import load_dotenv

load_dotenv()

async def main():
    # Initialize alert manager
    alert_manager = AlertManager()
    
    # Example alerts for Bitcoin
    # Price alert when BTC crosses $60,000
    btc_price_alert = PriceThresholdAlert(
        ticker="BTCUSDT",
        timeframe="1h",
        threshold=60000,
        direction="above"
    )
    alert_manager.add_alert(btc_price_alert)
    
    # EMA cross alert
    btc_ema_alert = EMAAlert(
        ticker="BTCUSDT",
        timeframe="1h",
        ema_period=50,
        direction="cross_above"
    )
    alert_manager.add_alert(btc_ema_alert)
    
    # RSI alert when RSI falls below 30 (oversold)
    btc_rsi_alert = RSIAlert(
        ticker="BTCUSDT",
        timeframe="1h",
        rsi_period=14,
        threshold=30,
        direction="below"
    )
    alert_manager.add_alert(btc_rsi_alert)
    
    # Chandelier Exit buy signal alert
    btc_ce_alert = ChandelierExitAlert(
        ticker="BTCUSDT",
        timeframe="1h",
        signal_type="buy"
    )
    alert_manager.add_alert(btc_ce_alert)
    
    # Example alerts for Ethereum
    # Price alert when ETH crosses $3,000
    eth_price_alert = PriceThresholdAlert(
        ticker="ETHUSDT",
        timeframe="1h",
        threshold=3000,
        direction="above"
    )
    alert_manager.add_alert(eth_price_alert)
    
    # Start the alert manager
    print("Starting Crypto Alerts Service...")
    try:
        # Run with 60-second (1 minute) interval between checks
        await alert_manager.run(check_interval=60)
    except KeyboardInterrupt:
        print("Stopping Crypto Alerts Service...")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main()) 