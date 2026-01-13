# 文件名: data_manager.py
import pandas as pd
import time

class DataManager:  # <--- 请确保这里是 DataManager
    def __init__(self, exchange):
        """
        初始化时，需要传入一个已经连接好的 exchange 对象
        这样可以复用 Driver 的连接，不用建立两次
        """
        self.exchange = exchange

    def fetch_kline(self, symbol, timeframe, limit=500):
        """读取单个周期的 K 线"""
        try:
            bars = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ [数据层] 获取 {timeframe} 失败: {e}")
            return None

    def get_all_timeframes(self, symbol, timeframes_list):
        """
        一次性读取所有需要的周期
        返回一个字典，格式如: {'5m': df1, '1h': df2}
        """
        data_map = {}
        
        for tf in timeframes_list:
            print(f"📡 正在获取 {tf} 数据...")
            df = self.fetch_kline(symbol, tf)
            
            if df is not None:
                data_map[tf] = df
            
            # 为了防止币安报错 (429 Too Many Requests)，稍微停顿
            time.sleep(0.5) 
            
        return data_map