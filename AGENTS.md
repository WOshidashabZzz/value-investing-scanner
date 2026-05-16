# 价值投资扫描器 (Value Investing Scanner)

多因子价值投资辅助筛选系统，支持 **A 股（沪深主板）**、**港股** 和 **美股（S&P 500）** 三大市场。

## 功能特性

- **多市场支持**：A 股（沪深主板）、港股、美股（S&P 500）
- **多因子评分**：基于估值、质量、成长、分红四大维度综合评分
- **风险提示**：自动识别高负债、亏损、ST 等风险因素
- **行业板块**：支持按行业板块筛选和分类
- **数据自动更新**：通过 systemd timer / cron 定时自动采集数据
- **双版本安全更新**：staging → latest → backup 三级数据版本管理

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python) |
| 数据库 | MySQL |
| 数据源 | AKShare（A 股）、Baostock（A 股备用）、YFinance（美股） |
| 前端 | 原生 HTML + JavaScript |
| 部署 | Nginx + Ubuntu |
| 定时任务 | systemd timer / cron |

## 项目结构

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
│   ├── update_*_stocks.sh    # 数据更新 Shell 脚本
│   ├── update-*-stocks.service  # systemd service 配置
│   └── update-*-stocks.timer    # systemd timer 配置
├── tests/                    # 测试
├── docs/                     # 文档
│   ├── AGENTS.md             # 项目说明
│   └── nginx.example.conf    # Nginx 配置示例
├── requirements.txt          # Python 依赖
└── .gitignore
```

## 快速开始

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 创建 MySQL 数据库
mysql -u root -p < database/create_tables.sql
```

### 2. 配置

```bash
# 复制配置示例文件
cp config/config.example.py config/config.py

# 编辑 config/config.py，填入实际的数据库连接信息
```

### 3. 更新股票池

```bash
# 更新 A 股股票池
python -m collector.update_stock_pool

# 更新 S&P 500 列表
python -m collector.update_sp500_list
```

### 4. 启动 API 服务

```bash
# 启动 FastAPI 服务
uvicorn api.api:app --host 0.0.0.0 --port 8000
```

### 5. 访问前端

打开浏览器访问 `http://localhost:8000` 或通过 Nginx 反向代理访问。

## 数据更新

### A 股数据

```bash
# 全量更新（股票池 + 估值 + 财务 + 股息率）
python -m collector.main

# 仅更新财务数据
python -m collector.update_financial
```

### 美股数据

```bash
# 自动更新
python -m collector.auto_update

# 强制更新（忽略缓存）
python -m collector.auto_update --force
```

### 港股数据

```bash
# 自动更新
python -m collector.auto_update_hk
```

## 评分体系

系统基于以下四大维度对股票进行综合评分（满分 100 分）：

| 维度 | 权重 | 因子 |
|------|------|------|
| 估值 | 30% | PE_TTM、PB |
| 质量 | 30% | ROE |
| 成长 | 25% | 营收增长率、净利润增长率 |
| 分红 | 15% | 股息率 |

## 许可证

MIT
