import requests

# 请修改这里的端口号为你 VPN 的端口
PROXY_PORT = 7890 

proxies = {
    'http': f'http://127.0.0.1:{PROXY_PORT}',
    'https': f'http://127.0.0.1:{PROXY_PORT}'
}

print(f"🕵️‍♂️ 正在尝试通过端口 {PROXY_PORT} 连接币安...")

try:
    # 强制让 requests 走代理
    response = requests.get('https://api.binance.com/api/v3/ping', proxies=proxies, timeout=10)
    
    if response.status_code == 200:
        print("✅✅✅ 连接成功！你的代理完全没问题。")
        print("👉 如果主程序还报错，请检查代码里是不是粘贴错了位置。")
    else:
        print(f"❌ 连接通了，但是服务器返回错误: {response.status_code}")

except Exception as e:
    print("\n❌❌❌ 连接失败！")
    print(f"错误信息: {e}")
    print("-" * 30)
    print("💡 解决方案:")
    print("1. 你的端口号写错了？(检查 VPN 设置)")
    print("2. 你的 VPN 没开？或者没开‘全局模式’？")
    print("3. SSL 证书拦截？(尝试换个 VPN 节点)")