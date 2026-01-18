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
START_TIME = '2026-01-01 00:00:00'  
END_TIME   = '2026-01-10 00:00:00'   

# === 核心参数 ===
LEVERAGE =10           # 杠杆倍数
TP_PERCENT_LONG = 0.02      # 多单止盈比例
SL_PERCENT_LONG = 0.009      # 多单止损比例
TP_PERCENT_SHORT = 0.02     # 空单止盈比例
SL_PERCENT_SHORT = 0.009     # 空单止损比例
FEE_RATE = 0.0002       # 手续费 (万5)

# === 仓位管理===
#True是打开复利，False是关闭复利
MIX_UP = True      
FIXED_MARGIN_RATE = 0.7 # 每次复利开单的金额比例

MAX_OPEN = True  # 是否启用最大开仓金额限制
MAX_OPEN_LIMIT=100000  # 最大开仓金额.      想要长时间的稳定收益就调小，10万后每加10万峰值收益率提升高1000%左右。 9w

# ===偏离值===
#True是打开偏离值，False为关闭偏离值
SIDE_DISTANCE_SWITCH = True
SAME_SIDE_DISTANCE_LONG = 0.015   #多单偏离值
SAME_SIDE_DISTANCE_SHORT = 0.015   #空单偏离值

#===连续开单风险控制===
ENABLE_CONSECUTIVE_FILTER = False  # 总开关：True开启，False关闭
MAX_CONS_LONG  = 5   # 连续做多最大次数 (比如允许连续追4次多)
MAX_CONS_SHORT = 5   # 连续做空最大次数 (比如只允许连续追2次空)



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
    """
    修正后的回测引擎：
    1. 解决了无限刷单Bug (T+1机制)
    2. 解决了手续费漏扣问题 (双向万2)
    3. 解决了挂单永不过期的问题
    """
    
    # 判空
    if df.empty:
        print("❌ 数据为空，无法回测")
        return [], [], 0
    
    if df.empty:
        print("❌ 数据为空，无法回测")
        return [], [], 0

    # =========================================
    # 🚨【补全步骤】必须先计算指标，否则后面会报错 KeyError
    # =========================================
    # 确保按照 Close 列计算均线
    df['ma31'] = df['close'].rolling(31).mean()
    df['ma128'] = df['close'].rolling(128).mean()
    df['ma373'] = df['close'].rolling(373).mean()

    print("✅ 指标计算完成 (MA31, MA128, MA373)")

    # === 1. 账户初始化 ===
    balance = INITIAL_BALANCE
    reserve_fund = INITIAL_RESERVE
    
    active_orders = []   # 持仓单
    closed_trades = []   # 已平仓记录
    equity_curve = []    # 资金曲线
    
    # 挂单变量 (Pending Order)
    pending_order = None 
    
    # 状态记忆
    last_trade_type = None
    consecutive_counts = 0
    
    # 预留计算MA的长度
    start_index = 375 
    
    print(f"🔄 开始回测 | 费率: {FEE_RATE*10000:.0f}‱ (万{FEE_RATE*10000:.0f}) | 杠杆: {LEVERAGE}x")
    print(f"⏳ 正在逐根K线模拟 ({len(df) - start_index} 根)...")

    # === 2. 主循环 ===
    for i in range(start_index, len(df)):
        
        # --- 获取数据 ---
        # 当前K线 (用于撮合交易)
        row = df.iloc[i]
        current_time  = row['timestamp']
        current_open  = float(row['open'])
        current_high  = float(row['high'])
        current_low   = float(row['low'])
        current_close = float(row['close'])
        
        # 上一根K线 (用于生成信号 - 杜绝未来函数)
        prev_row = df.iloc[i-1]
        last_close = float(prev_row['close'])
        last_ma31  = float(prev_row['ma31'])
        last_ma128 = float(prev_row['ma128'])
        last_ma373 = float(prev_row['ma373'])

        # 临时变量：记录本根K线刚刚成交的单子
        # (刚成交的单子不参与当根K线的平仓检查，防止日内高频刷单)
        newly_filled_order = None 

        # ============================================================
        # 🟢【阶段一：挂单撮合 (Entry Logic)】
        # ============================================================
        if pending_order is not None:
            is_filled = False
            fill_price = 0
            
            # --- 检查是否成交 ---
            # 1. 买单 (Long)
            if pending_order['type'] == 'long':
                # 如果开盘价更低，直接以开盘价成交 (滑点优势)
                if current_open <= pending_order['price']:
                    is_filled = True
                    fill_price = current_open
                # 否则看最低价是否跌破
                elif current_low <= pending_order['price']:
                    is_filled = True
                    fill_price = pending_order['price']
            
            # 2. 卖单 (Short)
            elif pending_order['type'] == 'short':
                # 如果开盘价更高，直接以开盘价成交
                if current_open >= pending_order['price']:
                    is_filled = True
                    fill_price = current_open
                # 否则看最高价是否冲过
                elif current_high >= pending_order['price']:
                    is_filled = True
                    fill_price = pending_order['price']

            # --- 成交处理 ---
            if is_filled:
                real_order = pending_order.copy()
                real_order['entry_price'] = fill_price
                real_order['open_time'] = current_time
                
                # 💰【扣除开仓手续费】(按名义价值计算)
                # 名义价值 = 成交价 * 数量
                trade_value = real_order['amount'] * fill_price
                entry_fee = trade_value * FEE_RATE
                
                balance -= entry_fee  # 直接从余额扣除
                real_order['entry_fee'] = entry_fee # 记录一下
                
                newly_filled_order = real_order # 暂存，稍后加入持仓
                
            else:
                # ⚠️【关键】如果没成交，挂单失效，必须退还冻结的保证金！
                # 否则你的钱会被一直冻结，最后没钱开单
                balance += pending_order['margin']
            
            # 无论是否成交，挂单在当前K线结束时都清空 (Expire)
            pending_order = None

        # ============================================================
        # 🔵【阶段二：持仓管理 (Exit Logic)】
        # ============================================================
        orders_to_keep = []
        
        for order in active_orders:
            is_closed = False
            exit_price = 0
            close_reason = ""
            
            # --- 多单止盈止损 ---
            if order['type'] == 'long':
                # 1. 止损 (SL)
                if current_low <= order['sl_price']:
                    is_closed = True
                    close_reason = "止损"
                    # 防穿仓：如果开盘直接跳空到止损下方，按开盘价损
                    exit_price = current_open if current_open < order['sl_price'] else order['sl_price']
                
                # 2. 止盈 (TP)
                elif current_high >= order['tp_price']:
                    is_closed = True
                    close_reason = "止盈"
                    exit_price = current_open if current_open > order['tp_price'] else order['tp_price']

            # --- 空单止盈止损 ---
            elif order['type'] == 'short':
                # 1. 止损 (SL)
                if current_high >= order['sl_price']:
                    is_closed = True
                    close_reason = "止损"
                    exit_price = current_open if current_open > order['sl_price'] else order['sl_price']
                
                # 2. 止盈 (TP)
                elif current_low <= order['tp_price']:
                    is_closed = True
                    close_reason = "止盈"
                    exit_price = current_open if current_open < order['tp_price'] else order['tp_price']

            # --- 结算 ---
            if is_closed:
                # 1. 计算盘面盈亏
                if order['type'] == 'long':
                    pnl = (exit_price - order['entry_price']) * order['amount']
                else:
                    pnl = (order['entry_price'] - exit_price) * order['amount']
                
                # 💰【扣除平仓手续费】(按名义价值计算)
                exit_value = exit_price * order['amount']
                exit_fee = exit_value * FEE_RATE
                
                # 净利润 = 盘面盈亏 - 平仓费
                # (注意：开仓费之前已经从balance扣了，保证金之前也扣了)
                net_pnl = pnl - exit_fee
                
                # 资金回笼 = 保证金 + 净利润
                balance += order['margin'] + net_pnl
                
                # 备用金检查
                if balance < 0:
                    if reserve_fund > abs(balance):
                        reserve_fund += balance # 填坑
                        balance = 0
                    else:
                        balance = 0 # 破产
                
                # 记录
                closed_trades.append({
                    'time': current_time,
                    'type': order['type'],
                    'profit': net_pnl, # 这是扣除平仓费后的净利
                    'entry_fee': order['entry_fee'], # 记录一下当时的开仓费
                    'exit_fee': exit_fee,
                    'reason': close_reason
                })
            else:
                orders_to_keep.append(order)
        
        # 更新持仓列表
        active_orders = orders_to_keep
        
        # 将本轮刚成交的单子加入，准备下一轮监控 (T+1)
        if newly_filled_order:
            active_orders.append(newly_filled_order)

        # ============================================================
        # 🟡【阶段三：信号生成 (Signal Logic)】
        # ============================================================
        # 只有在 (无挂单) 且 (未满仓) 时才开单
        if pending_order is None and len(active_orders) < MAX_ORDERS:
            signal = None
            
            # 1. 均线排列判断
            if ENABLE_LONG and (last_close > last_ma31 > last_ma128):
                signal = 'long'
            elif ENABLE_SHORT and (last_close < last_ma31 and last_ma31 < last_ma128):
                signal = 'short'
            
            # 2. 偏离值过滤
            if SIDE_DISTANCE_SWITCH and signal:
                if last_trade_type == signal: # 只有同向才检查
                    if signal == 'long':
                        thresh = last_ma31 * (1 + SAME_SIDE_DISTANCE_LONG)
                        if last_close <= thresh: signal = None
                    elif signal == 'short':
                        thresh = last_ma31 * (1 - SAME_SIDE_DISTANCE_SHORT)
                        if last_close >= thresh: signal = None

            # 3. 连续开单过滤
            if ENABLE_CONSECUTIVE_FILTER and signal:
                if last_trade_type == signal:
                    if signal == 'long' and consecutive_counts >= MAX_CONS_LONG: signal = None
                    elif signal == 'short' and consecutive_counts >= MAX_CONS_SHORT: signal = None

            # --- 生成挂单 ---
            if signal:
                # 更新计数器
                if last_trade_type == signal:
                    consecutive_counts += 1
                else:
                    consecutive_counts = 1
                    last_trade_type = signal

                # 计算本金
                margin_to_use = balance * FIXED_MARGIN_RATE if MIX_UP else INITIAL_BALANCE
                if MAX_OPEN and MAX_OPEN_LIMIT > 0:
                    margin_to_use = min(margin_to_use, MAX_OPEN_LIMIT)
                
                # 只有钱够才开
                if margin_to_use > 5 and balance > margin_to_use:
                    limit_price = last_close
                    
                    # 预估数量 (Amount = 保证金 * 杠杆 / 价格)
                    amount = (margin_to_use * LEVERAGE) / limit_price
                    
                    # 计算TP/SL
                    if signal == 'long':
                        tp = limit_price * (1 + TP_PERCENT_LONG)
                        sl = limit_price * (1 - SL_PERCENT_LONG)
                    else:
                        tp = limit_price * (1 - TP_PERCENT_SHORT)
                        sl = limit_price * (1 + SL_PERCENT_SHORT)
                    
                    # 💰【冻结保证金】
                    balance -= margin_to_use
                    
                    pending_order = {
                        'type': signal,
                        'price': limit_price,
                        'amount': amount,
                        'margin': margin_to_use,
                        'tp_price': tp,
                        'sl_price': sl
                    }

        # ============================================================
        # 🟣【阶段四：统计资金 (Equity Calculation)】
        # ============================================================
        equity = balance 
        
        # 加回冻结在挂单里的钱
        if pending_order:
            equity += pending_order['margin']
            
        # 加回持仓单的保证金 + 浮动盈亏
        for order in active_orders:
            equity += order['margin']
            if order['type'] == 'long':
                equity += (current_close - order['entry_price']) * order['amount']
            else:
                equity += (order['entry_price'] - current_close) * order['amount']
        
        equity_curve.append(equity)

    print(f"✅ 回测完成! 总交易数: {len(closed_trades)} | 最终权益: {equity_curve[-1]:.2f}")
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
    # === 🛑 统一时间处理逻辑 ===
    # =========================================================
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import webbrowser
    import os
    import time
    import numpy as np # 确保导入numpy

    print("\n" + "="*40)
    print("🔍 数据预处理...")

    # --- 步骤A: 锁定时间列数据 ---
    raw_time_series = None
    if 'open_time' in df.columns:
        raw_time_series = df['open_time']
    elif 'timestamp' in df.columns:
        raw_time_series = df['timestamp']
    else:
        raw_time_series = df.iloc[:, 0]
    
    # --- 步骤B: 智能转换格式 ---
    try:
        first_val = raw_time_series.iloc[0]
        if isinstance(first_val, str):
            final_time_index = pd.to_datetime(raw_time_series)
        elif isinstance(first_val, (int, float, np.integer, np.floating)):
            if first_val > 10000000000: 
                final_time_index = pd.to_datetime(raw_time_series, unit='ms')
            else:
                final_time_index = pd.to_datetime(raw_time_series, unit='s')
        else:
            final_time_index = pd.to_datetime(raw_time_series)
    except Exception as e:
        print(f"❌ 时间转换错误: {e}")
        exit()

    print(f"📅 时间范围: {final_time_index.min()} ~ {final_time_index.max()}")

    # 2. 运行回测
    trades, equity, final_reserve = run_backtest(df)
    
    if len(equity) > 0:
        
        # --- 3. 核心统计计算 (新增峰值计算) ---
        final_trading_balance = equity[-1]
        total_initial_assets = INITIAL_BALANCE + INITIAL_RESERVE
        total_final_assets = final_trading_balance + final_reserve
        
        # 总体盈亏
        total_profit = total_final_assets - total_initial_assets
        profit_rate = (total_profit / total_initial_assets) * 100
        
        # === 🆕 新增：计算历史最高资产与峰值收益率 ===
        max_equity_value = max(equity) # 历史最高账户余额
        # 注意：这里假设备用金不动，只计算交易账户的峰值带动整体资产的峰值
        # 峰值总资产近似为 = 最高账户余额 + 剩余备用金 (略有误差但够用)
        peak_total_assets = max_equity_value + final_reserve 
        peak_profit_rate = ((peak_total_assets - total_initial_assets) / total_initial_assets) * 100

        # === 文字版控制台打印 ===
        # 胜率统计
        total_trades = len(trades)
        win_trades = len([t for t in trades if t['profit'] > 0])
        loss_trades = total_trades - win_trades
        win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0

        print("\n" + "="*40)
        print(f"📊 回测结果 ({START_TIME} 至 {END_TIME})")
        print(f"模式: 多[{'✅' if ENABLE_LONG else '❌'}] / 空[{'✅' if ENABLE_SHORT else '❌'}]")
        print("-" * 40)
        print(f"💰 资金详情:")
        print(f"   初始总投入: {total_initial_assets:.2f} U (本金:{INITIAL_BALANCE} + 备用:{INITIAL_RESERVE})")
        print(f"   最终总资产: {total_final_assets:.2f} U (账户:{final_trading_balance:.2f} + 备用:{final_reserve:.2f})")
        print(f"   净盈亏:     {'+' if total_profit>0 else ''}{total_profit:.2f} U")
        print(f"   总收益率:   {profit_rate:.2f}%")
        print(f"   🚀 峰值收益: {peak_profit_rate:.2f}%")
        print("-" * 40)
        print(f"📈 交易详情:")
        print(f"   总交易数:   {total_trades}")
        print(f"   胜率:       {win_rate:.2f}% (✅{win_trades} / ❌{loss_trades})")
        print("="*40)

        # --- 4. 绘图数据对齐 ---
        len_df = len(final_time_index)
        len_equity = len(equity)
        
        if len_equity < len_df:
            aligned_time_index = final_time_index[-len_equity:]
            aligned_equity = equity
        elif len_equity > len_df:
            aligned_time_index = final_time_index
            aligned_equity = equity[-len_df:]
        else:
            aligned_time_index = final_time_index
            aligned_equity = equity

        equity_series = pd.Series(aligned_equity, index=aligned_time_index)
        daily_pnl = equity_series.resample('D').last().diff().fillna(0) 

        # --- 5. Plotly 绘图 ---
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

        # === 🆕 标题设置 (BTC/USDT + 杠杆 + 峰值收益) ===
        title_text = (
            f"<b>BTC/USDT 量化回测报告</b><br>"
            f"<sup>"
            f"杠杆: {LEVERAGE}x | "
            f"总收益: {profit_rate:.2f}% | "
            f"峰值收益: {peak_profit_rate:.2f}% | "
            f"周期: {START_TIME} ~ {END_TIME}"
            f"</sup>"
        )

        fig.update_layout(
            title=title_text,
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
        filename_html = f"backtest_BTC_USDT_{LEVERAGE}x_{current_time_str}.html"
        full_path_html = os.path.join(save_dir, filename_html)
        
        fig.write_html(full_path_html)
        print(f"✅ 交互式回测报告已保存: {full_path_html}")
        webbrowser.open(full_path_html)
        
    else:
        print("❌ 未产生回测数据，请检查CSV路径或策略逻辑。")