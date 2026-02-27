.PHONY: run install run-bare test-telegram test-alerts-range docker-build docker-up docker-up-recreate docker-down logs debug-vm clean

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

run: install
	$(PYTHON) -m alerts_service

install:
	[ -d $(VENV) ] || python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run-bare:
	$(PYTHON) -m alerts_service

test-telegram: install
	PYTHONPATH=. $(PYTHON) tests/test_telegram.py

test-alerts-range: install
	PYTHONPATH=. $(PYTHON) tests/test_alerts_range.py --start 2026-02-10 --end 2026-02-11

docker-build:
	docker compose build

docker-up:
	docker compose up -d

# Recreate container so it picks up .env changes (e.g. DB_HOST).
docker-up-recreate:
	docker compose up -d --force-recreate

docker-down:
	docker compose down

logs:
	docker compose logs -f alerts-service

# Debug on VM: show what env the container gets and whether Postgres is reachable.
debug-vm:
	@echo "=== .env (DB/OHLC only) ==="
	@grep -E '^DB_HOST=|^OHLC_API_BASE_URL=' .env 2>/dev/null || echo "(no .env or no these keys)"
	@echo ""
	@echo "=== Env inside container (same as 'docker compose up') ==="
	@docker compose run --no-deps --rm alerts-service env 2>/dev/null | grep -E '^DB_HOST=|^OHLC_API_BASE_URL=' || echo "(run failed - is image built?)"
	@echo ""
	@echo "=== Host: can we reach Postgres on localhost:5432? ==="
	@nc -zv localhost 5432 2>&1 || true
	@echo ""
	@echo "=== Container: resolve host.docker.internal? ==="
	@docker compose run --no-deps --rm alerts-service python -c "import socket; print(socket.gethostbyname('host.docker.internal'))" 2>/dev/null || echo "(resolve failed)"

clean:
	rm -rf $(VENV) .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
