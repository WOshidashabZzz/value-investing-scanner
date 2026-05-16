# 📊 价值投资扫描器 (Value Investing Scanner)

> 多因子价值投资辅助筛选系统 — 支持 A 股、港股、美股三大市场

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ 功能特性

- **🌏 多市场覆盖** — 同时支持 A 股（沪深主板）、港股、美股（S&P 500）
- **📊 多因子评分体系** — 基于估值、质量、成长、分红四大维度综合评分（满分 100 分）
- **⚠️ 风险提示** — 自动识别高负债、持续亏损、ST 等风险因素
- **🏭 行业板块分类** — 支持按金融、消费、医药、科技等板块筛选
- **🔄 数据自动更新** — 通过 systemd timer / cron 定时采集，无需手动操作
- **🛡️ 双版本安全更新** — staging → latest → backup 三级数据版本管理，更新失败自动回滚
- **📱 响应式前端** — 原生 HTML + JavaScript，深色主题，移动端友好

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | [FastAPI](https://fastapi.tiangolo.com) (Python) |
| 数据库 | MySQL 8.0+ |
| A 股数据源 | [AKShare](https://akshare.akfamily.xyz)（主）、[Baostock](http://baostock.com)（备） |
| 美股数据源 | [YFinance](https://github.com/ranaroussi/yfinance) |
| 前端 | 原生 HTML + CSS + JavaScript |
| 部署 | Nginx + Ubuntu |
| 定时任务 | systemd timer / cron |

## 📁 项目结构

```
value-investing-scanner/
├── api/                      # FastAPI 后端 API
│   ├── api.py                # API 路由（A 股 + 美股）
│   ├── db.py                 # 数据库连接
│   ├── scoring.py            # 评分引擎
│   ├── risk.py               # 风险评估
│   ├── factor_config.py      # 因子配置
│   ├── stock_utils.py        # A 股工具函数
│   ├── us_stock_utils.py     # 美股工具函数
│   ├── us_stock_schema.py    # 美股数据模型
│   ├── screen_stocks.py      # 低市盈率筛选
│   └── validate_staging.py   # 数据校验
├── collector/                # 数据采集
│   ├── main.py               # A 股采集入口
│   ├── auto_update.py        # 美股自动更新
│   ├── auto_update_hk.py     # 港股自动更新
│   ├── cache_manager.py      # 缓存管理
│   ├── fetch_a_stock.py      # A 股估值采集
│   ├── fetch_financial.py    # 财务数据采集
│   ├── save_to_mysql.py      # 数据入库
│   ├── update_stock_pool.py  # 股票池更新
│   ├── update_hk_stocks.py   # 港股数据更新
│   ├── update_us_stocks.py   # 美股数据更新
│   ├── update_sp500_list.py  # S&P 500 列表更新
│   ├── update_sector.py      # 行业板块更新
│   ├── proxy_utils.py        # 代理工具
│   ├── timeout_utils.py      # 超时工具
│   └── providers/            # 数据提供者
├── frontend/                 # 前端页面
│   ├── index.html            # A 股页面
│   ├── cn.html               # A 股（备用）
│   ├── hk.html               # 港股页面
│   └── us.html               # 美股页面
├── config/                   # 配置文件
│   ├── config.example.py     # 配置示例
│   └── hk_stock_pool.json    # 港股股票池配置
├── database/                 # 数据库相关
│   ├── create_tables.sql     # 建表 SQL
│   ├── alter_tables.sql      # 改表 SQL
│   └── add_*.sql             # 数据库迁移脚本
├── scripts/                  # 运维脚本
│   ├── update_hk_stocks.sh   # 港股更新脚本
│   ├── update_us_stocks.sh   # 美股更新脚本
│   └── update-*-stocks.{service,timer}  # systemd 配置
├── tests/                    # 测试
├── docs/                     # 文档
│   ├── AGENTS.md             # 项目说明
│   └── nginx.example.conf    # Nginx 配置示例
├── requirements.txt          # Python 依赖
└── .gitignore
```

## 🚀 快速开始

### 前置条件

- Python 3.10+
- MySQL 8.0+
- pip / conda

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/value-investing-scanner.git
cd value-investing-scanner
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 创建数据库

```bash
mysql -u root -p < database/create_tables.sql
```

### 4. 配置

```bash
cp config/config.example.py config/config.py
# 编辑 config/config.py，填入数据库连接信息
```

### 5. 更新股票池

```bash
# A 股股票池
python -m collector.update_stock_pool

# S&P 500 列表
python -m collector.update_sp500_list
```

### 6. 启动服务

```bash
uvicorn api.api:app --host 0.0.0.0 --port 8000
```

### 7. 访问

打开浏览器访问 `http://localhost:8000`

## 📖 使用说明

### 数据更新

```bash
# A 股全量更新
python -m collector.main

# 美股自动更新
python -m collector.auto_update

# 港股自动更新
python -m collector.auto_update_hk
```

### API 接口

| 接口 | 说明 |
|------|------|
| `GET /api/stocks` | 获取 A 股评分数据 |
| `GET /api/us-stocks` | 获取美股评分数据 |
| `GET /api/hk-stocks` | 获取港股评分数据 |
| `GET /api/sectors` | 获取行业板块列表 |
| `GET /api/screen-low-pe` | 低市盈率筛选 |

### 定时任务部署

参考 `scripts/` 目录下的 systemd 配置文件和 Shell 脚本，部署定时数据更新。

```bash
# 复制 systemd 配置
sudo cp scripts/update-us-stocks.service /etc/systemd/system/
sudo cp scripts/update-us-stocks.timer /etc/systemd/system/

# 启用定时器
sudo systemctl daemon-reload
sudo systemctl enable update-us-stocks.timer
sudo systemctl start update-us-stocks.timer
```

## 📊 评分体系

系统基于以下四大维度对股票进行综合评分（满分 100 分）：

| 维度 | 权重 | 因子 | 说明 |
|------|------|------|------|
| 估值 | 30% | PE_TTM、PB | 市盈率、市净率越低越好 |
| 质量 | 30% | ROE | 净资产收益率越高越好 |
| 成长 | 25% | 营收增长率、净利润增长率 | 增长率越高越好 |
| 分红 | 15% | 股息率 | 股息率越高越好 |

## ⚠️ 风险提示

> **本系统仅供投资研究参考，不构成任何投资建议。**
>
> 股票投资有风险，过往表现不代表未来收益。请基于自身判断做出投资决策。

## 📄 许可证

[MIT](LICENSE)

---

**关键词**：价值投资 · 多因子选股 · A 股 · 港股 · 美股 · S&P 500 · FastAPI · 股票筛选器
