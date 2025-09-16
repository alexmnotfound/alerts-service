# Alerts Service

A Python service that monitors cryptocurrency tickers and sends alerts via Telegram when specific trading conditions are met.

## Features

- **Multi-ticker monitoring**: Monitors multiple cryptocurrency pairs (BTCUSDT, ETHUSDT, ADAUSDT, SOLUSDT, DOTUSDT)
- **Hourly data validation**: Checks if data corresponds to the current hour
- **Automatic API updates**: Sends POST requests to update data when it's not current
- **Technical analysis alerts**: 
  - Pivot point alerts (when price is within 1% of pivot levels)
  - EMA crossover alerts (price crossing above/below EMA levels)
- **Telegram notifications**: Sends alerts via Telegram bot
- **Robust error handling**: Continues monitoring even if individual tickers fail

## Configuration

Edit `config.py` to:
- Add/remove tickers to monitor
- Adjust API base URL
- Modify alert thresholds
- Change monitoring intervals

## Environment Variables

Set the following environment variables:
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
- `TELEGRAM_CHAT_ID`: Chat ID where alerts will be sent

## Usage

### Using Docker
```bash
docker-compose up
```

### Using Python directly
```bash
chmod +x run.sh
./run.sh
```

## API Endpoints

The service expects the following API endpoints:
- `GET /ohlc/{ticker}/1h` - Fetch OHLC data for a ticker
- `POST /ohlc/{ticker}/1h` - Update OHLC data for a ticker

## Monitoring

The service runs every hour and:
1. Fetches data for each configured ticker
2. Validates if the data corresponds to the current hour
3. Updates data via POST request if not current
4. Checks for trading alerts
5. Sends notifications via Telegram
