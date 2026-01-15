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
                # 2. 准备计算
                close = pd.to_numeric(df['close'])
                
                # --- A. 预先计算完整的均线序列 (因为我们要回溯前几根) ---
                ma31_series = close.rolling(31).mean()
                ma128_series = close.rolling(128).mean()
                ma373_series = close.rolling(373).mean()
                
                # --- B. 定义一个判断函数 (检查某根K线收盘价是否大于三条均线) ---
                def is_bullish_breakout(idx):
                    p = float(close.iloc[idx])
                    m1 = float(ma31_series.iloc[idx])
                    m2 = float(ma128_series.iloc[idx])
                    m3 = float(ma373_series.iloc[idx])
                    # 条件：收盘价 同时大于 三条均线
                    return (p > m1) and (p > m2) and (p > m3)

                def is_bearish_breakout(idx):
                    p = float(close.iloc[idx])
                    m1 = float(ma31_series.iloc[idx])
                    m2 = float(ma128_series.iloc[idx])
                    m3 = float(ma373_series.iloc[idx])
                    # 条件：收盘价 同时小于 三条均线
                    return (p < m1) and (p < m2) and (p < m3)

                # --- C. 获取关键数据 (用于显示和逻辑) ---
                # 当前最新价 (仅展示)
                current_price = float(close.iloc[-1])
                # 上一根完成的K线 (T) 的收盘价
                prev_close = float(close.iloc[-2])
                
                # --- D. 执行“前4根”逻辑检测 ---
                # T= -2 (最新完成), T-1= -3, T-2= -4, T-3= -5
                
                # 1. 检查最新完成的那一根 (必须满足条件)
                bull_current = is_bullish_breakout(-2)
                bear_current = is_bearish_breakout(-2)
                
                # 2. 检查前3根 (必须【不】满足条件)
                # 只要前3根里，有任意一根满足了条件，就说明早就突破了，不是“首次”
                # 所以要求：前3根全部为 False
                bull_pre_check = (not is_bullish_breakout(-3)) and \
                                 (not is_bullish_breakout(-4)) and \
                                 (not is_bullish_breakout(-5))
                                 
                bear_pre_check = (not is_bearish_breakout(-3)) and \
                                 (not is_bearish_breakout(-4)) and \
                                 (not is_bearish_breakout(-5))

                # 3. 打印详细状态
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] 🔴 实时最新价: {current_price:.2f} 检测线收盘价：{prev_close}")
                print(f"   └── 🔎 突破检测(T=-2): {'✅满足' if bull_current or bear_current else '❌未满足'} | 前三根保持沉寂: {'✅是' if bull_pre_check or bear_pre_check else '❌否(已有前值)'}")
                print("-" * 60)

                # 4. 信号判断
                new_signal = None
                alert_text = ""

                # --- 开多逻辑 ---
                # 逻辑：当前K线站上均线 AND 前三根K线都在均线之下(或未完全站上)
                if bull_current and bull_pre_check:
                    new_signal = 'LONG'
                    alert_text = f"多头起爆确认 (价格{prev_close:.2f} 首次站上三均线)"
                
                # --- 开空逻辑 ---
                # 逻辑：当前K线跌破均线 AND 前三根K线都在均线之上(或未完全跌破)
                elif bear_current and bear_pre_check:
                    new_signal = 'SHORT'
                    alert_text = f"空头起爆确认 (价格{prev_close:.2f} 首次跌破三均线)"
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
                time.sleep(5)

            except KeyboardInterrupt:
                print("\n🛑 程序已停止")
                break
            except Exception as e:
                print(f"❌ 运行报错: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = AutoAlertBot()
    bot.run()