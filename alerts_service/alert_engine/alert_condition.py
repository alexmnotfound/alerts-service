class AlertCondition:
    """
    Base class for alert conditions
    """
    def __init__(self, ticker, timeframe, alert_type, name="Generic Alert"):
        self.ticker = ticker
        self.timeframe = timeframe
        self.alert_type = alert_type
        self.name = name
        self.triggered = False
    
    def check_condition(self, current_price, indicators_data, ohlc_data):
        """
        Check if the alert condition is met
        To be implemented by subclasses
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_alert_message(self, current_price):
        """
        Generate alert message when triggered
        """
        return f"{self.name} alert triggered for {self.ticker} at price {current_price}"


class PriceThresholdAlert(AlertCondition):
    """
    Alert when price crosses above or below a threshold
    """
    def __init__(self, ticker, timeframe, threshold, direction="above"):
        super().__init__(ticker, timeframe, "Price Threshold")
        self.threshold = threshold
        self.direction = direction
        self.name = f"Price {direction} {threshold}"
    
    def check_condition(self, current_price, indicators_data, ohlc_data):
        if self.direction == "above" and current_price > self.threshold:
            self.triggered = True
            return True
        elif self.direction == "below" and current_price < self.threshold:
            self.triggered = True
            return True
        return False


class EMAAlert(AlertCondition):
    """
    Alert when price crosses above or below an EMA
    """
    def __init__(self, ticker, timeframe, ema_period, direction="cross_above"):
        super().__init__(ticker, timeframe, "EMA Cross")
        self.ema_period = ema_period
        self.direction = direction
        self.name = f"Price {direction.replace('_', ' ')} EMA{ema_period}"
    
    def check_condition(self, current_price, indicators_data, ohlc_data):
        if not indicators_data or 'ema' not in indicators_data:
            return False
        
        ema_data = indicators_data['ema']
        filtered_ema = [e for e in ema_data if e['period'] == self.ema_period]
        
        if not filtered_ema:
            return False
        
        ema_value = filtered_ema[0]['value']
        
        if self.direction == "cross_above" and current_price > ema_value:
            # Check if previous price was below EMA
            if len(ohlc_data) > 1 and ohlc_data[1]['close'] < ema_value:
                self.triggered = True
                return True
        elif self.direction == "cross_below" and current_price < ema_value:
            # Check if previous price was above EMA
            if len(ohlc_data) > 1 and ohlc_data[1]['close'] > ema_value:
                self.triggered = True
                return True
        
        return False


class RSIAlert(AlertCondition):
    """
    Alert when RSI crosses above or below a threshold
    """
    def __init__(self, ticker, timeframe, rsi_period, threshold, direction="above"):
        super().__init__(ticker, timeframe, "RSI Alert")
        self.rsi_period = rsi_period
        self.threshold = threshold
        self.direction = direction
        self.name = f"RSI{rsi_period} {direction} {threshold}"
    
    def check_condition(self, current_price, indicators_data, ohlc_data):
        if not indicators_data or 'rsi' not in indicators_data:
            return False
        
        rsi_data = indicators_data['rsi']
        filtered_rsi = [r for r in rsi_data if r['period'] == self.rsi_period]
        
        if not filtered_rsi:
            return False
        
        rsi_value = filtered_rsi[0]['value']
        
        if self.direction == "above" and rsi_value > self.threshold:
            self.triggered = True
            return True
        elif self.direction == "below" and rsi_value < self.threshold:
            self.triggered = True
            return True
        
        return False


class ChandelierExitAlert(AlertCondition):
    """
    Alert when Chandelier Exit changes direction
    """
    def __init__(self, ticker, timeframe, signal_type="buy"):
        super().__init__(ticker, timeframe, "Chandelier Exit")
        self.signal_type = signal_type
        self.name = f"Chandelier Exit {signal_type.capitalize()} Signal"
    
    def check_condition(self, current_price, indicators_data, ohlc_data):
        if not indicators_data or 'ce' not in indicators_data:
            return False
        
        ce_data = indicators_data['ce']
        
        if not ce_data:
            return False
        
        latest_ce = ce_data[0]
        
        if self.signal_type == "buy" and latest_ce['buy_signal']:
            self.triggered = True
            return True
        elif self.signal_type == "sell" and latest_ce['sell_signal']:
            self.triggered = True
            return True
        
        return False 