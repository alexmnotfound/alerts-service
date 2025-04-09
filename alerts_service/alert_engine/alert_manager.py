import asyncio
import time
from datetime import datetime
from ..db.database import Database
from ..binance_api.client import BinanceClient
from ..telegram.notifier import TelegramNotifier
from .alert_condition import ChandelierExitAlert


class AlertManager:
    def __init__(self, alerts=None):
        self.alerts = alerts or []
        self.db = Database()
        self.binance = BinanceClient()
        self.telegram = TelegramNotifier()
        self.cached_ohlc = {}  # Cache for OHLC data by ticker and timeframe
        
    def add_alert(self, alert):
        """Add a new alert to be monitored"""
        self.alerts.append(alert)
        print(f"Added alert: {alert.name} for {alert.ticker}")
        
    def remove_alert(self, alert):
        """Remove an alert from monitoring"""
        if alert in self.alerts:
            self.alerts.remove(alert)
            print(f"Removed alert: {alert.name} for {alert.ticker}")
    
    def clear_triggered_alerts(self):
        """Remove all alerts that have been triggered"""
        triggered = [a for a in self.alerts if a.triggered]
        for alert in triggered:
            self.remove_alert(alert)
        return len(triggered)
    
    async def fetch_ohlc_data(self):
        """Fetch latest OHLC data from Binance for all tickers and timeframes in alerts"""
        # Group alerts by ticker and timeframe
        ticker_timeframes = set()
        for alert in self.alerts:
            ticker_timeframes.add((alert.ticker, alert.timeframe))
        
        # Fetch OHLC data for each ticker and timeframe
        for ticker, timeframe in ticker_timeframes:
            try:
                # Get latest kline from Binance
                klines = self.binance.get_klines(ticker, timeframe, limit=2)
                if klines and len(klines) > 0:
                    # Store in cache
                    self.cached_ohlc[(ticker, timeframe)] = klines
                    print(f"Updated OHLC data for {ticker} {timeframe}")
            except Exception as e:
                print(f"Error fetching OHLC data for {ticker} {timeframe}: {e}")
    
    async def check_alerts(self):
        """Check all active alerts against current OHLC data"""
        # Group alerts by ticker to process efficiently
        tickers = {}
        for alert in self.alerts:
            if alert.ticker not in tickers:
                tickers[alert.ticker] = []
            tickers[alert.ticker].append(alert)
        
        # Check each ticker's alerts
        for ticker, ticker_alerts in tickers.items():
            # Group alerts by timeframe
            timeframe_groups = {}
            for alert in ticker_alerts:
                if alert.timeframe not in timeframe_groups:
                    timeframe_groups[alert.timeframe] = []
                timeframe_groups[alert.timeframe].append(alert)
            
            # Process each timeframe group
            for timeframe, alerts in timeframe_groups.items():
                # Check if we have cached OHLC data for this ticker and timeframe
                cache_key = (ticker, timeframe)
                if cache_key not in self.cached_ohlc:
                    print(f"No OHLC data for {ticker} {timeframe}, skipping alerts")
                    continue
                
                # Get the latest OHLC data
                ohlc_data = self.cached_ohlc[cache_key]
                if not ohlc_data:
                    continue
                
                # Use the most recent candle's close price
                current_price = ohlc_data[0]['close']
                
                # Get historical OHLC from database
                db_ohlc_data = self.db.get_latest_ohlc(ticker, timeframe, limit=10)
                
                # Collect required indicators based on alert types
                indicators_data = {}
                indicator_types = set()
                for alert in alerts:
                    if hasattr(alert, 'ema_period'):
                        indicator_types.add('ema')
                    if hasattr(alert, 'rsi_period'):
                        indicator_types.add('rsi')
                    if isinstance(alert, ChandelierExitAlert):
                        indicator_types.add('ce')
                
                # Fetch required indicators
                for indicator_type in indicator_types:
                    indicators_data[indicator_type] = self.db.get_indicators(
                        ticker, timeframe, indicator_type, limit=10
                    )
                
                # Check each alert condition
                triggered_alerts = []
                for alert in alerts:
                    if alert.check_condition(current_price, indicators_data, db_ohlc_data):
                        triggered_alerts.append(alert)
                
                # Send notifications for triggered alerts
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for alert in triggered_alerts:
                    alert_data = {
                        'ticker': ticker,
                        'timeframe': timeframe,
                        'alert_type': alert.alert_type,
                        'price': current_price,
                        'message': f"{alert.get_alert_message(current_price)}\nTime: {timestamp}"
                    }
                    await self.telegram.send_alert(alert_data)
    
    async def run(self, check_interval=60):
        """Run the alert manager continuously"""
        print(f"Starting alert manager with {len(self.alerts)} alerts")
        print(f"Will check OHLC data every {check_interval} seconds")
        
        while True:
            try:
                # Fetch latest OHLC data
                await self.fetch_ohlc_data()
                
                # Check alerts against this data
                await self.check_alerts()
                
                # Clean up triggered alerts
                removed = self.clear_triggered_alerts()
                if removed > 0:
                    print(f"Removed {removed} triggered alerts")
                
                # Sleep until next check
                await asyncio.sleep(check_interval)
            except Exception as e:
                print(f"Error in alert manager: {e}")
                await asyncio.sleep(check_interval) 