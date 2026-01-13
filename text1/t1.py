import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta

# ================= 配置区域 =================
SYMBOL = 'BTC/USDT'     # 交易对
TIMEFRAME = '5m'        # K线周期
USE_PROXY = True        # 如果你在国内，可能需要开启代理
PROXY_URL = 'http://127.0.0.1:7890' # 替换成你的梯子端口
# ===========================================

def get_binance_data():
    print(f"🔄 正在连接 Binance 获取 {SYMBOL} 最近1小时数据...")
    
    # 1. 初始化交易所 (默认连接合约市场，因为你策略里有做空)
    exchange_config = {
        'timeout': 30000,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}  # ⚠️ 重要：这里指定了是【合约】数据！
    }
    
    # 如果是现货，把上面的 'options' 行注释掉即可

    if USE_PROXY:
        exchange_config['proxies'] = {
            'http': PROXY_URL,
            'https': PROXY_URL,
        }

    exchange = ccxt.binance(exchange_config)

    # 2. 计算时间：获取过去 90 分钟的数据 (确保涵盖过去1小时)
    # 1小时 = 12根5分钟K线，我们要多取几根来计算均线
    limit = 50 
    
    try:
        # 获取 K 线数据
        ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=limit)
        
        # 转换为 DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 3. 【核心】时间处理 - 转换为北京时间
        # API 返回的是 UTC 时间戳 (毫秒)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        # 转换为北京时间 (UTC+8)
        df['datetime_bj'] = df['datetime'] + pd.Timedelta(hours=8)
        
        # 4. 模拟计算 MA31 (为了核对你的策略数据)
        df['MA31'] = df['close'].rolling(31).mean()

        return df
    
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        return None

def print_check_report(df):
    if df is None:
        return

    # 设置 pandas 显示参数，保证列对齐，不省略
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    pd.set_option('display.unicode.ambiguous_as_wide', True)
    pd.set_option('display.unicode.east_asian_width', True)

    # 只截取最后 15 行 (即过去 1 小时左右的数据)
    recent_df = df.tail(15).copy()
    
    print("\n" + "="*80)
    print(f"📊 {SYMBOL} - {TIMEFRAME} K线数据核对表 (北京时间)")
    print("="*80)
    print("说明：时间列显示的是K线【开盘时间】。例如 12:00 代表 12:00-12:05 这根线。")
    print("-" * 80)
    
    # 整理打印格式
    for index, row in recent_df.iterrows():
        time_str = row['datetime_bj'].strftime('%Y-%m-%d %H:%M')
        close_price = row['close']
        open_price = row['open']
        ma31 = row['MA31']
        
        # 标记是否是最近一根 (正在跳动)
        is_current = "👈 (正在跳动/最新)" if index == recent_df.index[-1] else ""
        
        print(f"时间: {time_str} | 开盘: {open_price:<8.2f} | 收盘: {close_price:<8.2f} | MA31: {ma31:<8.2f} {is_current}")

    print("="*80)
    print("💡 核对指南：")
    print("1. 拿出你的手机/电脑看盘软件，找到对应时间点的 K 线。")
    print("2. 重点对比【收盘价】。")
    print("3. 如果收盘价一致，但均线不一致 -> 说明均线算法(SMA/EMA)不同。")
    print("4. 如果收盘价都有几十刀差距 -> 说明你看的是现货，代码跑的是合约(或反之)。")

if __name__ == "__main__":
    df = get_binance_data()
    print_check_report(df)