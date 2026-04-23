import pytest
from unittest.mock import patch, MagicMock


def _make_mock_connection(rows, build_return=None):
    """Helper: returns a mock context-manager connection whose cursor yields given rows."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = rows
    mock_cursor.fetchone.return_value = build_return
    mock_conn_obj = MagicMock()
    mock_conn_obj.__enter__ = MagicMock(return_value=mock_conn_obj)
    mock_conn_obj.__exit__ = MagicMock(return_value=False)
    mock_conn_obj.cursor.return_value = mock_cursor
    return mock_conn_obj


def test_fetch_recent_candles_returns_list():
    from alerts_service.db import fetch_recent_candles_with_indicators

    fake_row = {
        "ticker": "BTCUSDT", "timeframe": "1h",
        "timestamp": "2026-01-01T00:00:00", "open": 99.0, "high": 101.0,
        "low": 98.0, "close": 100.0, "volume": 1000.0, "candle_pattern": None,
    }

    with patch("alerts_service.db.get_connection") as mock_conn, \
         patch("alerts_service.db._build_candle_with_indicators") as mock_build:
        mock_conn.return_value = _make_mock_connection([fake_row])
        mock_build.return_value = {"close": 100.0, "timestamp": "2026-01-01T00:00:00"}
        result = fetch_recent_candles_with_indicators("BTCUSDT", "1h", limit=5)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["close"] == 100.0


def test_fetch_recent_candles_empty_returns_list():
    from alerts_service.db import fetch_recent_candles_with_indicators
    with patch("alerts_service.db.get_connection") as mock_conn:
        mock_conn.return_value = _make_mock_connection([])
        result = fetch_recent_candles_with_indicators("BTCUSDT", "1h", limit=5)
    assert result == []


def test_fetch_recent_candles_oldest_first():
    from datetime import datetime
    from unittest.mock import patch, MagicMock
    from alerts_service.db import fetch_recent_candles_with_indicators

    row1 = {"ticker": "BTCUSDT", "timeframe": "1h", "timestamp": datetime(2026, 1, 1, 1),
            "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000, "candle_pattern": None}
    row2 = {"ticker": "BTCUSDT", "timeframe": "1h", "timestamp": datetime(2026, 1, 1, 2),
            "open": 101, "high": 102, "low": 100, "close": 101.5, "volume": 1200, "candle_pattern": None}
    # DB returns DESC order (newest first), function should reverse to oldest-first
    db_rows = [row2, row1]

    with patch("alerts_service.db.get_connection") as mock_conn, \
         patch("alerts_service.db._build_candle_with_indicators", side_effect=lambda conn, cur, t, tf, row: row):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = db_rows
        mock_conn_obj = MagicMock()
        mock_conn_obj.__enter__ = MagicMock(return_value=mock_conn_obj)
        mock_conn_obj.__exit__ = MagicMock(return_value=False)
        mock_conn_obj.cursor.return_value = mock_cursor
        mock_conn.return_value = mock_conn_obj

        result = fetch_recent_candles_with_indicators("BTCUSDT", "1h", limit=2)

    assert len(result) == 2
    assert result[0]["timestamp"] < result[1]["timestamp"]  # oldest first


# ---------------------------------------------------------------------------
# Pivot retest detection tests
# ---------------------------------------------------------------------------

def _make_candle(close, high, low, open_, volume, pivot_pp, pivot_r1, pivot_s1, atr_value, month=1):
    from datetime import datetime
    return {
        "timestamp": datetime(2026, month, 1),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "indicators": {
            "pivot": {
                "pp": pivot_pp, "r1": pivot_r1, "s1": pivot_s1,
                "r2": None, "r3": None, "r4": None, "r5": None,
                "s2": None, "s3": None, "s4": None, "s5": None,
            },
            "ce": {"atr_value": atr_value * 3.0},
        },
    }


def test_no_breakdown_no_retest_short():
    from alerts_service.alerts.pivot_retest import detect_pivot_retest_short
    pp = 100.0
    # All candles close above PP — no breakdown ever
    candles = [_make_candle(close=105, high=106, low=104, open_=105, volume=1000,
                             pivot_pp=pp, pivot_r1=115, pivot_s1=90, atr_value=2.0)
               for _ in range(10)]
    assert detect_pivot_retest_short(candles) is None


def test_short_retest_fires():
    from alerts_service.alerts.pivot_retest import detect_pivot_retest_short
    pp = 100.0
    atr = 2.0
    # 20 seed candles above PP (to build vol SMA)
    seed = [_make_candle(close=102, high=103, low=101, open_=101.5, volume=1000,
                          pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
            for _ in range(20)]
    # Breakdown candle: prev_close=102 (>=pp=100), close=98 (<pp), high vol
    seed[-1] = _make_candle(close=98, high=103, low=97, open_=102, volume=3000,
                             pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    # Filler: close below PP
    filler = _make_candle(close=96, high=98, low=95, open_=97, volume=800,
                           pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    # Retest: high>=pp=100, close<pp, upper_wick = 101 - max(97,98) = 3 >= 0.3*2=0.6
    retest = _make_candle(close=98, high=101, low=96, open_=97, volume=900,
                           pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    candles = seed + [filler, retest]
    result = detect_pivot_retest_short(candles)
    assert result is not None
    assert "SHORT" in result
    assert "PP" in result


def test_long_retest_fires():
    from alerts_service.alerts.pivot_retest import detect_pivot_retest_long
    pp = 100.0
    atr = 2.0
    # 20 seed candles below PP
    seed = [_make_candle(close=98, high=99, low=97, open_=98, volume=1000,
                          pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
            for _ in range(20)]
    # Breakout: prev_close=98 (<=pp=100), close=103 (>pp), high vol
    seed[-1] = _make_candle(close=103, high=104, low=98, open_=98.5, volume=3000,
                             pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    # Filler above PP
    filler = _make_candle(close=105, high=106, low=104, open_=105, volume=800,
                           pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    # Retest: low<=pp=100, close>pp, lower_wick = min(101,102)-99 = 2 >= 0.3*2=0.6
    retest = _make_candle(close=102, high=104, low=99, open_=101, volume=900,
                           pivot_pp=pp, pivot_r1=115, pivot_s1=85, atr_value=atr)
    candles = seed + [filler, retest]
    result = detect_pivot_retest_long(candles)
    assert result is not None
    assert "LONG" in result
    assert "PP" in result


def test_returns_none_if_too_few_candles():
    from alerts_service.alerts.pivot_retest import detect_pivot_retest_short
    assert detect_pivot_retest_short([]) is None
    assert detect_pivot_retest_short([_make_candle(100, 101, 99, 100, 1000, 90, 110, 80, 2.0)]) is None


# ---------------------------------------------------------------------------
# monitor.py integration tests
# ---------------------------------------------------------------------------

def _import_monitor_with_telegram_mocked():
    """Import alerts_service.monitor with telegram stubbed out (not installed in test env)."""
    import sys
    from unittest.mock import MagicMock
    # Stub telegram before monitor is imported so notifier.py doesn't blow up
    for mod in ("telegram", "telegram.ext", "telegram.error"):
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    # Force re-import in case monitor was cached from a failed attempt
    sys.modules.pop("alerts_service.monitor", None)
    import alerts_service.monitor as monitor_mod
    return monitor_mod


def test_process_ticker_pivot_retest_no_candles():
    """Should return without error when no candles available."""
    from unittest.mock import patch
    monitor_mod = _import_monitor_with_telegram_mocked()
    with patch.object(monitor_mod, "fetch_recent_candles_with_indicators", return_value=[]):
        monitor_mod.process_ticker_pivot_retest("BTCUSDT")  # should not raise


def test_process_ticker_pivot_retest_sends_alert():
    """Should call send_consolidated_alert when a retest is detected."""
    from unittest.mock import patch, MagicMock
    fake_candles = [{"close": 90000.0}] * 50
    monitor_mod = _import_monitor_with_telegram_mocked()

    with patch.object(monitor_mod, "fetch_recent_candles_with_indicators", return_value=fake_candles), \
         patch.object(monitor_mod, "detect_pivot_retest_short", return_value="Pivot Retest SHORT — PP @ 90,000.00 | wick 100.00 | atr 500.00"), \
         patch.object(monitor_mod, "detect_pivot_retest_long", return_value=None), \
         patch.object(monitor_mod, "send_consolidated_alert") as mock_send, \
         patch.object(monitor_mod, "_apply_cooldown", return_value=(["Pivot Retest SHORT — PP @ 90,000.00 | wick 100.00 | atr 500.00"], {("1h", "pivot_retest_short")})):
        monitor_mod.process_ticker_pivot_retest("BTCUSDT")
    mock_send.assert_called_once()
