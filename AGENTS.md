# 项目说明

这是一个股票因子分析网站。

技术栈：
- FastAPI
- MySQL
- AKShare
- HTML + JavaScript
- Nginx
- Ubuntu 服务器部署

工作规则：
- 默认使用中文回答。
- 修改前先说明会改哪些文件。
- 不要随意改变现有 API 返回格式。
- 不要随意删除已有功能。
- 优先小步修改。
- 大改前提醒我先 git commit。

# 股票池筛选规则

## 筛选范围
- 只保留沪深主板（main_board）股票
- 排除创业板（gem）、科创板（star）、北交所（bse）

## 排除条件
- 名称中包含以下关键词的股票将被排除：
  - ST（风险警示）
  - ETF（交易型开放式指数基金）
  - 指数（指数基金）
  - 可转债（可转换债券）
  - LOF（上市开放式基金）
  - REIT（房地产信托基金）
  - 基金（基金产品）
  - 债（债券相关）
  - 优先（优先股）
  - 退、退市（退市股票）
  - B股、B 股（B股股票）

## 数据源
- 优先使用 AKShare 获取股票列表
- AKShare 失败时使用 Baostock 作为备用

## 输出文件
- `data/full_stock_pool.csv`：全量股票池（所有板块）
- `data/stock_pool.csv`：沪深主板股票池（本项目使用）

# 项目目录结构

```
stock-screener/
├── api/                      # FastAPI 后端 API
│   ├── __init__.py
│   ├── api.py                # API 路由
│   ├── scoring.py            # 评分引擎
│   ├── risk.py               # 风险评估
│   ├── factor_config.py      # 因子配置
│   ├── stock_utils.py        # 股票工具函数
│   ├── screen_stocks.py      # 低市盈率筛选
│   └── db.py                 # 数据库连接
├── collector/                # 数据采集
│   ├── __init__.py
│   ├── main.py               # 采集入口
│   ├── fetch_a_stock.py      # 估值数据采集
│   ├── fetch_financial.py    # 财务数据采集
│   ├── update_dividend_akshare.py  # 股息率采集
│   ├── update_stock_pool.py  # 股票池更新
│   ├── update_financial.py   # 财务数据更新
│   ├── save_to_mysql.py      # 数据入库
│   └── timeout_utils.py      # 超时工具
├── frontend/                 # 前端
│   └── index.html            # 前端页面
├── database/                 # 数据库相关文件
│   ├── alter_tables.sql      # 修改表结构 SQL
│   └── create_tables.sql     # 创建表 SQL
├── config/                   # 配置文件
│   ├── __init__.py
│   ├── config.example.py     # 配置示例
│   └── config.py             # 实际配置（不提交到版本控制）
├── data/                     # 数据文件
│   ├── stock_pool.csv        # 沪深主板股票池
│   └── full_stock_pool.csv   # 全量股票池
├── docs/                     # 文档
│   └── AGENTS.md             # 项目说明文档
├── tests/                    # 测试文件
│   ├── __init__.py
│   ├── test_baostock.py      # baostock 测试
│   └── test_baostock_financial.py # baostock 财务测试
├── AGENTS.md                 # 项目说明（本文件）
├── DIRECTORY_STRUCTURE.md    # 目录结构说明
├── requirements.txt          # Python 依赖
└── .gitignore
```
