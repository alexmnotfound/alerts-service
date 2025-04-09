# Crypto Alerts Service (Work In Progress)

A service that monitors cryptocurrency prices, reads OHLC and technical indicators from a PostgreSQL database, fetches OHLC data from the Binance public API (v3) at regular intervals, and sends alerts via Telegram when specific conditions are met.

## Features

- Reads OHLC (Open-High-Low-Close) data from a PostgreSQL database
- Reads technical indicators (EMA, RSI, Chandelier Exit, etc.) from the database
- Fetches OHLC data from Binance public API every minute (no API keys required)
- Configurable alert conditions
- Real-time notifications via Telegram

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your configuration details
6. Run the application: `python main.py`

## Alert Types

The service supports various alert types:

- **Price Threshold Alerts**: Notify when price crosses above or below a specified threshold
- **EMA Alerts**: Notify when price crosses above or below a specific EMA
- **RSI Alerts**: Notify when RSI crosses above or below a specific threshold
- **Chandelier Exit Alerts**: Notify when Chandelier Exit indicator gives a buy or sell signal

## Configuration

Configure the database connection, Binance API credentials, and Telegram bot in the `.env` file.

## Adding Custom Alerts

You can add custom alerts by:

1. Creating a new alert condition class in `alerts_service/alert_engine/alert_condition.py`
2. Adding alert instances in `main.py`

## Example

```python
# Create a new alert for BTC when price crosses above $60,000
btc_alert = PriceThresholdAlert(
    ticker="BTCUSDT",
    timeframe="1h",
    threshold=60000,
    direction="above"
)
alert_manager.add_alert(btc_alert)
```
