import ccxt
import pandas as pd
import time
from datetime import datetime

def fetch_binance_futures_data_with_oi(symbol, timeframe, start_str, end_str):
    
    # 1. 初始化交易所 (保持你的代理配置)
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future', 
        },
        'proxies': {
            'http': 'http://127.0.0.1:7890',  # 记得检查你的端口
            'https': 'http://127.0.0.1:7890',
        },
        'timeout': 30000,
    })

    # 2. 转换时间
    since = exchange.parse8601(start_str)
    end_timestamp = exchange.parse8601(end_str)
    
    all_data = []
    
    # !!! 关键修改：Binance OI 接口单次限制通常为 500，为了对齐，我们将 limit 设为 500 !!!
    LIMIT = 500 
    
    print(f"--- 开始下载 [U本位合约] {symbol} [{timeframe}] (含OI数据) ---")
    
    while since < end_timestamp:
        try:
            # === A. 获取 K线数据 (OHLCV) ===
            # 返回格式: [[Timestamp, Open, High, Low, Close, Volume], ...]
            ohlcvs = exchange.fetch_ohlcv(symbol, timeframe, since, limit=LIMIT)
            
            if not ohlcvs:
                print("未获取到K线数据，可能已到头或网络问题，尝试跳出")
                break

            # === B. 获取 持仓量数据 (Open Interest) ===
            # 返回格式: [{'symbol': 'BTC/USDT', 'timestamp': 1600..., 'openInterest': 123...}, ...]
            # 注意：某些旧版本ccxt或冷门币种可能报错，加个try-except保护
            oi_list = []
            try:
                oi_list = exchange.fetch_open_interest_history(symbol, timeframe, since, limit=LIMIT)
            except Exception as e:
                print(f"警告: 获取OI数据失败 (Timestamp: {since}) - {e}")
                # 如果获取失败，oi_list为空，后面逻辑会自动填 None
            
            # === C. 数据对齐与合并 ===
            # 1. 把 OI 数据转成字典，方便按时间戳查找: { timestamp: openInterest_value }
            oi_map = {item['timestamp']: item['openInterest'] for item in oi_list}
            
            batch_data = []
            last_time = ohlcvs[-1][0]
            
            for candle in ohlcvs:
                ts = candle[0]
                
                # 如果当前K线时间超出了结束时间，停止处理
                if ts > end_timestamp:
                    break
                
                # 从 map 中找到对应时间的 OI，找不到则为 None
                oi_value = oi_map.get(ts, None)
                
                # 拼接: [Timestamp, Open, High, Low, Close, Volume, OpenInterest]
                new_row = candle + [oi_value]
                batch_data.append(new_row)

            # 将本批次数据加入总列表
            all_data.extend(batch_data)
            
            # === D. 更新进度与时间 ===
            since = last_time + 1
            
            current_date = datetime.fromtimestamp(last_time / 1000).strftime('%Y-%m-%d %H:%M')
            # 这里的 batch_data[-1][-1] 是最新一条的 OI 值
            last_oi_display = batch_data[-1][-1] if batch_data else 0
            
            print(f"已下载至: {current_date} | 累计: {len(all_data)} 行 | 最新OI: {last_oi_display}")
            
            if last_time >= end_timestamp:
                break
            
            # 因为发了两次请求（K线+OI），建议稍微增加延时，防止触发权重限制
            time.sleep(0.5) 
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)
            continue

    # === E. 保存数据 ===
    if len(all_data) > 0:
        # 定义列名，新增 'OpenInterest'
        columns = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'OpenInterest']
        df = pd.DataFrame(all_data, columns=columns)
        
        df['datetime'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('datetime', inplace=True)
        
        # 处理可能缺失的 OI 数据 (可选：向前填充 ffill)
        # df['OpenInterest'] = df['OpenInterest'].fillna(method='ffill') 
        
        filename = f"FUTURES_OI_{symbol.replace('/', '')}_{timeframe}_{start_str[:4]}.csv"
        df.to_csv(filename)
        print(f"\n下载完成！保存为: {filename}")
        print(f"数据预览:\n{df.tail(3)}")
    else:
        print("无数据下载")

if __name__ == "__main__":
    SYMBOL = 'BTC/USDT'
    TIMEFRAME = '5m'
    
    # 注意：Binance 的 OI 历史数据可能不如 K线数据久远
    # 2021年之前的数据可能会有缺失，属于正常现象
    START = '2026-01-01 00:00:00'
    END =   '2026-01-05 00:00:00' # 测试小范围，跑通了再改大

    fetch_binance_futures_data_with_oi(SYMBOL, TIMEFRAME, START, END)