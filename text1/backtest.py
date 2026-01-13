import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os   
import time 
from datetime import datetime

# =========================================
# === 策略全局配置 ===
# =========================================
SYMBOL = 'BTC/USDT'     
TIMEFRAME = '5m'        
K_LIMIT = 100000        # 拉取数据量
INITIAL_BALANCE = 2500  # 初始本金
MAX_ORDERS = 1          # 最大同时持仓单数

ENABLE_LONG = True      # 是否允许做多
ENABLE_SHORT = True    # 是否允许做空

# 格式必须是: 'YYYY-MM-DD HH:MM:SS'
START_TIME = '2024-01-01 00:00:00'  # 回测起点
END_TIME   = '2026-01-01 00:00:00'  # 回测终点 (不填则跑到当前最新)

# === 核心参数 ===
LEVERAGE = 10           # 杠杆倍数
TP_PERCENT_LONG = 0.014      # 多单止盈比例
SL_PERCENT_LONG = 0.041       # 多单止损比例
TP_PERCENT_SHORT = 0.013     # 空单止盈比例
SL_PERCENT_SHORT = 0.04      # 空单止损比例
FEE_RATE = 0.0005       # 手续费 (万5)

# === 仓位管理 ===
FIXED_MARGIN_RATE = 0.4 #每次开单的金额比例

# 同向开单的距离阈值 1.5%
SAME_SIDE_DISTANCE = 0

# --- RSI 策略参数 ---
RSI_PERIOD = 14       # 常用周期 14
RSI_OVERBOUGHT = 75   # 超买阈值 (做多禁区)
RSI_OVERSOLD = 25     # 超卖阈值 (做空禁区)

def fetch_history_data():
    """
    【最终版】按指定【起止时间】精准拉取数据
    """
    print(f"📡 正在拉取 {SYMBOL} 数据...")
    print(f"⏰ 时间范围: {START_TIME}  --->  {END_TIME}")
    
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 30000, 
        'options': {'defaultType': 'future'}, 
        'userAgent': 'Mozilla/5.0',
        'proxies': {
            'http': 'http://127.0.0.1:7890',  # ⚠️ 确认端口
            'https': 'http://127.0.0.1:7890',
        }
    })
    
    # 1. 解析时间戳
    start_ts = exchange.parse8601(START_TIME)
    end_ts = exchange.parse8601(END_TIME)
    
    # 如果没填结束时间，默认到现在
    if end_ts is None:
        end_ts = exchange.milliseconds()

    single_limit = 1500 
    all_ohlcv = []
    since = start_ts
    
    while since < end_ts:
        try:
            # 每次拉取 1500 根
            current_batch = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=single_limit, since=since)
            
            if len(current_batch) == 0: break 
            
            # 更新下一次的起点
            last_timestamp = current_batch[-1][0]
            since = last_timestamp + 1 
            
            # 过滤掉超出 end_ts 的数据 (防止拉多了)
            # 这里的 x[0] 是 K 线的时间戳
            current_batch = [x for x in current_batch if x[0] < end_ts]
            
            if len(current_batch) == 0:
                break
                
            all_ohlcv += current_batch
            
            # 打印进度 (转成可读日期)
            last_date_str = datetime.fromtimestamp(last_timestamp / 1000).strftime('%Y-%m-%d')
            print(f"   ...已拉取至: {last_date_str} (共 {len(all_ohlcv)} 根)")
            
            # 如果拉到的数据比 limit 少，说明已经到头了
            if len(current_batch) < single_limit and since < end_ts:
                 # 这里有个特殊情况：如果过滤后变少了，不代表交易所没数据了
                 # 只有当原始 batch 也少于 limit 时才 break
                 # 但为了简单，如果 since 已经超过 end_ts，循环自然会停
                 pass

        except Exception as e:
            print(f"❌ 拉取中断: {e}")
            break

    if len(all_ohlcv) == 0: return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    print(f"✅ 数据准备完毕，共 {len(df)} 根K线")
    return df

