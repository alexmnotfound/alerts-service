# Alerts service. Copy .env.example to .env and set DB_*, OHLC_API_BASE_URL, Telegram.

.PHONY: build up down logs recreate run install test clean

# Docker (same targets as ohlc_handler)
build:
	docker compose build

up:
	docker compose up -d

recreate:
	docker compose up -d --force-recreate

down:
	docker compose down

logs:
	docker compose logs -f alerts-service

# Local run
install:
	[ -d venv ] || python3 -m venv venv
	venv/bin/pip install -r requirements.txt

run: install
	venv/bin/python -m alerts_service

test: install
	PYTHONPATH=. venv/bin/python tests/test_telegram.py
	PYTHONPATH=. venv/bin/python tests/test_alerts_range.py --start 2026-02-10 --end 2026-02-11

clean:
	rm -rf venv .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
