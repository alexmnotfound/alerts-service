.PHONY: run install run-bare test-telegram test-alerts-range docker-build docker-up docker-down clean

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

run: install
	$(PYTHON) monitor.py

install:
	[ -d $(VENV) ] || python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run-bare:
	$(PYTHON) monitor.py

test-telegram: install
	$(PYTHON) test_telegram.py

test-alerts-range: install
	$(PYTHON) test_alerts_range.py --start 2026-02-10 --end 2026-02-11

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf $(VENV) .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