def calculate_rsi(df, period=14):
    """辅助函数：计算RSI指标"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    # 使用 Wilder's Smoothing (标准的RSI算法)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def run_backtest(df):
    # 剔除最后一行
    df = df[:-1].reset_index(drop=True)
    
    # 打印当前模式
    mode_str = []
    if ENABLE_LONG: mode_str.append("做多")
    if ENABLE_SHORT: mode_str.append("做空")
    mode_msg = " + ".join(mode_str) if mode_str else "观察模式"
    print(f"🔄 开始回测 | 模式:【{mode_msg}】 | 杠杆:{LEVERAGE}x")
    
    # 1. 计算指标
    df['ma31'] = df['close'].rolling(31).mean()
    df['ma128'] = df['close'].rolling(128).mean()
    df['ma373'] = df['close'].rolling(373).mean()

    # 2. 账户初始化
    balance = INITIAL_BALANCE
    active_orders = []   
    closed_trades = []   
    equity_curve = []    
    
    # 👇【核心1】新增记忆变量：记录“上一单”的方向
    last_trade_type = None 
    
    start_index = 375
    
    for i in range(start_index, len(df)):
        
        # === 数据准备 ===
        last_close = float(df.loc[i-1, 'close'])
        last_ma31  = float(df.loc[i-1, 'ma31'])
        last_ma128 = float(df.loc[i-1, 'ma128'])
        last_ma373 = float(df.loc[i-1, 'ma373'])

        current_open  = float(df.loc[i, 'open'])   
        current_close = float(df.loc[i, 'close'])  
        current_time  = df.loc[i, 'timestamp']
        
        # =========================================
        # 第一步：检查【平仓】(代码保持不变)
        # =========================================
        orders_to_remove = []
        for order in active_orders:
            profit = 0
            is_closed = False
            close_reason = ""
            exec_price = current_close 
            
            if order['type'] == 'long':
                if current_close <= order['sl_price']:
                    is_closed = True; close_reason = "止损"; exec_price = current_close 
                elif current_close >= order['tp_price']:
                    is_closed = True; close_reason = "止盈"; exec_price = current_close 
                if is_closed:
                    pnl = (exec_price - order['entry_price']) * order['amount'] - (exec_price * order['amount'] * FEE_RATE) - order['entry_fee']
                    balance += order['margin'] + pnl; profit = pnl

            elif order['type'] == 'short':
                if current_close >= order['sl_price']:
                    is_closed = True; close_reason = "止损"; exec_price = current_close
                elif current_close <= order['tp_price']:
                    is_closed = True; close_reason = "止盈"; exec_price = current_close
                if is_closed:
                    pnl = (order['entry_price'] - exec_price) * order['amount'] - (exec_price * order['amount'] * FEE_RATE) - order['entry_fee']
                    balance += order['margin'] + pnl; profit = pnl

            if is_closed:
                icon = "🟢" if profit > 0 else "🔴"
                print(f"[{current_time}] {icon} 平仓({order['type']}) | {close_reason} | 盈亏: {profit:.2f} U")
                closed_trades.append({'profit': profit, 'time': current_time})
                orders_to_remove.append(order)

        for order in orders_to_remove: active_orders.remove(order)

        # =========================================
        # 第二步：检查【开仓】(加入同向过滤逻辑)
        # =========================================
        
        if len(active_orders) < MAX_ORDERS:
            signal = None
            
            # --- 1. 先判断基础信号 (Standard Logic) ---
            # 🟢 基础多单条件
            if ENABLE_LONG and (last_close > last_ma31 and last_ma31 > last_ma128 and last_ma128 > last_ma373):
                signal = 'long'
                
            # 🔴 基础空单条件
            elif ENABLE_SHORT and (last_close < last_ma373 and last_ma31 < last_ma128):
                signal = 'short'
            
            # --- 2. 👇【核心2】再应用“同向过滤”逻辑 ---
            if signal:
                # 只有当【本次信号】等于【上次方向】时，才进行严苛检查
                if last_trade_type is not None and signal == last_trade_type:
                    
                    # 如果是同向追多：开盘价必须拉开 1.5%
                    if signal == 'long':
                        threshold = last_ma31 * (1 + SAME_SIDE_DISTANCE)
                        if current_open <= threshold:
                            # print(f"🚫 过滤同向追多: 离均线不够远 (需 > {threshold:.2f})")
                            signal = None # 撤销信号

                    # 如果是同向追空：开盘价必须拉开 1.5%
                    elif signal == 'short':
                        threshold = last_ma31 * (1 - SAME_SIDE_DISTANCE)
                        if current_open >= threshold:
                            # print(f"🚫 过滤同向追空: 离均线不够远 (需 < {threshold:.2f})")
                            signal = None # 撤销信号

            # --- 3. 执行开仓 ---
            if signal:
                # 👇【核心3】记录本次方向，供下一次判断使用
                last_trade_type = signal 
                
                #target_margin = balance * FIXED_MARGIN_RATE     #复利

                target_margin = INITIAL_BALANCE * FIXED_MARGIN_RATE    #单利
                if target_margin < 5: continue 

                notional_value = target_margin * LEVERAGE
                amount = notional_value / current_open
                actual_initial_margin = (amount * current_open) / LEVERAGE
                entry_fee = notional_value * FEE_RATE
                
                total_cost = actual_initial_margin + entry_fee
                if balance < total_cost: continue 
                
                balance -= actual_initial_margin 

                # 设置止盈止损
                if signal == 'long':
                    tp_price = current_open * (1 + TP_PERCENT_LONG)
                    sl_price = current_open * (1 - SL_PERCENT_LONG) 
                else:
                    tp_price = current_open * (1 - TP_PERCENT_SHORT)
                    sl_price = current_open * (1 + SL_PERCENT_SHORT) 
                    
                new_order = {
                    'type': signal, 'entry_price': current_open, 'amount': amount,
                    'margin': actual_initial_margin, 'tp_price': tp_price,
                    'sl_price': sl_price, 'entry_fee': entry_fee, 'open_time': current_time
                }
                active_orders.append(new_order)
                print(f"[{current_time}] 🚀 开仓({signal}) | 价格:{current_open:.2f} | 保证金:{actual_initial_margin:.1f}U")

        # 记录资金曲线
        floating_pnl = 0
        total_margin = 0
        for order in active_orders:
            total_margin += order['margin']
            if order['type'] == 'long': floating_pnl += (current_close - order['entry_price']) * order['amount']
            else: floating_pnl += (order['entry_price'] - current_close) * order['amount']
        
        equity_curve.append(balance + total_margin + floating_pnl)

    return closed_trades, equity_curve

if __name__ == "__main__":
    df = fetch_history_data()
    trades, equity = run_backtest(df)
    
    if len(equity) > 0:
        final_balance = equity[-1]
        profit_rate = (final_balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100

        # 胜率统计
        total_trades = len(trades)
        win_trades = len([t for t in trades if t['profit'] > 0])
        loss_trades = total_trades - win_trades
        win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
        
        print("\n" + "="*30)
        print(f"模式设置: 多[{'✅' if ENABLE_LONG else '❌'}] / 空[{'✅' if ENABLE_SHORT else '❌'}]")
        print(f"初始本金: {INITIAL_BALANCE} U")
        print(f"最终余额: {final_balance:.2f} U")
        print(f"收益率: {profit_rate:.2f}%")
        print(f"总交易数: {len(trades)}")
        print(f"胜率: {win_rate:.2f}% (✅{win_trades} / ❌{loss_trades})")
        print("="*30)
        
        plt.figure(figsize=(20, 10))
        plt.plot(equity, label='Equity (USDT)')
        plt.title(f'Backtest (Lev {LEVERAGE}x, Win: {win_rate:.1f}%)') 
        plt.legend()
        plt.grid()
        
        save_dir = r"F:\BIANRobot\text1\Backtest_Results" 
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        current_time_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"backtest_result_{current_time_str}.png"
        full_path = os.path.join(save_dir, filename)
        
        plt.savefig(full_path)
        print(f"✅ 结果已保存为: {full_path}")