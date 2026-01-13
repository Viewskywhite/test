import ccxt
import pandas as pd
import time

class BinanceDriver:
    def __init__(self, config):
        self.cfg = config
        self.exchange = ccxt.binance({
            'apiKey': config.API_KEY,
            'secret': config.SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'} # 默认做合约
        })
        
        if config.SANDBOX_MODE:
            self.exchange.set_sandbox_mode(True)
            print("⚠️ 警告：当前处于测试网 (Testnet) 模式")

        max_retries = 5 # 最多重试 5 次
        for i in range(max_retries):
            try:
                print(f"🔌 [第 {i+1} 次尝试] 正在连接交易所...")
                self.exchange.load_markets() # 加载精度规则
                print("✅ 交易所连接成功！")
                break # 成功了就跳出循环，继续运行
            except Exception as e:
                print(f"⚠️ 连接失败: {e}")
                if i < max_retries - 1:
                    print("⏳ 3秒后自动重试...")
                    time.sleep(3) # 休息3秒
                else:
                    print("❌ 多次连接失败，程序即将退出。请检查网络/代理或配置。")
                    raise e # 如果试了5次还不行，就只能让它报错停止了
                
        # =========================================================

    def get_usdt_balance(self):
        """查询账户里的 USDT 余额"""
        try:
            balance = self.exchange.fetch_balance()
            return balance['free']['USDT']
        except Exception as e:
            print(f"❌ 获取余额失败: {e}")
            return 0

    def execute_order(self, side):
        """
        执行下单
        side: 'buy' 或 'sell'
        """
        if not getattr(self.cfg, 'ENABLE_TRADING', False):
            print(f"🛡️ [安全模式] 触发 {side} 信号，但 ENABLE_TRADING = False，已拦截。")
            return None
        
        symbol = self.cfg.SYMBOL
        amount_usdt = self.cfg.QUANTITY_USDT

        try:
            # 1. 获取当前价格
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']

            # 2. 计算购买数量 (USDT / 价格)
            raw_amount = amount_usdt / price

            # 3. 精度修正 (关键步骤：防止小数位报错)
            amount = self.exchange.amount_to_precision(symbol, raw_amount)

            # 4. 设置杠杆
            try:
                self.exchange.set_leverage(self.cfg.LEVERAGE, symbol)
            except:
                pass 

            print(f"🚀 正在下单: {side} {amount} 个 {symbol} (约 {amount_usdt} U)")

            # 5. 发送市价单
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount
            )
            print(f"✅ 下单成功！订单ID: {order['id']}")
            return order

        except Exception as e:
            print(f"❌ 下单失败: {e}")
            return None