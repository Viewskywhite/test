import time
from config import Config
from drive import BinanceDriver
from Strategy import Strategy
from data_manager import DataManager
from alert_system import AlertSystem

def main():
    print("=== 超级量化终端启动 ===")
    
    # 1. 初始化三大模块
    driver = BinanceDriver(Config)           # 驱动 (手)
    data_loader = DataManager(driver.exchange) # 数据 (眼)
    brain = Strategy(Config)                 # 策略 (脑)
    alert_system = AlertSystem()             # 哨兵 (耳)

    # 打印初始余额
    balance = driver.get_usdt_balance()
    print(f" 账户初始余额: {balance:.2f} USDT")

    while True:
        try:
            print("\n" + "=" * 50)
            print(f" 系统时间: {time.strftime('%H:%M:%S')}")
            
            # === A. 获取所有关注的周期数据 ===
            # 返回一个字典: {'5m': df, '15m': df, ...}
            kline_dict = data_loader.get_all_timeframes(
                Config.SYMBOL, 
                Config.TIMEFRAMES
            )
            # ==========================================
            # === [新增] D. 独立报警模块 (插入在这里) ===
            # ==========================================
            # 只要数据里包含 5m，就让哨兵去检查一遍
            # 注意：请确保 config.py 的 TIMEFRAMES 里包含 '5m'
            if '5m' in kline_dict:
                # 这里调用我们在 alert_system.py 里写好的检查函数
                alert_system.check_signal(kline_dict['5m'])
            # ==========================================

            # === B. 满足你的需求：打印所有数据 ===
            if kline_dict:
                print(f"\n---  行情监控 ({Config.SYMBOL}) ---")
                for tf in Config.TIMEFRAMES:
                    if tf in kline_dict:
                        df = kline_dict[tf]
                        current_price = df.iloc[-1]['close']
                        # 打印: [5m] 现价: 93000.5 | 涨跌幅等信息...
                        print(f" > [{tf: <3}] 最新价: {current_price:.2f} \t(数据量: {len(df)})")
            
            # === C. 保持原有功能：执行交易逻辑 ===
            # 我们只把“主周期”的数据喂给策略
            target_tf = Config.TRADE_TIMEFRAME
            
            if target_tf in kline_dict:
                target_df = kline_dict[target_tf]
                
                print(f"\n---  策略分析 (基于 {target_tf}) ---")
                
                # 让大脑分析
                signal = brain.analyze(target_df)
                
                # 执行信号
                if signal:
                    print(f" 触发交易信号: 【{signal}】")
                    driver.execute_order(signal)
                else:
                    print("💤 暂无交易信号，继续观察...")
            else:
                print(f" 警告：未获取到主交易周期 {target_tf} 的数据")

            print("=" * 50)
            
            # 休息
            time.sleep(10)

        except KeyboardInterrupt:
            print("\n用户手动停止程序")
            break
        except Exception as e:
            print(f"主程序报错: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()