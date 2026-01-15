class Config:
    # ================= 账户设置 =================
    API_KEY = 'ma13EUO520TQoNy8cOk6n1iv36f44q7QQf8Z4FqSVTXb7vpPIEegMZ60DnwZv3Zk'
    SECRET = 'RuTTzvZuo3N1T6svGferbWh1i5yMFI7ymC5lVUHfdhkSyucVwrGgvXP1Afq8gCgI'
    
    # True = 测试网 (资金是假的)，False = 实盘 (资金是真的)
    # 强烈建议先用 True 跑通流程！
    SANDBOX_MODE = False

    # ================= 交易目标 =================
    SYMBOL = 'BTC/USDT'  # 交易对
    LEVERAGE = 5         # 杠杆倍数
    QUANTITY_USDT = 100  # 每次交易金额 (USDT)
    SANDBOX_MODE = True  # 是否使用测试网

    # === 交易总开关 ===
    # True  = 允许真实下单 (危险!)
    # False = 禁止下单，只打印日志 (安全模式)
    ENABLE_TRADING = False
    
    # ================= 仓位控制 =================
    QUANTITY_USDT = 100  # 每次交易只用 100 U
    
    # ================= 策略参数 =================
    TIMEFRAMES = ['5m', '15m', '30m', '1h']    # K线周期：15分钟
    # === 策略交易设置 ===
    # 这一行是机器人用来下单的主周期 (必须包含在上面列表里)
    TRADE_TIMEFRAME = '5m'

    MA_FAST = 5          # 快线周期
    MA_SLOW = 20         # 慢线周期

    # === 报警设置 ===
    # Bark 推送链接 (格式通常是: https://api.day.app/你的私钥/)
    # 请确保最后面带有一个斜杠 /
    BARK_URL = 'https://api.day.app/MtNFHgi5zjRjdDQPoRJX9j/' 
    
    ENABLE_BARK = True        # 是否开启手机推送 (True/False)