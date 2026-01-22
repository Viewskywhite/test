import ccxt
import pandas as pd
import time
import requests
import pyttsx3
import datetime

# =================================================================
# 👇👇👇 【配置区域】 👇👇👇
# =================================================================
CONFIG = {
    # --- 交易对设置 ---
    'SYMBOLS': ['BTC/USDT', 'ETH/USDT'],  # 同时监控BTC和ETH
    
    # --- ⚠️ 时间周期设置 ---
    'TIMEFRAME': '15m',    # 15分钟K线
    
    # --- 策略开关 ---
    'ENABLE_BTC': True,    # 是否启用BTC检测
    'ENABLE_ETH': True,    # 是否启用ETH检测

    # --- 网络与通知 ---
    'USE_PROXY': False,            # ⚠️ 国内请设为 True
    'PROXY_URL': 'http://127.0.0.1:7890',  # 根据你的代理端口修改
    
    'ENABLE_TTS': True,         
    'ENABLE_BARK': True,        
    'BARK_URLS': ['https://api.day.app/MtNFHgi5zjRjdDQPoRJX9j/',
                   'https://api.day.app/HV36M6pFqEbJCAh8eWbbCT/'],
}
# =================================================================

class AutoAlertBot:
    def __init__(self):
        print("🤖 正在初始化15分钟K线检测机器人 (永续合约版)...")
        
        # --- 状态记录 (每个交易对独立记录) ---
        self.last_ts = {
            'BTC/USDT': None,
            'ETH/USDT': None
        }
        
        # --- 数据快照 (用于打印) ---
        self.data_snapshot = {
            'BTC/USDT': {'price': 0, 'ma128': 0, 'ma373': 0, 'last_signal': None},
            'ETH/USDT': {'price': 0, 'ma128': 0, 'ma373': 0, 'last_signal': None}
        }
        
        self.engine = None
        if CONFIG['ENABLE_TTS']: self._init_voice()

        # 初始化交易所连接
        exchange_args = {
            'timeout': 30000, 
            'enableRateLimit': True, 
            'options': {'defaultType': 'future'}  # ⚠️ 强制指定 U本位合约数据
        }
        
        if CONFIG['USE_PROXY']:
            print(f"🌍 代理模式: {CONFIG['PROXY_URL']}")
            exchange_args['proxies'] = {'http': CONFIG['PROXY_URL'], 'https': CONFIG['PROXY_URL']}
        else:
            print("🔗 直连模式")
            
        self.exchange = ccxt.binance(exchange_args)
        symbols_str = ', '.join([s for s in CONFIG['SYMBOLS'] if (s == 'BTC/USDT' and CONFIG['ENABLE_BTC']) or (s == 'ETH/USDT' and CONFIG['ENABLE_ETH'])])
        print(f"✅ 连接成功 | 目标: {symbols_str} (永续合约) | 周期: {CONFIG['TIMEFRAME']}")

    def _init_voice(self):
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 150)
        except: pass


    def send_bark(self, title, content):
        if not CONFIG['ENABLE_BARK']: return
        
        # 获取 URL 列表 (兼容性处理：防止你万一没改配置报错)
        urls = CONFIG.get('BARK_URLS', [])
        # 如果用户还在用老配置 'BARK_URL'，也兼容一下
        if 'BARK_URL' in CONFIG:
            urls.append(CONFIG['BARK_URL'])

        for base_url in urls:
            try:
                # 拼接完整的请求地址
                url = f"{base_url.rstrip('/')}/{title}/{content}"
                
                # 发送请求
                requests.get(url, timeout=2) # 设置2秒超时，防止卡住
                
            except Exception as e:
                # 如果某一个人发送失败（比如网络不好），打印错误但【不中断】程序
                print(f"⚠️ Bark推送失败: {e}")

    def fetch_data(self, symbol, timeframe):
        """获取指定交易对的K线数据"""
        try:
            # 这里的 fetch_ohlcv 会自动使用 init 里设置的 future 选项
            bars = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=400)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ 数据获取失败 [{symbol} {timeframe}]: {e}")
            return None

    # =================================================================
    # 新策略: 15分钟K线检测 - MA128 与 MA373 交叉报警
    # =================================================================
    def check_15m_strategy(self, symbol, df):
        """
        检测逻辑：
        1. 计算 MA128、MA373
        2. 交叉发生在「已经收盘的第一根K线」与「上一根K线」之间（即刚收盘这根形成过程中）
        3. 金叉：上一根 MA128 < MA373，刚收盘根 MA128 > MA373 → 可以多啦
        4. 死叉：上一根 MA128 > MA373，刚收盘根 MA128 < MA373 → 可以空啦
        5. 报警内容保持与原先一致
        """
        if len(df) < 374:  # 需要足够的数据计算 MA373
            return
        
        # 计算 MA128、MA373
        close = pd.to_numeric(df['close'])
        df['ma128'] = close.rolling(128).mean()
        df['ma373'] = close.rolling(373).mean()
        
        # 获取K线：当前根、已收盘第一根、上一根
        # 交叉发生在「已经收盘的第一根」与「上一根」之间（即刚收盘这根形成过程中）
        curr = df.iloc[-1]
        first_closed = df.iloc[-2]   # 已经收盘的第一根K线（刚收盘这根）
        prev_closed = df.iloc[-3]    # 上一根K线
        
        # 更新数据快照
        self.data_snapshot[symbol] = {
            'price': curr['close'],
            'ma128': first_closed['ma128'],
            'ma373': first_closed['ma373'],
            'last_signal': self.data_snapshot[symbol].get('last_signal', None)
        }
        
        # 检查是否已经处理过这根K线（用刚收盘这根的时间戳）
        ts = first_closed['timestamp']
        if self.last_ts[symbol] == ts:
            return
        
        # 上一根 vs 刚收盘这根，判断交叉
        ma128_prev = float(prev_closed['ma128'])
        ma373_prev = float(prev_closed['ma373'])
        ma128_curr = float(first_closed['ma128'])
        ma373_curr = float(first_closed['ma373'])
        
        # 金叉：MA128 上穿 MA373
        golden_cross = (ma128_prev < ma373_prev) and (ma128_curr > ma373_curr)
        # 死叉：MA128 下穿 MA373
        death_cross = (ma128_prev > ma373_prev) and (ma128_curr < ma373_curr)
        
        signal_msg = None
        if golden_cross:
            signal_msg = "可以多啦"
        elif death_cross:
            signal_msg = "可以空啦"
        
        # 触发报警
        if signal_msg:
            if symbol == 'BTC/USDT':
                title = "祝老板发财"
                content = f"'大饼' {signal_msg}"
            else:
                title = "祝老板发财"
                content = f"'小饼' {signal_msg}"
            
            cross_type = "金叉" if golden_cross else "死叉"
            print(f"\n⚡⚡ [{symbol}] {signal_msg} ⚡⚡")
            print(f"   MA128 与 MA373 {cross_type} | 已收盘第一根 MA128: {ma128_curr:.2f} MA373: {ma373_curr:.2f}")
            print(f"   上一根 MA128: {ma128_prev:.2f} MA373: {ma373_prev:.2f}")
            
            self.send_bark(title, content)
            
            if CONFIG['ENABLE_TTS'] and self.engine:
                try:
                    tts_text = f"{symbol.replace('/USDT', '')} {signal_msg}"
                    self.engine.say(tts_text)
                    self.engine.runAndWait()
                except:
                    pass
            
            self.last_ts[symbol] = ts
            self.data_snapshot[symbol]['last_signal'] = signal_msg

    # =================================================================
    # 主循环
    # =================================================================
    def run(self):
        print(f"🚀 监控启动 | 周期: {CONFIG['TIMEFRAME']} | 策略: MA128 与 MA373 交叉报警")
        print("=" * 60)
        
        while True:
            try:
                # 检测BTC
                if CONFIG['ENABLE_BTC']:
                    df_btc = self.fetch_data('BTC/USDT', CONFIG['TIMEFRAME'])
                    if df_btc is not None:
                        self.check_15m_strategy('BTC/USDT', df_btc)
                
                # 检测ETH
                if CONFIG['ENABLE_ETH']:
                    df_eth = self.fetch_data('ETH/USDT', CONFIG['TIMEFRAME'])
                    if df_eth is not None:
                        self.check_15m_strategy('ETH/USDT', df_eth)
                
                # 打印面板
                t_str = datetime.datetime.now().strftime("%H:%M:%S")
                
                print("\n" + "-"*60)
                print(f"⏰ 时间: {t_str} | 交易所: Binance Future (U本位) | 周期: {CONFIG['TIMEFRAME']}")
                
                if CONFIG['ENABLE_BTC']:
                    d_btc = self.data_snapshot['BTC/USDT']
                    print(f"【BTC/USDT】 现价: {d_btc['price']:.2f} | MA128: {d_btc['ma128']:.2f} | MA373: {d_btc['ma373']:.2f}")
                    if d_btc['last_signal']:
                        print(f"    └─ 上次信号: {d_btc['last_signal']}")
                
                if CONFIG['ENABLE_ETH']:
                    d_eth = self.data_snapshot['ETH/USDT']
                    print(f"【ETH/USDT】 现价: {d_eth['price']:.2f} | MA128: {d_eth['ma128']:.2f} | MA373: {d_eth['ma373']:.2f}")
                    if d_eth['last_signal']:
                        print(f"    └─ 上次信号: {d_eth['last_signal']}")
                
                print("-" * 60)
                time.sleep(10)  # 15分钟周期，每10秒检查一次即可

            except KeyboardInterrupt:
                print("\n🛑 程序已停止")
                break
            except Exception as e:
                print(f"\n❌ 主循环报错: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(5)

if __name__ == "__main__":
    bot = AutoAlertBot()
    bot.run()