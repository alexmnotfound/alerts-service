# Alerts Service

Monitors cryptocurrency tickers using OHLC and technical indicators from the same PostgreSQL database as the OHLC Handler. When conditions are met (e.g. pivot levels, EMA touches/crosses, candle patterns), it sends alerts to Telegram. Runs in a loop with two types of processing: **price pass** (1H every 5 min: pivot + EMA) and **candle-pattern pass** (all timeframes, only in the 1‑minute window after each candle close). When data is missing or stale it triggers the OHLC Handler API to update.

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
| `CHECK_INTERVAL` | Seconds between **price pass** (1H pivot + EMA). | `300` (5 min) |
| `HOURLY_CHECK_INTERVAL` | Legacy alias for `CHECK_INTERVAL` | same |
| `CANDLE_PATTERN_CHECK_INTERVAL` | Seconds between candle-pattern checks (1 min after close). | `60` |
| `RETRY_INTERVAL` | Seconds before retry on error | `30` |
| `STALE_DATA_SECONDS` | Fallback max age (seconds) for “stale” when timeframe is unknown. Per-timeframe defaults in code: 1h→2h, 4h→8h, 1d→2d, 1w→14d, 1M→60d. | `7200` |

Copy `.env.example` to `.env` and fill in values.

## Project layout

```
alerts-service/
├── alerts_service/          # Main package
│   ├── alerts/              # Alert rules (add new rules in rules.py)
│   ├── notifier/            # Telegram formatting and sending
│   ├── config.py
│   ├── db.py
│   ├── binance_client.py
│   ├── monitor.py
│   └── __main__.py          # Entry point: python -m alerts_service
├── tests/
│   ├── test_telegram.py
│   └── test_alerts_range.py
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

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

## Processing: two passes

- **Price pass (1H, every `CHECK_INTERVAL`):** Runs only for 1H. Rules: **monthly pivot** and **EMA 50/200**. Fetches latest 1H candle + indicators from DB and current OHLC from Binance, runs `run_price_rules()`, applies cooldown, sends one consolidated message per ticker if any alert fires.
- **Candle-pattern pass (all timeframes, every `CANDLE_PATTERN_CHECK_INTERVAL`):** For each timeframe we only run when **within 1 minute after that timeframe’s candle close** (e.g. 1H at :01, 4H at :01 after 4h close, 1d at 00:01 UTC, etc.). Rules: **Doji** (and any future candle-pattern rules). Fetches candle + current OHLC, runs `run_candle_pattern_rules()`, Doji dedupe, cooldown, sends.

So: pivot and EMA fire on 1H every 5 minutes; Doji (and other candle patterns) fire only once per closed candle, in the 1‑minute window after close for each timeframe.

## Alert rules

- **Current price** is always from Binance (live). **Indicators** (pivot, RSI, OBV, candle_pattern, etc.) are the **fixed values from the last closed candle** per timeframe (1H, 4H, etc.) in the DB. Each timeframe is evaluated separately: we compare current price to that timeframe’s indicator values.

1. **Monthly pivot** – Current price (Binance) within 2% of any monthly pivot level (PP, R1–R5, S1–S5). **Price pass only, 1H.** Configurable via `PIVOT_THRESHOLD` in `alerts_service/config.py`.
2. **Doji** – The candle that **just closed** (for that timeframe) has Doji pattern. **Candle-pattern pass only:** fires only in the **1‑minute window after candle close** for each timeframe (1h, 4h, 1d, 1w, 1M). See `CANDLE_PATTERN_GRACE_AFTER_CLOSE` in config.
3. **EMA50 / EMA200** – Current price touches or crosses EMA 50 or 200. **Price pass only, 1H** (rule is defined for 1h, 4h, 1d, 1M but the service only runs price rules on 1H every 5 min). Uses fixed EMA from last closed candle.

When you add more indicators (e.g. OBV, RSI), use the same pattern: take the fixed value for that timeframe from `db_candle["indicators"]` and compare to current price (or to the threshold that makes sense for that indicator).

**Alert cooldown (per ticker + timeframe):** We send at most one alert per (ticker, timeframe) within a cooldown window, so the same condition doesn’t spam. Defaults: 1H → every 4 hours, 4H → once per day, 1d → 2 days, 1w → 7 days, 1M → 30 days. Configured in `ALERT_COOLDOWN_SECONDS` in `alerts_service/config.py`.


## OHLC Handler API (triggering updates)

When the latest candle is missing or older than the **per-timeframe** staleness threshold (e.g. 1h→2 hours, 4h→8 hours, 1d→2 days; see `STALE_DATA_SECONDS_BY_TIMEFRAME` in config), the service calls:

- `POST /update/{symbol}/{timeframe}` for the affected symbol and timeframe.

Allowed symbols: `BTCUSDT`, `ETHUSDT`. Timeframes: `1h`, `4h`, `1d`, `1w`, `1M`.

## Testing alerts over a date range

Run alert rules against historical DB data for a given timestamp range (UTC):

```bash
make test-alerts-range
# or with custom range (from project root):
PYTHONPATH=. python tests/test_alerts_range.py --start 2025-01-01 --end 2025-01-31
PYTHONPATH=. python tests/test_alerts_range.py --ticker ETHUSDT --timeframe 4h --start 2025-01-01 --end 2025-01-15 --limit 200
```

For each candle in the range, the script uses that candle’s OHLC as “current” and runs all rules; it prints timestamp, close price, and any alerts that would have fired.

## Testing Telegram

```bash
make test-telegram
```

Uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the environment or `.env`.
