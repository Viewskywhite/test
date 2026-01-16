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
    'SYMBOL': 'BTC/USDT',       
    
    # --- ⚠️ 时间周期设置 ---
    'TF_2MA': '1h',    
    'TF_3MA': '5m',    
    
    # --- 策略开关 ---
    'ENABLE_STRATEGY_2MA': True,   # ✅ 1小时策略 (穿线 + 偏离)
    'ENABLE_STRATEGY_3MA': False,   # ✅ 5分钟策略 (排列起爆)

    # --- 网络与通知 ---
    'USE_PROXY': False,            # ⚠️ 国内请设为 True
    'PROXY_URL': 'http://127.0.0.1:7890',
    
    'ENABLE_TTS': True,         
    'ENABLE_BARK': True,        
    'BARK_URLS': ['https://api.day.app/MtNFHgi5zjRjdDQPoRJX9j/',
                   'https://api.day.app/HV36M6pFqEbJCAh8eWbbCT/'],
}
# =================================================================

class AutoAlertBot:
    def __init__(self):
        print("🤖 正在初始化双周期机器人 (合约版)...")
        
        # --- 状态记录 ---
        self.last_ts_2ma = None
        self.last_ts_3ma = None
        self.last_dev_time = 0
        
        # --- 数据快照 (用于打印) ---
        self.data_snapshot = {
            '1h': {'price': 0, 'ma128': 0, 'ma373': 0, 'ratio': 0, 'is_closed': False},
            '5m': {'price': 0, 'ma31': 0, 'ma128': 0, 'ma373': 0}
        }
        
        self.engine = None
        if CONFIG['ENABLE_TTS']: self._init_voice()

        # 👇👇👇【核心修改】确保完全匹配测试脚本的获取方式 👇👇👇
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
        print(f"✅ 连接成功 | 目标: {CONFIG['SYMBOL']} (永续合约)")

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

    def fetch_data(self, timeframe):
        try:
            # 这里的 fetch_ohlcv 会自动使用 init 里设置的 future 选项
            bars = self.exchange.fetch_ohlcv(CONFIG['SYMBOL'], timeframe=timeframe, limit=500)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ 数据获取失败 [{timeframe}]: {e}")
            return None

    # =================================================================
    # 策略 1: 两均线 (1H) - 这里的偏离检测已改为 iloc[-2]
    # =================================================================
    def check_strategy_2ma_1h(self, df):
        if not CONFIG['ENABLE_STRATEGY_2MA']: return
        
        close = pd.to_numeric(df['close'])
        df['ma128'] = close.rolling(128).mean()
        df['ma373'] = close.rolling(373).mean()

        curr = df.iloc[-1]  # 实时K线 (仅用于显示现价)
        conf = df.iloc[-2]  # ⚠️ 上一根已收盘K线 (用于所有逻辑检测)
        trig = df.iloc[-3]  # 触发线 (T-2)

        # --- A. 偏离值检测 (改为检测上一根 conf) ---
        dev_msg = None
        ratio_val = 0.0
        
        ma373_val = float(conf['ma373'])
        conf_close = float(conf['close'])
        
        if ma373_val > 0:
            if conf_close > ma373_val: 
                # 阳线/上方: 用上一根的最高价算
                ratio_val = float(conf['high']) / ma373_val
                if ratio_val > 1.068: 
                    dev_msg = f"⚠️ [1H]多偏离过多 (R:{ratio_val:.4f})"
            else: 
                # 阴线/下方: 用上一根的最低价算
                ratio_val = float(conf['low']) / ma373_val
                if ratio_val < 0.932: 
                    dev_msg = f"⚠️ [1H]空偏离过多 (R:{ratio_val:.4f})"

        # 🟢 保存快照用于打印 (注意：这里 ratio 显示的是上一根确定的值)
        self.data_snapshot['1h'] = {
            'price': curr['close'],      # 还是显示实时价格
            'ma128': conf['ma128'],      # 显示上一根的确切均线
            'ma373': conf['ma373'],
            'ratio': ratio_val,          # 显示上一根的确切偏离
            'is_closed': True
        }

        # 执行偏离报警 (300秒冷却)
        if dev_msg and (time.time() - self.last_dev_time > 300):
            print(f"\n🚨 {dev_msg}")
            print(f"   (基于上一根1H收盘K线检测，非实时插针)")
            self.send_bark("偏离过多", dev_msg)
            self.last_dev_time = time.time()

        # --- B. 穿线开仓逻辑 (保持不变) ---
        ts = conf['timestamp']
        if self.last_ts_2ma == ts: return

        trig_top = max(trig['open'], trig['close'])
        trig_bot = min(trig['open'], trig['close'])
        
        ma128_in = (trig['ma128'] > trig_bot) and (trig['ma128'] < trig_top)
        ma373_in = (trig['ma373'] > trig_bot) and (trig['ma373'] < trig_top)
        
        if ma128_in and (not ma373_in):
            signal_msg = None
            # 多头: 128>373, 触发阳, 确认阳, 确认Low>128
            if (trig['ma128'] > trig['ma373']) and (trig['close'] > trig['open']) and \
               (conf['close'] > conf['open']) and (conf['low'] > conf['ma128']):
                signal_msg = "可以开多啦"

            # 空头: 128<373, 触发阴, 确认阴, 确认High<128
            elif (trig['ma128'] < trig['ma373']) and (trig['close'] < trig['open']) and \
                 (conf['close'] < conf['open']) and (conf['high'] < conf['ma128']):
                signal_msg = "可以开空啦"

            if signal_msg:
                print(f"\n⚡⚡ {signal_msg} ⚡⚡")
                self.send_bark("九道盟策略提醒老板发财：", signal_msg)
                self.last_ts_2ma = ts

    # =================================================================
    # 策略 2: 三均线 (5m)
    # =================================================================
    def check_strategy_3ma_5m(self, df):
        if not CONFIG['ENABLE_STRATEGY_3MA']: return
        
        close = pd.to_numeric(df['close'])
        df['ma31'] = close.rolling(31).mean()
        df['ma128'] = close.rolling(128).mean()
        df['ma373'] = close.rolling(373).mean()
        
        curr = df.iloc[-1]
        row_curr = df.iloc[-2] # T-1
        row_prev1 = df.iloc[-3]
        row_prev2 = df.iloc[-4]
        
        self.data_snapshot['5m'] = {
            'price': row_curr['close'],
            'ma31': row_curr['ma31'],
            'ma128': row_curr['ma128'],
            'ma373': row_curr['ma373']
        }

        ts = row_curr['timestamp']
        if self.last_ts_3ma == ts: return 

        def check_status(row):
            p, m1, m2, m3 = row['close'], row['ma31'], row['ma128'], row['ma373']
            is_bull = (p > m1) and (m1 > m2) and (m2 > m3)
            is_bear = (p < m1) and (m1 < m2) and (m2 < m3) 
            return is_bull, is_bear

        bull_c, bear_c = check_status(row_curr)
        bull_p1, bear_p1 = check_status(row_prev1)
        bull_p2, bear_p2 = check_status(row_prev2)

        signal_msg = None
        if bull_c and (not bull_p1) and (not bull_p2):
            signal_msg = f" [5m] 可以开多啦 (31>128>373)"
        
        elif bear_c and (not bear_p1) and (not bear_p2):
            signal_msg = f" [5m] 可以开空啦 (31<128<373)"
            
        if signal_msg:
            print(f"\n🌊🌊 {signal_msg} 🌊🌊")
            self.send_bark("老板发财", signal_msg)
            self.last_ts_3ma = ts

    # =================================================================
    # 主循环
    # =================================================================
    def run(self):
        print(f"🚀 监控启动 (合约版) | 1h偏离检测改为: 上一根收盘K线")
        print("=" * 60)
        
        while True:
            try:
                # 1. 运行 1H (偏离改为上一根)
                if CONFIG['ENABLE_STRATEGY_2MA']:
                    df_1h = self.fetch_data(CONFIG['TF_2MA'])
                    if df_1h is not None: self.check_strategy_2ma_1h(df_1h)
                
                # 2. 运行 5m
                if CONFIG['ENABLE_STRATEGY_3MA']:
                    df_5m = self.fetch_data(CONFIG['TF_3MA'])
                    if df_5m is not None: self.check_strategy_3ma_5m(df_5m)
                
                # 3. 打印面板
                t_str = datetime.datetime.now().strftime("%H:%M:%S")
                d1 = self.data_snapshot['1h']
                d5 = self.data_snapshot['5m']
                
                print("\n" + "-"*50)
                print(f"⏰ 时间: {t_str} | 交易所: Binance Future (U本位)")
                
                if CONFIG['ENABLE_STRATEGY_2MA']:
                    print(f"【1H 数据】 现价: {d1['price']:.2f}")
                    print(f"    └─ MA128: {d1['ma128']:.2f} | MA373: {d1['ma373']:.2f}")
                    # 显示这是一个基于上一根K线的计算值
                    print(f"    └─ [上一根]偏离比: {d1['ratio']:.4f} (阈值 >1.068 / <0.932)")
                
                if CONFIG['ENABLE_STRATEGY_3MA']:
                    print(f"【5m 数据】 上根收盘: {d5['price']:.2f}")
                    status = "无序震荡"
                    if d5['ma31'] > d5['ma128'] > d5['ma373']: status = "多头排列 ✅"
                    elif d5['ma31'] < d5['ma128'] < d5['ma373']: status = "空头排列 ❄️"
                    print(f"    └─ 状态: {status}")
                
                print("-" * 50)
                time.sleep(5)

            except KeyboardInterrupt:
                print("\n🛑 程序已停止")
                break
            except Exception as e:
                print(f"\n❌ 主循环报错: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = AutoAlertBot()
    bot.run()