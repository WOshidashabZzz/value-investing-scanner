# 项目目录结构

```
stock-screener/
├── api/                      # FastAPI 后端 API
│   ├── __init__.py
│   ├── api.py                # API 路由
│   ├── db.py                 # 数据库连接
│   ├── factor_config.py      # 因子配置
│   ├── risk.py               # 风险评估
│   ├── scoring.py            # 评分引擎
│   ├── screen_stocks.py      # 低市盈率筛选
│   └── stock_utils.py        # 股票工具函数
├── collector/                # 数据采集
│   ├── __init__.py
│   ├── fetch_a_stock.py      # 估值数据采集
│   ├── fetch_financial.py    # 财务数据采集
│   ├── main.py               # 采集入口
│   ├── save_to_mysql.py      # 数据入库
│   ├── timeout_utils.py      # 超时工具
│   ├── update_dividend_akshare.py  # 股息率采集
│   ├── update_financial.py   # 财务数据更新
│   └── update_stock_pool.py  # 股票池更新
├── config/                   # 配置文件
│   ├── __init__.py
│   ├── config.example.py     # 配置示例
│   └── config.py             # 实际配置（不提交到版本控制）
├── data/                     # 数据文件
│   ├── full_stock_pool.csv   # 全量股票池
│   └── stock_pool.csv        # 沪深主板股票池
├── database/                 # 数据库相关文件
│   ├── alter_tables.sql      # 修改表结构 SQL
│   └── create_tables.sql     # 创建表 SQL
├── docs/                     # 文档
│   └── AGENTS.md             # 项目说明文档
├── frontend/                 # 前端
│   └── index.html            # 前端页面
├── tests/                    # 测试文件
│   ├── __init__.py
│   ├── test_baostock.py      # baostock 测试
│   └── test_baostock_financial.py # baostock 财务测试
├── AGENTS.md                 # 项目说明
├── DIRECTORY_STRUCTURE.md    # 本文件
├── requirements.txt          # Python 依赖
└── .gitignore
```
