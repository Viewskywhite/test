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
INITIAL_BALANCE = 1000  # 初始本金
INITIAL_RESERVE = 0  # 备用金 (当本金不够时自动充值)
MAX_ORDERS = 1          # 最大同时持仓单数

ENABLE_LONG = True      # 是否允许做多
ENABLE_SHORT = True     # 是否允许做空

# 【注意】这里是回测的时间范围
# 你的CSV文件必须包含这段时间的数据，否则会报错空数据
START_TIME = '2025-01-01 00:00:00'  
END_TIME   = '2026-01-01 00:00:00'  

# === 核心参数 ===
LEVERAGE = 10           # 杠杆倍数
TP_PERCENT_LONG = 0.014      # 多单止盈比例
SL_PERCENT_LONG = 0.041       # 多单止损比例
TP_PERCENT_SHORT = 0.013     # 空单止盈比例
SL_PERCENT_SHORT = 0.04     # 空单止损比例
FEE_RATE = 0.0004       # 手续费 (万5)

# === 仓位管理 （复利）===
FIXED_MARGIN_RATE = 0.7 # 每次开单的金额比例

# 同向开单的距离阈值 1.5%
SAME_SIDE_DISTANCE = 0.015

# --- RSI 策略参数 ---
RSI_PERIOD = 14       
RSI_OVERBOUGHT = 75   
RSI_OVERSOLD = 25     

def load_from_csv(file_path):
    """
    【新版】从本地CSV读取数据
    """
    print(f"📂 正在读取本地文件: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ 错误: 找不到文件 {file_path}")
        return pd.DataFrame()

    # 读取 CSV
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ 文件读取失败: {e}")
        return pd.DataFrame()

    # 1. 统一列名转小写 (Open -> open) 以匹配策略
    df.columns = [x.lower() for x in df.columns]

    # 2. 处理时间列
    # 优先找 datetime, 没有则找 timestamp
    time_col = 'datetime' if 'datetime' in df.columns else 'timestamp'
    
    # 确保转换为 datetime 对象
    if time_col in df.columns:
        df['timestamp'] = pd.to_datetime(df[time_col])
    else:
        # 如果既没有datetime也没有timestamp，尝试使用索引
        print("⚠️ 未找到时间列，尝试重置索引...")
        df.reset_index(inplace=True)
        df['timestamp'] = pd.to_datetime(df.iloc[:, 0]) # 假设第一列是时间

    # 3. 按配置的时间范围过滤数据
    print(f"⏰ 筛选时间: {START_TIME} ---> {END_TIME}")
    mask = (df['timestamp'] >= pd.to_datetime(START_TIME)) & \
           (df['timestamp'] <= pd.to_datetime(END_TIME))
    
    df = df.loc[mask].copy()
    
    # 4. 排序并重置索引
    df.sort_values('timestamp', inplace=True)
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        print("❌ 警告: 该时间段内没有数据！请检查CSV文件覆盖的日期。")
        return pd.DataFrame()

    print(f"✅ 数据加载成功，共 {len(df)} 根K线")
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

    # 2. 账户初始化
    if df.empty:
        print("数据为空，无法回测")
        return [], [], 0 # 👈 返回值增加一个

    # ... (前面的代码保持不变) ...
    
    # 2. 账户初始化
    balance = INITIAL_BALANCE
    reserve_fund = INITIAL_RESERVE  # 🆕 必须在这里初始化备用金
    
    active_orders = []   
    closed_trades = []   
    equity_curve = []    
    last_trade_type = None

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
    
    # 进度条提示
    print(f"⏳ 正在逐根K线模拟交易 ({len(df)} 根)...")

    for i in range(start_index, len(df)):
        
        # === 数据准备 ===
        last_close = float(df.loc[i-1, 'close'])
        last_ma31  = float(df.loc[i-1, 'ma31'])
        last_ma128 = float(df.loc[i-1, 'ma128'])
        last_ma373 = float(df.loc[i-1, 'ma373'])

        current_open  = float(df.loc[i, 'open'])   
        current_close = float(df.loc[i, 'close'])  
        current_time  = df.loc[i, 'timestamp']

        current_ma128 = float(df.loc[i, 'ma128'])
        
        # =========================================
        # 第一步：检查【平仓】
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
                # print(f"[{current_time}] {icon} 平仓({order['type']}) | {close_reason} | 盈亏: {profit:.2f} U | 原因: {close_reason}")
                closed_trades.append({'profit': profit, 'time': current_time})
                orders_to_remove.append(order)
                #print(f"[{current_time}] 平仓: {close_reason} | 盈亏: {profit:.2f})

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
                        threshold = last_ma373 * (1 + SAME_SIDE_DISTANCE)
                        if current_open <= threshold:
                            # print(f"🚫 过滤同向追多: 离均线不够远 (需 > {threshold:.2f})")
                            signal = None # 撤销信号

                    # 如果是同向追空：开盘价必须拉开 1.5%
                    elif signal == 'short':
                        threshold = last_ma373 * (1 - SAME_SIDE_DISTANCE)
                        if current_open >= threshold:
                            # print(f"🚫 过滤同向追空: 离均线不够远 (需 < {threshold:.2f})")
                            signal = None # 撤销信号

            # --- 3. 执行开仓 ---
            if signal:
                last_trade_type = signal #记录方向
                
                # ------------------------------------------------------
                # 1. 计算目标仓位大小
                # ------------------------------------------------------
                target_margin = balance * FIXED_MARGIN_RATE          # 复利模式
                #target_margin = INITIAL_BALANCE    # 单利模式 (推荐配合备用金)
                
                if target_margin < 5: continue 

                # 计算实际需要的资金 (保证金 + 手续费)
                notional_value = target_margin * LEVERAGE
                amount = notional_value / current_open
                actual_initial_margin = (amount * current_open) / LEVERAGE
                entry_fee = notional_value * FEE_RATE
                
                total_cost = actual_initial_margin + entry_fee # 开这一单总共需要的钱
                
                # ------------------------------------------------------
                # 2. 🆕 新增：备用金划转逻辑
                # ------------------------------------------------------
                if balance < total_cost:
                    missing_amount = total_cost - balance # 缺多少钱
                    
                    # 检查备用金够不够填坑
                    if reserve_fund >= missing_amount:
                        # 💰 备用金充足，进行划转
                        reserve_fund -= missing_amount
                        balance += missing_amount
                        print(f"[{current_time}] 🆘 余额不足，启用备用金! 补充: {missing_amount:.2f}U | 剩余备用金: {reserve_fund:.2f}U")
                    else:
                        # 备用金也不够了，那就真的开不出来了
                        # print(f"[{current_time}] ❌ 资金彻底耗尽 (含备用金)，无法开仓")
                        continue
                
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
                # print(f"[{current_time}] 🚀 开仓({signal}) | 价格:{current_open:.2f} | 保证金:{actual_initial_margin:.1f}U")

        # 记录资金曲线
        floating_pnl = 0
        total_margin = 0
        for order in active_orders:
            total_margin += order['margin']
            if order['type'] == 'long': floating_pnl += (current_close - order['entry_price']) * order['amount']
            else: floating_pnl += (order['entry_price'] - current_close) * order['amount']
        
        equity_curve.append(balance + total_margin + floating_pnl)

    return closed_trades, equity_curve, reserve_fund

