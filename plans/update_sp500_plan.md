# S&P 500 成分股列表更新计划

## 现状

| 文件 | 股票数量 | 字段 | 问题 |
|------|---------|------|------|
| `data/sp500_symbols.csv` | ~360 只 | ticker, name, sector | 远少于 S&P 500 的 ~503 只；有重复 ticker；缺少 industry |
| `data/us_stocks/sp500_symbols.csv` | ~342 只 | ticker, name | 缺少 sector 和 industry |

## 目标

更新 `data/sp500_symbols.csv` 为完整的 S&P 500 成分股列表，字段包含：
- `ticker` - 股票代码（去重）
- `name` - 公司中文/英文名称
- `sector` - 板块分类（与现有分类一致：科技/金融/消费/医药/制造/周期/地产基建/公用环保）
- `industry` - 行业细分（新增字段）

## 数据源选择

使用 **Wikipedia S&P 500 列表页面**（https://en.wikipedia.org/wiki/List_of_S%26P_500_companies）作为数据源。

理由：
1. ✅ 公开稳定 - Wikipedia 页面长期维护，更新及时
2. ✅ 无需 API key - 直接抓取 HTML 表格
3. ✅ 字段完整 - 包含 Symbol、Security、GICS Sector、GICS Sub-Industry
4. ✅ 不接入新 API - 使用标准 HTTP 请求 + HTML 解析（BeautifulSoup）
5. ✅ 已在 requirements.txt 中的依赖：`requests`, `pandas`；需要新增 `beautifulsoup4` 或 `lxml`

## 方案

### 方案一：Wikipedia 抓取（推荐）

创建新脚本 `collector/update_sp500_list.py`：

1. 使用 `requests` 获取 Wikipedia 页面 HTML
2. 使用 `pandas.read_html()` 解析表格（无需额外依赖）
3. 提取字段：Symbol → ticker, Security → name, GICS Sector → sector, GICS Sub-Industry → industry
4. 将 GICS Sector 映射到现有中文 sector 分类
5. 去重（按 ticker）
6. 写入 `data/sp500_symbols.csv`

### 方案二：yfinance 获取

使用项目中已有的 yfinance 获取 S&P 500 成分股列表。

但 yfinance 获取成分股列表的稳定性不如 Wikipedia。

### 选定方案：方案一（Wikipedia）

## 需要修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `collector/update_sp500_list.py` | **新建** | S&P 500 成分股列表更新脚本 |
| `data/sp500_symbols.csv` | **更新** | 替换为完整列表 |
| `data/us_stocks/sp500_symbols.csv` | **更新** | 同步更新备份文件 |
| `collector/update_us_stocks.py` | **不改** | 已通过 `load_sp500_symbols()` 自动读取最新 CSV |
| `api/us_stock_utils.py` | **不改** | 评分逻辑不变 |
| `frontend/us.html` | **不改** | 前端不变 |

## 执行步骤

1. 创建 `collector/update_sp500_list.py`
   - 从 Wikipedia 抓取 S&P 500 成分股列表
   - GICS Sector → 中文 sector 映射
   - 去重
   - 写入 CSV（包含 ticker, name, sector, industry）
2. 运行脚本
3. 验证结果
4. 同步更新 `data/us_stocks/sp500_symbols.csv`
5. 告知用户统计信息

## GICS Sector → 中文 Sector 映射

| GICS Sector | 中文 Sector |
|-------------|-------------|
| Information Technology | 科技 |
| Financials | 金融 |
| Consumer Discretionary | 消费 |
| Consumer Staples | 消费 |
| Health Care | 医药 |
| Industrials | 制造 |
| Energy | 周期 |
| Materials | 周期 |
| Utilities | 公用环保 |
| Communication Services | 科技 |
| Real Estate | 地产基建 |

## 风险与注意事项

1. Wikipedia 页面结构变化可能导致解析失败 - 添加错误处理和备用方案
2. 网络请求可能超时 - 添加超时和重试机制
3. 中文名称需要从现有数据继承或使用英文名 - 保留现有中文名映射
4. 不修改评分逻辑、不修改前端、不接入新 API - 严格遵守
