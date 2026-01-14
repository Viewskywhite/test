import ccxt
import pandas as pd
import time
import requests
import pyttsx3

# =================================================================
# 👇👇👇 【配置区域】 👇👇👇
# =================================================================
CONFIG = {
    'SYMBOL': 'BTC/USDT',       
    'TIMEFRAME': '5m',          
    
    # ⚠️ 这里的开关要注意：
    # 如果你在国内本地运行，必须设为 True
    # 如果你在海外服务器(AWS/香港阿里云)运行，设为 False
    'USE_PROXY': False,           
    'PROXY_URL': 'http://127.0.0.1:7890', # 你的梯子端口(Clash通常是7890)
    
    'ENABLE_TTS': True,         
    'ENABLE_BARK': True,        
    'BARK_URL': 'https://api.day.app/MtNFHgi5zjRjdDQPoRJX9j/', 
}
# =================================================================

class AutoAlertBot:
    def __init__(self):
        print("🤖 正在初始化机器人...")
        self.last_signal = None 
        self.engine = None
        
        if CONFIG['ENABLE_TTS']: self._init_voice()

        # 1. 基础配置 (强制 U本位合约)
        exchange_args = {
            'timeout': 30000,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'} 
        }
        
        # 2. 根据开关决定是否挂代理
        if CONFIG['USE_PROXY']:
            print(f"🌍 检测到代理模式开启，正在连接代理: {CONFIG['PROXY_URL']}...")
            exchange_args['proxies'] = {
                'http': CONFIG['PROXY_URL'],
                'https': CONFIG['PROXY_URL']
            }
        else:
            print("🔗 直连模式 (无代理)...")
            
        self.exchange = ccxt.binance(exchange_args)
        print(f"✅ 交易所连接配置完成")

    def _init_voice(self):
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 150)
            voices = self.engine.getProperty('voices')
            for v in voices:
                if 'Chinese' in v.name or 'CN' in v.id:
                    self.engine.setProperty('voice', v.id)
                    break
        except: pass

    def play_sound(self, text):
        if self.engine and CONFIG['ENABLE_TTS']:
            try:
                self.engine.say(f"，{text}")
                self.engine.runAndWait()
            except: pass

    def send_bark(self, title, content):
        if not CONFIG['ENABLE_BARK']: return
        url = f"{CONFIG['BARK_URL'].rstrip('/')}/{title}/{content}"
        try: requests.get(url, timeout=5)
        except: pass

    def fetch_data(self):
        try:
            bars = self.exchange.fetch_ohlcv(CONFIG['SYMBOL'], timeframe=CONFIG['TIMEFRAME'], limit=500)
            return pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as e:
            # 这里如果不打印详细错误，你不知道是因为断网还是别的原因
            print(f"❌ 获取数据失败 (请检查VPN是否开启): {e}")
            return None

    def run(self):
        print(f"🚀 监控已启动 | 目标: {CONFIG['SYMBOL']} | 周期: {CONFIG['TIMEFRAME']}")
        print("=" * 75)
        
        while True:
            try:
                # 1. 获取数据
                df = self.fetch_data()
                if df is None:
                    time.sleep(5)
                    continue

                # 2. 准备计算
                close = pd.to_numeric(df['close'])
                
                # -----------------------------------------------------------
                # ⚠️ 关键修改：全部取 iloc[-2] (上一根收盘确定的K线)
                # 这样 价格 和 均线 都是“死值”，信号绝对稳定，不会闪烁
                # -----------------------------------------------------------
                
                # 基准价格 (上一根收盘价)
                prev_close = float(close.iloc[-2]) 
                
                # 基准均线 (上一根K线算出来的均线)
                ma31 = float(close.rolling(31).mean().iloc[-2])
                ma128 = float(close.rolling(128).mean().iloc[-2])
                ma373 = float(close.rolling(373).mean().iloc[-2])
                
                # 当前最新价 (仅用于给你看盘，不参与信号计算)
                current_price = float(close.iloc[-1]) 

                # 3. 打印详细状态 (分两行打印，清晰明了)
                t_str = time.strftime("%H:%M:%S")
                
                # 第一行：实时行情 (让你知道程序还活着)
                print(f"[{t_str}] 🔴 实时最新价: {current_price:.2f}")
                
                # 第二行：信号判断依据 (这是你最关心的逻辑数据)
                # 逻辑是：用这个收盘价，去对比后面的均线
                print(f"   └── 🟢 信号判断依据(上根收盘): 价格:{prev_close:.2f} | MA31:{ma31:.2f} | MA128:{ma128:.2f} | MA373:{ma373:.2f}")
                print("-" * 60) # 分隔线

                # 4. 信号判断 (使用 prev_close 和 上一根均线)
                new_signal = None
                alert_text = ""

                # --- 开多逻辑 ---
                if (prev_close > ma31) and (ma31 > ma128) and (ma128 > ma373):
                    new_signal = 'LONG'
                    alert_text = f"开多信号确认 (价格{prev_close} > MA31)"
                
                # --- 开空逻辑 ---
                elif (prev_close < ma31) and (ma373 > ma128) and (ma128 > ma31):
                    new_signal = 'SHORT'
                    alert_text = f"开空信号确认 (价格{prev_close} < MA31)"

                # 5. 状态机处理
                if new_signal != self.last_signal:
                    if new_signal:
                        print(f"\n🔥🔥🔥 触发报警: {alert_text} 🔥🔥🔥\n")
                        self.play_sound("趋势确立，" + alert_text)
                        self.send_bark(alert_text, f"确认价:{prev_close}")
                    else:
                        print(">> 信号条件不再满足，恢复观望")
                    
                    self.last_signal = new_signal
                
                # 6. 等待
                time.sleep(10)

            except KeyboardInterrupt:
                print("\n🛑 程序已停止")
                break
            except Exception as e:
                print(f"❌ 运行报错: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = AutoAlertBot()
    bot.run()