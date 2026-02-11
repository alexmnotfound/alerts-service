# Alerts Service

Monitors cryptocurrency tickers using OHLC and technical indicators from the same PostgreSQL database as the OHLC Handler. When conditions are met (e.g. pivot levels, EMA touches/crosses), it sends alerts to Telegram. Runs in a loop; when data is missing or stale it triggers the OHLC Handler API to update.

## Architecture

- **Database**: Same PostgreSQL as OHLC Handler. Reads TA indicators from `ohlc_data`, `ema_data`, `rsi_data`, `obv_data`, `ce_data`, `pivot_data`. The OHLC Service only updates candles and computes indicators; it does not serve live OHLC.
- **Binance**: This service fetches **current OHLC** (klines) from Binance and compares that live price/candle with the indicators from the DB to trigger alerts.
- **OHLC Handler API**: Used only to trigger updates when the service detects missing or stale indicator data in the DB.
- **Telegram**: Alerts are sent via a Telegram bot to a configured chat.

## Configuration

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Database name | `ohlc` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | *(required)* |
| `OHLC_API_BASE_URL` | OHLC Handler base URL | `http://localhost:8000` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | *(required for alerts)* |
| `TELEGRAM_CHAT_ID` | Chat ID for alerts | *(required for alerts)* |
| `HOURLY_CHECK_INTERVAL` | Seconds between full checks | `3600` |
| `RETRY_INTERVAL` | Seconds before retry on error | `30` |
| `STALE_DATA_SECONDS` | Consider data stale after this many seconds | `7200` |

Copy `.env.example` to `.env` and fill in values.

## Running with Docker (e.g. DonWeb VM)

1. Build and run with docker-compose (set env in `.env` or host):

   ```bash
   docker-compose up -d
   ```

2. For production, run the built image without mounting the repo (so the container uses the image, not the host filesystem). Either remove the `volumes` section from `docker-compose.yml` or run the image directly:

   ```bash
   docker build -t alerts-service .
   docker run -d --name alerts-service \
     -e DB_HOST=your-db-host \
     -e DB_PORT=5432 \
     -e DB_NAME=ohlc \
     -e DB_USER=your-user \
     -e DB_PASSWORD=your-password \
     -e OHLC_API_BASE_URL=http://ohlc-handler-host:8000 \
     -e TELEGRAM_BOT_TOKEN=your-token \
     -e TELEGRAM_CHAT_ID=your-chat-id \
     alerts-service
   ```

3. Ensure the VM can reach PostgreSQL and the OHLC Handler (same network or correct host/port).

## Running locally

```bash
make run
```

Or `make install` then `make run-bare`. Set env vars or use `.env`.

## Alert rules

1. **Monthly pivot** – When current price (from Binance) is within 2% of any monthly pivot level (PP, R1–R5, S1–S5). Configurable via `PIVOT_THRESHOLD` in `config.py`.
2. **Doji** – When the last closed candle has Doji pattern (from DB, computed by the OHLC Service).


## OHLC Handler API (triggering updates)

When the latest candle is missing or older than `STALE_DATA_SECONDS`, the service calls:

- `POST /update/{symbol}/{timeframe}` for the affected symbol and timeframe.

Allowed symbols: `BTCUSDT`, `ETHUSDT`. Timeframes: `1h`, `4h`, `1d`, `1w`, `1M`.

## Testing alerts over a date range

Run alert rules against historical DB data for a given timestamp range (UTC):

```bash
python test_alerts_range.py --start 2025-01-01 --end 2025-01-31
python test_alerts_range.py --ticker ETHUSDT --timeframe 4h --start 2025-01-01 --end 2025-01-15 --limit 200
```

For each candle in the range, the script uses that candle’s OHLC as “current” and runs all rules; it prints timestamp, close price, and any alerts that would have fired.

## Testing Telegram

```bash
python test_telegram.py
```

Uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the environment or `.env`.
