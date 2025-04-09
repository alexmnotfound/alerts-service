import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

class BinanceClient:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        
    def get_latest_price(self, ticker):
        """Get the latest price for a symbol"""
        try:
            response = requests.get(f"{self.base_url}/ticker/price", params={"symbol": ticker})
            response.raise_for_status()
            data = response.json()
            return float(data['price'])
        except Exception as e:
            print(f"Error fetching price for {ticker}: {e}")
            return None
            
    def get_klines(self, ticker, interval, limit=100):
        """
        Get historical klines (candlestick data) using the v3 API
        
        Parameters:
        - ticker: Symbol (e.g., 'BTCUSDT')
        - interval: Time interval (e.g., '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w')
        - limit: Number of candles to fetch
        
        Returns:
        - List of candles with [timestamp, open, high, low, close, volume]
        """
        try:
            # Binance v3 Klines API uses these interval formats
            valid_intervals = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
            
            if interval not in valid_intervals:
                print(f"Invalid interval: {interval}. Using 1h instead.")
                interval = '1h'
            
            # Fetch klines from Binance public API
            params = {
                "symbol": ticker,
                "interval": interval,
                "limit": limit
            }
            
            response = requests.get(f"{self.base_url}/klines", params=params)
            response.raise_for_status()
            klines = response.json()
            
            # Format the results
            formatted_klines = []
            for k in klines:
                formatted_klines.append({
                    'timestamp': k[0] / 1000,  # Convert from ms to seconds
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                })
                
            return formatted_klines
        
        except Exception as e:
            print(f"Error fetching klines for {ticker}: {e}")
            return None 