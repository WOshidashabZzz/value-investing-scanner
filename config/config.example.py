DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "your_mysql_password",
    "database": "stock_screener",
    "charset": "utf8mb4",
}

TUSHARE_TOKEN = "your_tushare_token"

# Alpha Vantage API 配置（美股备用数据源，可选）
# 免费版 API Key 申请：https://www.alphavantage.co/support/#api-key
ALPHA_VANTAGE_CONFIG = {
    "api_key": "",
    "base_url": "https://www.alphavantage.co/query",
}

# ===== 代理配置（美股海外 API 使用） =====
# 如果 mihomo/clash 等代理运行在本机 7890 端口，使用以下默认配置
# 设置为空字典 {} 则直连（不走代理）
# 也支持 HTTP_PROXY / HTTPS_PROXY 环境变量覆盖
PROXY_CONFIG = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}
