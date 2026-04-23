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
