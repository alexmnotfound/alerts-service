import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

class Database:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        if self.conn is None:
            try:
                self.conn = psycopg2.connect(
                    host=os.getenv("DB_HOST"),
                    port=os.getenv("DB_PORT"),
                    dbname=os.getenv("DB_NAME"),
                    user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD")
                )
                self.conn.autocommit = True
                print("Database connection established successfully")
            except Exception as e:
                print(f"Database connection error: {e}")
                raise e
    
    def get_cursor(self):
        self.connect()
        return self.conn.cursor(cursor_factory=RealDictCursor)
    
    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
    
    def get_latest_ohlc(self, ticker, timeframe, limit=100):
        """Get the latest OHLC data from the database"""
        cursor = self.get_cursor()
        query = """
            SELECT * FROM ohlc_data 
            WHERE ticker = %s AND timeframe = %s 
            ORDER BY timestamp DESC 
            LIMIT %s
        """
        cursor.execute(query, (ticker, timeframe, limit))
        results = cursor.fetchall()
        cursor.close()
        return results
    
    def get_indicators(self, ticker, timeframe, indicator_type, limit=100):
        """Get the technical indicators from the database"""
        cursor = self.get_cursor()
        
        if indicator_type == 'ema':
            table = 'ema_data'
        elif indicator_type == 'ce':
            table = 'ce_data'
        elif indicator_type == 'obv':
            table = 'obv_data'
        elif indicator_type == 'rsi':
            table = 'rsi_data'
        elif indicator_type == 'pivot':
            table = 'pivot_data'
        else:
            raise ValueError(f"Unsupported indicator type: {indicator_type}")
        
        query = f"""
            SELECT * FROM {table} 
            WHERE ticker = %s AND timeframe = %s 
            ORDER BY timestamp DESC 
            LIMIT %s
        """
        cursor.execute(query, (ticker, timeframe, limit))
        results = cursor.fetchall()
        cursor.close()
        return results 