# =========================================
# === 主执行入口 ===
# =========================================
if __name__ == "__main__":
    
    # 【重要】在这里填写你下载的CSV文件路径
    CSV_PATH = r"F:\BIANRobot\text1\FUTURES_BTCUSDT_5m_2020.csv"
    
    # 1. 读取本地数据
    df = load_from_csv(CSV_PATH)
    
    # =========================================================
    # === 🛑 统一时间处理逻辑 (彻底修复1970问题) ===
    # =========================================================
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import webbrowser
    import os
    import time

    print("\n" + "="*40)
    print("🔍 数据预处理...")

    # --- 步骤A: 锁定时间列数据 ---
    # 逻辑：优先找 'open_time'，找不到就找 'timestamp'，还找不到就强制取【第1列】
    # 绝不使用 df.index (那是导致1970的罪魁祸首)
    
    raw_time_series = None
    col_name_used = "Unknown"

    if 'open_time' in df.columns:
        raw_time_series = df['open_time']
        col_name_used = "open_time"
    elif 'timestamp' in df.columns:
        raw_time_series = df['timestamp']
        col_name_used = "timestamp"
    else:
        # 强制使用第一列
        raw_time_series = df.iloc[:, 0]
        col_name_used = f"第1列 ({df.columns[0]})"
    
    print(f"👉 使用列 [{col_name_used}] 作为时间基准")

    # --- 步骤B: 智能转换格式 ---
    first_val = raw_time_series.iloc[0]
    final_time_index = None

    try:
        # 情况1: 字符串
        if isinstance(first_val, str):
            final_time_index = pd.to_datetime(raw_time_series)
            print("✅ 格式识别: 字符串日期 (2020-01-01...)")
            
        # 情况2: 数字 (时间戳)
        elif isinstance(first_val, (int, float, np.integer, np.floating)):
            # 如果数值很大(>100亿)，说明是毫秒
            if first_val > 10000000000: 
                final_time_index = pd.to_datetime(raw_time_series, unit='ms')
                print("✅ 格式识别: 毫秒级时间戳 (Unix ms)")
            else:
                final_time_index = pd.to_datetime(raw_time_series, unit='s')
                print("✅ 格式识别: 秒级时间戳 (Unix s)")
        else:
            # 兜底
            final_time_index = pd.to_datetime(raw_time_series)
            print("⚠️ 格式识别: 自动推断")

    except Exception as e:
        print(f"❌ 时间转换严重错误: {e}")
        print("停止运行，请检查CSV数据格式。")
        exit()

    print(f"📅 时间范围: {final_time_index.min()} ~ {final_time_index.max()}")
    print("-" * 40)

    # 2. 运行回测
    trades, equity, final_reserve = run_backtest(df)
    
    if len(equity) > 0:
        # === 🆕 资金统计与绘图 ===
        
        # --- 数据对齐 ---
        # 使用刚才算好的 final_time_index，不再重新计算
        len_df = len(final_time_index)
        len_equity = len(equity)
        
        if len_equity < len_df:
            # 截取最后一段
            aligned_time_index = final_time_index[-len_equity:]
            aligned_equity = equity
        elif len_equity > len_df:
            aligned_time_index = final_time_index
            aligned_equity = equity[-len_df:]
        else:
            aligned_time_index = final_time_index
            aligned_equity = equity

        # 生成 Pandas Series
        equity_series = pd.Series(aligned_equity, index=aligned_time_index)
        
        # 计算盈亏
        final_trading_balance = equity[-1]
        total_initial_assets = INITIAL_BALANCE + INITIAL_RESERVE
        total_final_assets = final_trading_balance + final_reserve
        total_profit = total_final_assets - total_initial_assets
        profit_rate = (total_profit / total_initial_assets) * 100
        
        daily_equity = equity_series.resample('D').last()
        daily_pnl = daily_equity.diff().fillna(0) 

        # --- Plotly 绘图 ---
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.05,
            row_heights=[0.7, 0.3],
            subplot_titles=("账户资金权益曲线 (Account Equity)", "每日盈亏 (Daily PnL)")
        )

        # 曲线
        fig.add_trace(
            go.Scatter(
                x=equity_series.index, 
                y=equity_series.values,
                mode='lines',
                name='总资产 (USDT)',
                line=dict(color='#00da3c', width=2),
                hovertemplate='时间: %{x}<br>资产: %{y:.2f} U<extra></extra>'
            ),
            row=1, col=1
        )

        # 柱状图
        if not daily_pnl.empty:
            colors = ['#26a69a' if v >= 0 else '#ef5350' for v in daily_pnl.values]
            fig.add_trace(
                go.Bar(
                    x=daily_pnl.index, 
                    y=daily_pnl.values,
                    name='每日盈亏',
                    marker_color=colors,
                    hovertemplate='日期: %{x|%Y-%m-%d}<br>盈亏: %{y:.2f} U<extra></extra>'
                ),
                row=2, col=1
            )

        # 布局
        fig.update_layout(
            title=f'<b>量化回测报告</b><br><sup>周期: {START_TIME} ~ {END_TIME} | 总收益: {profit_rate:.2f}% | 交易数: {len(trades)}</sup>',
            template='plotly_dark',
            hovermode='x unified',
            dragmode='zoom',
            height=800,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # 保存
        save_dir = r"F:\BIANRobot\text1\Backtest_Results"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        current_time_str = time.strftime("%Y%m%d_%H%M%S")
        filename_html = f"backtest_report_{current_time_str}.html"
        full_path_html = os.path.join(save_dir, filename_html)
        
        fig.write_html(full_path_html)
        print(f"✅ 交互式回测报告已保存: {full_path_html}")
        webbrowser.open(full_path_html)
        
    else:
        print("❌ 未产生回测数据，请检查CSV路径或策略逻辑。")