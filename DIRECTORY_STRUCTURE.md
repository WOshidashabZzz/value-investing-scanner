# 项目目录结构

```
stock-screener/
├── frontend/                  # 前端文件
│   └── index.html             # 前端页面
├── database/                  # 数据库相关文件
│   ├── alter_tables.sql       # 修改表结构 SQL
│   └── create_tables.sql      # 创建表 SQL
├── docs/                      # 文档
│   └── AGENTS.md              # 项目说明文档
├── api.py                     # FastAPI 应用入口
├── config.example.py          # 配置示例
├── db.py                      # 数据库连接
├── factor_config.py           # 因子配置
├── fetch_a_stock.py           # 获取股票估值数据
├── fetch_financial.py         # 获取财务数据
├── main.py                    # 命令行入口
├── risk.py                    # 风险评估
├── save_to_mysql.py           # 保存数据到 MySQL
├── scoring.py                 # 评分逻辑
├── screen_stocks.py           # 低市盈率筛选
├── stock_utils.py             # 股票工具函数
├── timeout_utils.py           # 超时工具
├── update_dividend_akshare.py # 更新股息数据
├── update_financial.py        # 更新财务数据
├── update_stock_pool.py       # 更新股票池
├── requirements.txt           # Python 依赖
├── stock_pool.csv             # 股票池 CSV
├── full_stock_pool.csv        # 完整股票池 CSV
├── test_baostock.py           # baostock 测试
├── test_baostock_financial.py # baostock 财务测试
└── DIRECTORY_STRUCTURE.md     # 本文件
```
