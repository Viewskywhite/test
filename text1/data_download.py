import ccxt
import pandas as pd
import time
from datetime import datetime

import ccxt
# ... 其他引用保持不变 ...

def fetch_binance_futures_data(symbol, timeframe, start_str, end_str):
    
    # === 关键修改在这里 ===
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future', 
        },
        # !!! 在这里添加代理配置 !!!
        # 如果你的梯子开着，但代码没加这段，Python是连不上网的。
        # 请检查你的代理软件，端口是 7890 还是 10809 或其他？
        'proxies': {
            'http': 'http://127.0.0.1:7890',  # <--- 如果你的端口是10809，请改为10809
            'https': 'http://127.0.0.1:7890', # <--- 同上
        },
        'timeout': 30000, # 设置超时时间为30秒，防止网络波动直接报错
    })

    # ... 下面的代码保持不变 ...

    # 转换时间
    since = exchange.parse8601(start_str)
    end_timestamp = exchange.parse8601(end_str)
    
    all_candles = []
    
    print(f"--- 开始下载 [U本位合约] {symbol} [{timeframe}] ---")
    
    while since < end_timestamp:
        try:
            # 获取数据
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            
            if not candles:
                break
            
            last_time = candles[-1][0]
            
            # 过滤超出时间范围的数据
            batch = [c for c in candles if c[0] <= end_timestamp]
            all_candles.extend(batch)
            
            since = last_time + 1
            
            # 打印进度
            current_date = datetime.fromtimestamp(last_time / 1000).strftime('%Y-%m-%d %H:%M')
            print(f"已下载至: {current_date} | 累计: {len(all_candles)}")
            
            if last_time >= end_timestamp:
                break
            
            time.sleep(0.2) # 合约接口频率限制有时候比现货严一点，稍慢一点更稳
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue

    if len(all_candles) > 0:
        # 定义列名
        # 合约数据的Volume通常指"成交数量(币)", 部分策略可能需要"成交金额(USDT)"
        # ccxt的标准返回一般是: [Timestamp, Open, High, Low, Close, Volume]
        df = pd.DataFrame(all_candles, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        
        df['datetime'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('datetime', inplace=True)
        
        # 保存时加上 futures 标识，防止混淆
        filename = f"FUTURES_{symbol.replace('/', '')}_{timeframe}_{start_str[:4]}.csv"
        df.to_csv(filename)
        print(f"下载完成，保存为: {filename}")
    else:
        print("无数据")

if __name__ == "__main__":
    # U本位合约通常也是用 'BTC/USDT' 这个符号
    # 因为我们在 options 里指定了 defaultType='future'，ccxt 会自动把它映射到合约接口
    SYMBOL = 'BTC/USDT'
    TIMEFRAME = '5m'
    
    # 建议下载时间：最近2-3年比较有参考价值
    START = '2020-01-01 00:00:00'
    END =   '2026-01-01 00:00:00'

    fetch_binance_futures_data(SYMBOL, TIMEFRAME, START, END)