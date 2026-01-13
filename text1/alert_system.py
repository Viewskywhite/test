import pandas as pd
import platform
import time
import pyttsx3
import requests     # 网络请求库
from config import Config  # 引入配置

class AlertSystem:
    def __init__(self):
        # 【核心修改】只记录上一次的状态，不需要计数器了
        # 初始状态为 None，代表刚启动时什么信号都不是
        self.last_signal_type = None 
        self.is_first_run = True  # 标记是否为第一次运行

        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 150)
            # 尝试设置中文语音
            try:
                voices = self.engine.getProperty('voices')
                for v in voices:
                    if 'Chinese' in v.name or 'CN' in v.id:
                        self.engine.setProperty('voice', v.id)
                        break
            except:
                pass
        except Exception as e:
            print(f"⚠️ 语音引擎初始化失败: {e}")
            self.engine = None

    def play_sound(self, speech_text):
        """让电脑说话 (修复版)"""
        if not self.engine:
            return
        try:
            # 必须放在 try 块中，防止音频驱动报错卡死主程序
            self.engine.say(f"，{speech_text}")
            self.engine.runAndWait()
        except Exception as e:
            print(f"❌ 语音播报出错: {e}")
    def send_bark_push(self, title, content):
        """发送 Bark 手机推送"""
        if not getattr(Config, 'ENABLE_BARK', False):
            return

        base_url = Config.BARK_URL
        if not base_url.endswith('/'):
            base_url += '/'
        
        safe_title = str(title).strip()
        safe_content = str(content).replace(' ', '_').replace('：', ':').replace('，', ',')
        
        full_url = f"{base_url}{safe_title}/{safe_content}"

        for i in range(2):
            try:
                requests.get(full_url, timeout=10)
                print(f"📱 Bark 推送成功: {safe_title}")
                return
            except Exception:
                time.sleep(1)
        print("❌ Bark 推送最终失败")

    def check_signal(self, df):
        """
        检查信号 (状态机模式：仅在状态改变时触发一次)
        """
        if df is None or len(df) < 375:
            return

        # 1. 准备数据
        close = pd.to_numeric(df['close'])
        
        # 价格使用上一根收盘价 (比大小用)
        prev_close = float(close.iloc[-2])
        # 现价用于显示
        current_price = float(close.iloc[-1])
        
        # 均线使用当前最新值
        ma31_curr = float(close.rolling(31).mean().iloc[-1])      #修改均线
        ma128_curr = float(close.rolling(128).mean().iloc[-1])
        ma373_curr = float(close.rolling(373).mean().iloc[-1])
        
        print(f"[监控] 上根收盘:{prev_close:.2f} | 现价:{current_price:.2f} | MA31:{ma31_curr:.2f} | MA128:{ma128_curr:.2f} | MA373:{ma373_curr:.2f}")

        # 2. 判断【当前瞬间】的信号类型
        current_signal = None  # 默认为无信号
        alert_title = ""

        # 判断是否满足开多条件
        if (prev_close > ma31_curr) and (ma31_curr > ma128_curr) and (ma128_curr > ma373_curr):
            current_signal = 'LONG'
            alert_title = "开多信号"

        # 判断是否满足开空条件
        elif (prev_close < ma31_curr) and (ma373_curr > ma128_curr) and (ma128_curr > ma31_curr):
            current_signal = 'SHORT'
            alert_title = "开空信号"

        # =========================================================
        # 【核心逻辑】状态改变检测 (Edge Detection)
        # 只有当 "现在的信号" 不等于 "上一次记录的信号" 时，才进行处理
        # =========================================================
        if self.is_first_run:
            # 如果是第一次运行，只记录状态，不报警
            self.last_signal_type = current_signal
            self.is_first_run = False #哪怕下次循环，也不是第一次了
            
            status_text = current_signal if current_signal else "无信号"
            print(f"✨ 系统初始化完成，当前状态锁定为: 【{status_text}】，静默待机中...")
            return 
            # 直接 return 结束本次函数，不执行下面的报警逻辑
        
        if current_signal != self.last_signal_type:
            
            # 情况A：触发了新信号 (从None变成多/空，或者从多变空)
            if current_signal is not None:
                print("\n" + "🚨" * 15)
                print(f"【{alert_title}】 (状态改变触发，仅提醒一次)")
                print(f"5min收盘:{prev_close:.2f} | 现价:{current_price:.2f}")
                print("🚨" * 15 + "\n")
                
                # 执行报警
                self.play_sound(alert_title)
                
                msg_content = f"5min收盘价：{prev_close:.2f}，现价：{current_price:.2f}"
                self.send_bark_push(alert_title, msg_content)
            
            # 情况B：信号消失了 (从多/空 变成了 None)
            else:
                print(f"信号条件已解除，恢复待机 (上个状态: {self.last_signal_type})")

            # === 无论如何，更新状态记录 ===
            self.last_signal_type = current_signal

        else:
            # 如果状态没变 (比如一直保持开多)，就什么都不做，保持安静
            pass