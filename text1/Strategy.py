import pandas as pd

class Strategy:
    def __init__(self, config):
        self.cfg = config

    def analyze(self, df):
        """
        输入: K线数据 (DataFrame)
        输出: 信号 ('buy', 'sell', 或 None)
        """
        # 长度检查：因为要计算 MA128，数据长度至少要大于 128
        if df is None or len(df) < 130:
            return None

        # 1. 数据准备
        close = pd.to_numeric(df['close'])
        
        # === 关键修改：计算指定的均线 (MA31 和 MA128) ===
        # 这里直接使用 31 和 128，确保符合你的策略描述
        # 如果你想用 config 里的变量，可以改成 self.cfg.MA_FAST 等
        ma31_series = close.rolling(31).mean()
        ma128_series = close.rolling(128).mean()
        
        # === 获取数值 (强制转 float 防止报错) ===
        # 这里的逻辑与你 AlertSystem 保持一致：
        # 价格：看“上一根”收盘价 (iloc[-2]) -> 信号确定的价格
        # 均线：看“当前”均线值 (iloc[-1]) -> 最新的趋势
        prev_close = float(close.iloc[-2])
        
        ma31_curr = float(ma31_series.iloc[-1])
        ma128_curr = float(ma128_series.iloc[-1])

        # 打印分析日志
        print(f"📊 策略分析: 上根收盘:{prev_close:.2f} | MA31:{ma31_curr:.2f} | MA128:{ma128_curr:.2f}")

        # 2. 生成信号
        # === 开多条件 ===
        # 条件1: 上一根收盘价 > MA31
        # 条件2: MA31 > MA128 (多头排列)
        if (prev_close > ma31_curr) and (ma31_curr > ma128_curr):
            return 'buy'
        
        # === 开空条件 ===
        # 你这次没提开空条件，为了防止旧代码干扰，我先注释掉
        # 如果需要，可以在这里加 elif 逻辑，比如:
        # elif (prev_close < ma373_curr):
        #     return 'sell'

        return None # 无信号