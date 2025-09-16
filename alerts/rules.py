def check_pivot_alert(candle):
    close = candle['close']
    pivot = candle['indicators']['pivot']
    threshold = 0.01  # 1% threshold

    for level_name, level_value in pivot.items():
        if abs(close - level_value) / level_value < threshold:
            formatted_price = f"${level_value:,.2f}"
            return f"Price is within 1% of {level_name} at {formatted_price}"
    return None


def check_ema_alert(candle):
    close = candle['close']
    high = candle['high']
    low = candle['low']
    ema = candle['indicators']['ema']
    ema_levels = [11, 22, 50, 200]  # Using correct EMA levels

    for level in ema_levels:
        # Check if this EMA level exists in the data
        if str(level) not in ema:
            continue
            
        ema_value = ema[str(level)]
        
        # Check if price touched EMA during the candle range
        if low <= ema_value <= high:
            # Price touched the EMA during the candle
            if close > ema_value:
                return f"Price touched and closed above EMA{level}"
            elif close < ema_value:
                return f"Price touched and closed below EMA{level}"
            else:
                return f"Price touched EMA{level}"
        # Check for crosses at close (fallback for when EMA is outside the range)
        elif close > ema_value:
            return f"Price crossed above EMA{level}"
        elif close < ema_value:
            return f"Price crossed below EMA{level}"
    return None 