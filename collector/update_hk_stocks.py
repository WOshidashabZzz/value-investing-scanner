"""
港股数据采集脚本

数据源（按优先级）：
1. AKShare stock_hk_spot() — 新浪港股实时行情（2757 只，含代码、名称、最新价）
2. AKShare stock_hk_financial_indicator_em() — 东方财富港股财务指标（PE/PB/ROE/股息率/市值等，单只查询）

输出：
- data/hk_stock/latest.json   — 当前展示数据
- data/hk_stock/backup.json   — 上一次成功数据
- data/hk_stock/raw/           — 原始数据快照

评分逻辑：
- PE：较低加分（PE <= 0 或缺失则跳过）
- PB：较低加分（PB <= 0 或缺失则跳过）
- ROE：较高加分
- revenue_growth：较高加分
- profit_growth：较高加分
- dividend_yield：较高加分
- 至少 2 个有效因子才计算 final_score
"""

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "hk_stock"
RAW_DIR = DATA_DIR / "raw"
LATEST_PATH = DATA_DIR / "latest.json"
BACKUP_PATH = DATA_DIR / "backup.json"

# 港股标准输出字段
HK_OUTPUT_FIELDS = [
    "code",
    "name",
    "market",
    "sector",
    "industry",
    "latest_price",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "profit_growth",
    "dividend_yield",
    "market_cap",
    "final_score",
    "risk_tag",
    "update_time",
]

# 港股核心资产股票池（从 config/hk_stock_pool.json 加载）
# 包含：恒生指数成分股 + 恒生科技指数成分股 + ETF + 港股通热门
# 数据来源：恒生指数公司官网（https://www.hsi.com.hk/）
HSI_AND_HSTECH_STOCKS = [
    # === 恒生指数成分股（核心蓝筹）===
    "00001",  # 长和
    "00002",  # 中电控股
    "00003",  # 香港中华煤气
    "00005",  # 汇丰控股
    "00006",  # 电能实业
    "00008",  # 电讯盈科
    "00010",  # 恒隆集团
    "00011",  # 恒生银行
    "00012",  # 恒基地产
    "00014",  # 希慎兴业
    "00016",  # 新鸿基地产
    "00017",  # 新世界发展
    "00019",  # 太古股份公司Ａ
    "00027",  # 银河娱乐
    "00066",  # 港铁公司
    "00083",  # 信和置业
    "00101",  # 恒隆地产
    "00175",  # 吉利汽车
    "00241",  # 阿里健康
    "00267",  # 中信股份
    "00288",  # 万洲国际
    "00291",  # 华润啤酒
    "00316",  # 东方海外国际
    "00322",  # 康师傅控股
    "00354",  # 中国软件国际
    "00388",  # 香港交易所
    "00669",  # 创科实业
    "00700",  # 腾讯控股
    "00762",  # 中国联通
    "00780",  # 同程旅行
    "00857",  # 中国石油股份
    "00883",  # 中国海洋石油
    "00902",  # 华能国际电力股份
    "00939",  # 建设银行
    "00941",  # 中国移动
    "00981",  # 中芯国际
    "00992",  # 联想集团
    "01038",  # 长江基建集团
    "01088",  # 中国神华
    "01093",  # 石药集团
    "01099",  # 国药控股
    "01109",  # 华润置地
    "01113",  # 长实集团
    "01209",  # 华润万象生活
    "01211",  # 比亚迪股份
    "01299",  # 友邦保险
    "01347",  # 华虹半导体
    "01357",  # 美图公司
    "01378",  # 中国宏桥
    "01398",  # 工商银行
    "01548",  # 金斯瑞生物科技
    "01579",  # 颐海国际
    "01801",  # 信达生物
    "01810",  # 小米集团－Ｗ
    "01876",  # 百威亚太
    "01880",  # 中国中免
    "01898",  # 中煤能源
    "01928",  # 金沙中国有限公司
    "01929",  # 周大福
    "01997",  # 九龙仓置业
    "02007",  # 碧桂园
    "02013",  # 微盟集团
    "02015",  # 理想汽车－Ｗ
    "02018",  # 瑞声科技
    "02020",  # 安踏体育
    "02269",  # 药明生物
    "02313",  # 申洲国际
    "02318",  # 中国平安
    "02319",  # 蒙牛乳业
    "02331",  # 李宁
    "02333",  # 长城汽车
    "02338",  # 潍柴动力
    "02359",  # 药明康德
    "02382",  # 舜宇光学科技
    "02388",  # 中银香港
    "02601",  # 中国太保
    "02628",  # 中国人寿
    "02688",  # 新奥能源
    "02899",  # 紫金矿业
    "03328",  # 交通银行
    "03690",  # 美团－Ｗ
    "03888",  # 金山软件
    "03908",  # 中金公司
    "03968",  # 招商银行
    "03988",  # 中国银行
    "06030",  # 中信证券
    "06060",  # 众安在线
    "06160",  # 百济神州
    "06186",  # 中国飞鹤
    "06618",  # 京东健康
    "06862",  # 海底捞
    "06969",  # 思摩尔国际
    "09618",  # 京东集团－ＳＷ
    "09626",  # 哔哩哔哩－Ｗ
    "09633",  # 农夫山泉
    "09660",  # 地平线机器人－Ｗ
    "09888",  # 百度集团－ＳＷ
    "09899",  # 网易云音乐
    "09922",  # 九毛九
    "09926",  # 康方生物
    "09961",  # 携程集团－Ｓ
    "09988",  # 阿里巴巴－Ｗ
    "09992",  # 泡泡玛特
    "09999",  # 网易－Ｓ

    # === 恒生科技指数成分股（补充）===
    "00020",  # 商汤－Ｗ
    "00268",  # 金蝶国际
    "00303",  # VTECH HOLDINGS
    "00772",  # 阅文集团
    "00799",  # IGG
    "01024",  # 快手－Ｗ
    "01797",  # 东方甄选
    "01833",  # 平安好医生
    "02400",  # 心动公司
    "02518",  # 汽车之家－Ｓ

    # === 港股通热门标的（南向资金偏好）===
    "00175",  # 吉利汽车（已在上方，保留）
    "00291",  # 华润啤酒（已在上方）
    "00772",  # 阅文集团（已在上方）
    "00902",  # 华能国际（已在上方）
    "01088",  # 中国神华（已在上方）
    "01093",  # 石药集团（已在上方）
    "01099",  # 国药控股（已在上方）
    "01211",  # 比亚迪股份（已在上方）
    "01801",  # 信达生物（已在上方）
    "01880",  # 中国中免（已在上方）
    "02020",  # 安踏体育（已在上方）
    "02319",  # 蒙牛乳业（已在上方）
    "02331",  # 李宁（已在上方）
    "02382",  # 舜宇光学科技（已在上方）
    "02601",  # 中国太保（已在上方）
    "03328",  # 交通银行（已在上方）
    "03908",  # 中金公司（已在上方）
    "03968",  # 招商银行（已在上方）
    "06030",  # 中信证券（已在上方）
    "06160",  # 百济神州（已在上方）
    "06186",  # 中国飞鹤（已在上方）
    "09633",  # 农夫山泉（已在上方）
    "09926",  # 康方生物（已在上方）
    "09992",  # 泡泡玛特（已在上方）

]


def ensure_dirs():
    """确保缓存目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def safe_float(value):
    """将各种异常值统一转为 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in {"", "-", "--", "None", "null", "nan", "NaN", "N/A", "n/a"}:
            return None
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def clean_record(record: dict) -> dict:
    """清理记录中所有数值字段，NaN/Infinity/None 统一转为 null。"""
    cleaned = {}
    for key, value in record.items():
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            cleaned[key] = None
        elif isinstance(value, dict):
            cleaned[key] = clean_record(value)
        else:
            cleaned[key] = value
    return cleaned


def save_json(path, data):
    """安全写入 JSON 文件。"""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    tmp_path.replace(path)


def load_json(path):
    """安全读取 JSON 文件。"""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ============================================================
# 数据源 1：新浪港股实时行情
# ============================================================

def fetch_hk_spot_from_sina() -> list[dict] | None:
    """
    通过 AKShare stock_hk_spot() 获取港股实时行情。
    返回约 2757 只港股，含代码、名称、最新价。
    """
    try:
        import akshare as ak
        df = ak.stock_hk_spot()
        if df is None or df.empty:
            print("  [新浪] stock_hk_spot() 返回空数据")
            return None

        records = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip().zfill(5)
            name = str(row.get("中文名称", "")).strip()
            latest_price = safe_float(row.get("最新价"))

            if not code or not name:
                continue

            records.append({
                "code": code,
                "name": name,
                "latest_price": latest_price,
                "market": "hk",
            })

        print(f"  [新浪] 成功获取 {len(records)} 只港股行情")
        return records
    except ImportError:
        print("  [新浪] akshare 未安装，跳过")
        return None
    except Exception as e:
        print(f"  [新浪] stock_hk_spot() 失败: {type(e).__name__}: {e}")
        return None


# ============================================================
# 数据源 1.5：新浪单只港股行情查询（名称回填）
# ============================================================

def fetch_hk_name_from_sina_single(codes: list[str]) -> dict[str, str]:
    """
    通过新浪单只行情接口 hq.sinajs.cn 批量查询港股名称。
    用于回填 stock_hk_spot() 全量接口未覆盖的股票。

    Args:
        codes: 港股代码列表，如 ["09992", "02688"]

    Returns:
        {code: name} 字典，仅包含查询成功的股票
    """
    if not codes:
        return {}

    import urllib.request

    name_map: dict[str, str] = {}
    batch_size = 10  # 每批最多10只

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        sina_codes = [f"hk{c}" for c in batch]
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)

        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            text = resp.read().decode("gbk")
            for line in text.strip().split("\n"):
                if line.startswith("var hq_str_hk"):
                    # 格式: var hq_str_hk09992="POP MART,泡泡玛特,..."
                    parts = line.split('"')
                    if len(parts) >= 2:
                        data = parts[1].split(",")
                        code = line.split("_hk")[1].split("=")[0].strip()
                        cn_name = data[1].strip() if len(data) > 1 else ""
                        if cn_name:
                            name_map[code] = cn_name
        except Exception:
            pass  # 单批失败不影响其他批次

        time.sleep(0.1)  # 避免请求过快

    if name_map:
        print(f"  [新浪单只] 成功获取 {len(name_map)}/{len(codes)} 只股票名称")
    return name_map


# ============================================================
# 数据源 2：东方财富港股财务指标（单只查询）
# ============================================================

def fetch_hk_financial_indicator(symbol: str) -> dict | None:
    """
    通过 AKShare stock_hk_financial_indicator_em() 获取单只港股财务指标。
    返回 PE/PB/ROE/股息率/市值等。
    """
    try:
        import akshare as ak
        df = ak.stock_hk_financial_indicator_em(symbol=symbol)
        if df is None or df.empty:
            return None

        row = df.iloc[0]
        result = {
            "pe": safe_float(row.get("市盈率")),
            "pb": safe_float(row.get("市净率")),
            "roe": safe_float(row.get("股东权益回报率(%)")),
            "dividend_yield": safe_float(row.get("股息率TTM(%)")),
            "market_cap": safe_float(row.get("总市值(港元)")),
            "revenue_growth": safe_float(row.get("营业总收入滚动环比增长(%)")),
            "profit_growth": safe_float(row.get("净利润滚动环比增长(%)")),
        }
        return result
    except Exception as e:
        print(f"    [东方财富] {symbol} 财务指标失败: {type(e).__name__}")
        return None


def batch_fetch_financial_indicators(stock_list: list[dict], max_workers: int = 5) -> list[dict]:
    """
    批量获取港股财务指标。
    每只股票单独查询，失败不中断整体流程。
    """
    total = len(stock_list)
    success_count = 0
    fail_count = 0

    for i, stock in enumerate(stock_list):
        code = stock.get("code", "")
        if not code:
            continue

        # 显示进度
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  [财务指标] 进度 {i+1}/{total}")

        indicators = fetch_hk_financial_indicator(code)
        if indicators:
            stock.update(indicators)
            success_count += 1
        else:
            fail_count += 1

        # 避免请求过快
        time.sleep(0.3)

    print(f"  [财务指标] 完成: 成功 {success_count}, 失败 {fail_count}")
    return stock_list


# ============================================================
# 评分逻辑（与 api/api.py 中的区间评分保持一致）
# ============================================================

def _hk_score_pe(pe: float) -> float | None:
    """PE 区间评分。"""
    if pe is None or math.isnan(pe) or pe <= 0 or pe > 100:
        return None
    if pe < 3:
        return 30.0
    if pe < 8:
        return 80.0 - (pe - 3) / 5 * 20
    if pe <= 25:
        return 100.0 - (pe - 8) / 17 * 20
    if pe <= 60:
        return 80.0 - (pe - 25) / 35 * 40
    return 40.0 - (pe - 60) / 40 * 30


def _hk_score_pb(pb: float) -> float | None:
    """PB 区间评分。"""
    if pb is None or math.isnan(pb) or pb <= 0:
        return None
    if pb < 0.5:
        return 30.0
    if pb < 0.8:
        return 50.0 + (pb - 0.5) / 0.3 * 20
    if pb <= 3.5:
        return 100.0 - (pb - 0.8) / 2.7 * 30
    if pb <= 8:
        return 70.0 - (pb - 3.5) / 4.5 * 30
    return 20.0


def _hk_score_roe(roe: float) -> float | None:
    """ROE 区间评分。"""
    if roe is None or math.isnan(roe) or roe <= 0:
        return None
    if roe < 3:
        return 10.0
    if roe < 10:
        return 30.0 + (roe - 3) / 7 * 50
    if roe <= 25:
        return 80.0 + (roe - 10) / 15 * 20
    return 100.0


def _hk_score_growth(value: float) -> float | None:
    """增长率评分（已封顶）。"""
    if value is None or math.isnan(value):
        return None
    if value > 30:
        return 100.0
    if value > 10:
        return 80.0 + (value - 10) / 20 * 20
    if value > 0:
        return 50.0 + value / 10 * 30
    if value > -20:
        return 20.0 + (value + 20) / 20 * 30
    return max(0, 20.0 + (value + 20) / 30 * 20)


def _hk_score_dividend(dy: float) -> float | None:
    """股息率区间评分。"""
    if dy is None or math.isnan(dy) or dy <= 0:
        return None
    if dy > 10:
        return 20.0
    if dy > 6:
        return 80.0 - (dy - 6) / 4 * 20
    if dy >= 2:
        return 80.0 + (dy - 2) / 4 * 20
    if dy >= 1:
        return 40.0 + (dy - 1) / 1 * 40
    return dy / 1 * 40


def _clamp_growth(value, field: str):
    """增长率封顶。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if field == "revenue_growth":
        return max(-50.0, min(100.0, v))
    elif field == "profit_growth":
        return max(-100.0, min(150.0, v))
    return v


def calculate_hk_score(record: dict) -> dict:
    """
    港股评分逻辑（区间评分 + 增长率封顶）。
    因子：
    - PE：区间评分，8~25 最优
    - PB：区间评分，0.8~3.5 较合理
    - ROE：区间评分，10%~25% 较优
    - revenue_growth：封顶后评分
    - profit_growth：封顶后评分
    - dividend_yield：区间评分，2%~6% 较优

    至少 2 个有效因子才计算 final_score。
    """
    pe = safe_float(record.get("pe"))
    pb = safe_float(record.get("pb"))
    roe = safe_float(record.get("roe"))
    revenue_growth = safe_float(record.get("revenue_growth"))
    profit_growth = safe_float(record.get("profit_growth"))
    dividend_yield = safe_float(record.get("dividend_yield"))

    # 增长率封顶
    revenue_growth = _clamp_growth(revenue_growth, "revenue_growth")
    profit_growth = _clamp_growth(profit_growth, "profit_growth")

    # 各因子区间评分
    pe_score = _hk_score_pe(pe)
    pb_score = _hk_score_pb(pb)
    roe_score = _hk_score_roe(roe)
    rg_score = _hk_score_growth(revenue_growth)
    pg_score = _hk_score_growth(profit_growth)
    dy_score = _hk_score_dividend(dividend_yield)

    scores = [s for s in [pe_score, pb_score, roe_score, rg_score, pg_score, dy_score] if s is not None]

    # 至少 2 个有效因子才计算 final_score
    if len(scores) >= 2:
        final_score = round(sum(scores) / len(scores), 2)
    elif len(scores) == 1:
        final_score = round(scores[0], 2)
    else:
        final_score = None

    record["final_score"] = final_score

    # 生成风险标签
    risk_tag = generate_hk_risk_tag(record)
    record["risk_tag"] = risk_tag

    return record


def generate_hk_risk_tag(record: dict) -> str:
    """生成港股风险标签（与 api/api.py _hk_generate_risk_tag 一致）。"""
    pe = safe_float(record.get("pe"))
    pb = safe_float(record.get("pb"))
    roe = safe_float(record.get("roe"))
    revenue_growth = safe_float(record.get("revenue_growth"))
    profit_growth = safe_float(record.get("profit_growth"))
    dividend_yield = safe_float(record.get("dividend_yield"))

    tags = []

    # PE
    if pe is not None and pe <= 0:
        tags.append("PE异常")
    elif pe is not None and pe < 3:
        tags.append("PE过低")
    elif pe is not None and pe > 60:
        tags.append("PE过高")

    # PB
    if pb is not None and 0 < pb < 0.5:
        tags.append("PB异常")
    elif pb is not None and pb > 8:
        tags.append("PB过高")

    # 可能价值陷阱
    if (
        pe is not None and pb is not None and roe is not None
        and 0 < pe < 8 and 0 < pb < 0.8 and roe < 8
    ):
        tags.append("可能价值陷阱")

    # ROE
    if roe is not None:
        if roe < 0:
            tags.append("ROE为负")
        elif roe < 3:
            tags.append("ROE偏低")
        elif roe < 6:
            tags.append("ROE偏低")

    # 增长率
    if revenue_growth is not None:
        if revenue_growth > 100:
            tags.append("增长异常")
        elif revenue_growth < -50:
            tags.append("营收大幅下滑")
        elif revenue_growth < 0:
            tags.append("营收下滑")

    if profit_growth is not None:
        if profit_growth > 150:
            tags.append("增长异常")
        elif profit_growth < -100:
            tags.append("利润大幅下滑")
        elif profit_growth < 0:
            tags.append("利润下滑")

    # 利润波动大
    if profit_growth is not None and profit_growth > 100 and roe is not None and roe < 5:
        if "利润波动大" not in tags:
            tags.append("利润波动大")

    # 股息率
    if dividend_yield is not None:
        if dividend_yield > 10:
            tags.append("股息率异常偏高")
        elif dividend_yield > 6:
            tags.append("高股息")

    if not tags:
        tags.append("暂无明显风险")

    return "；".join(tags)


# ============================================================
# 股票池配置加载
# ============================================================

def load_hk_stock_pool_config() -> dict:
    """从 config/hk_stock_pool.json 加载股票池配置。"""
    config_path = PROJECT_ROOT / "config" / "hk_stock_pool.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  ⚠️ 无法加载股票池配置: {e}")
        return {}


# ============================================================
# 主流程
# ============================================================

def build_hk_stock_list(use_core_only: bool = False) -> list[dict]:
    """
    构建港股股票列表。
    优先从新浪全量行情中筛选核心资产股票池，再补充财务指标。

    Args:
        use_core_only: 如果为 True，只使用静态成分股列表（快速测试用，不获取财务指标）
    """
    print("=" * 60)
    print("港股数据采集 - 开始")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 加载股票池配置
    pool_config = load_hk_stock_pool_config()
    # 使用 set 去重，避免同一只股票重复采集
    unique_codes = list(dict.fromkeys(HSI_AND_HSTECH_STOCKS))  # 保持顺序并去重
    target_codes = set(unique_codes)
    print(f"  目标股票池: {len(target_codes)} 只")

    # Step 1: 获取港股实时行情（新浪全量）
    print("\n[Step 1] 获取港股实时行情...")
    spot_records = fetch_hk_spot_from_sina()

    if spot_records and len(spot_records) > 0:
        print(f"  新浪全量行情获取成功，共 {len(spot_records)} 只股票")

        # 从全量数据中筛选目标股票
        spot_map = {s["code"]: s for s in spot_records}

        stock_list = []
        found_count = 0
        for code in unique_codes:
            if code in spot_map:
                stock_list.append(spot_map[code])
                found_count += 1
            else:
                # 新浪数据中未找到，用占位记录
                stock_list.append({"code": code, "name": "", "latest_price": None, "market": "hk"})

        print(f"  从中筛选目标股票: 目标 {len(target_codes)} 只，找到 {found_count} 只")
    else:
        print("  新浪行情获取失败，使用静态成分股列表")
        stock_list = [
            {"code": code, "name": "", "latest_price": None, "market": "hk"}
            for code in unique_codes
        ]
        print(f"  静态成分股列表，共 {len(stock_list)} 只")

    # 如果是 core-only 模式，直接返回行情数据（不获取财务指标，仅用于快速测试）
    if use_core_only:
        print(f"\n[快速模式] 仅获取行情数据，共 {len(stock_list)} 只（其中 {sum(1 for s in stock_list if s.get('latest_price') is not None)} 只有最新价）")
        return stock_list

    # Step 1.5: 名称回填（新浪全量未覆盖的股票，通过单只接口补全名称）
    missing_name_stocks = [s for s in stock_list if not s.get("name")]
    if missing_name_stocks:
        missing_codes = [s["code"] for s in missing_name_stocks if s.get("code")]
        print(f"\n[Step 1.5] 名称回填（{len(missing_codes)} 只股票名称缺失）...")
        name_map = fetch_hk_name_from_sina_single(missing_codes)
        if name_map:
            filled = 0
            for stock in stock_list:
                code = stock.get("code", "")
                if not stock.get("name") and code in name_map:
                    stock["name"] = name_map[code]
                    filled += 1
            print(f"  名称回填完成: {filled}/{len(missing_codes)} 只")
    else:
        print(f"\n[Step 1.5] 名称回填: 无需回填，所有股票均有名称")

    # Step 2: 批量获取财务指标
    print(f"\n[Step 2] 批量获取财务指标（共 {len(stock_list)} 只）...")
    stock_list = batch_fetch_financial_indicators(stock_list)

    # Step 2.5: 板块映射（根据股票名称映射到 A 股一级板块分类）
    print(f"\n[Step 2.5] 板块映射...")
    from api.stock_utils import map_sector_by_name
    mapped_count = 0
    for stock in stock_list:
        name = stock.get("name", "")
        if name:
            sector = map_sector_by_name(name)
            if sector:
                stock["sector"] = sector
                mapped_count += 1
    print(f"  板块映射完成: {mapped_count}/{len(stock_list)} 只股票已映射")

    # Step 3: 评分
    print(f"\n[Step 3] 计算评分...")
    scored_list = []
    stock_count = 0
    for stock in stock_list:
        # 普通股票使用原有评分
        stock = calculate_hk_score(stock)
        stock_count += 1
        scored_list.append(stock)
    print(f"  评分完成: {stock_count} 只股票")

    # Step 4: 排序（按评分从高到低）
    scored_list.sort(
        key=lambda x: -(x.get("final_score") if x.get("final_score") is not None else -1),
    )

    # Step 5: 标准化输出字段
    print(f"\n[Step 4] 标准化输出字段...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = []
    filtered_count = 0
    for stock in scored_list:
        code = stock.get("code", "")
        name = stock.get("name", "")
        latest_price = safe_float(stock.get("latest_price"))

        # 质量过滤：排除仙股（价格 < 0.5 HKD）
        if latest_price is not None and latest_price < 0.5:
            filtered_count += 1
            continue

        record = {
            "code": code,
            "name": name,
            "market": "hk",
            "asset_type": "stock",
            "sector": stock.get("sector"),
            "industry": stock.get("industry"),
            "latest_price": latest_price,
            "pe": safe_float(stock.get("pe")),
            "pb": safe_float(stock.get("pb")),
            "roe": safe_float(stock.get("roe")),
            "revenue_growth": safe_float(stock.get("revenue_growth")),
            "profit_growth": safe_float(stock.get("profit_growth")),
            "dividend_yield": safe_float(stock.get("dividend_yield")),
            "market_cap": safe_float(stock.get("market_cap")),
            "final_score": safe_float(stock.get("final_score")),
            "risk_tag": stock.get("risk_tag", "数据不足"),
            "update_time": now_str,
        }
        # 清理 NaN
        record = clean_record(record)
        output.append(record)

    print(f"\n[完成] 共处理 {len(output)} 只港股（过滤 {filtered_count} 只仙股）")
    return output


def save_results(records: list[dict]):
    """保存结果到 latest.json 和 backup.json。"""
    # 保存 latest.json
    save_json(LATEST_PATH, records)
    print(f"  -> 已保存 latest.json ({len(records)} 条)")

    # 保存 backup.json
    save_json(BACKUP_PATH, records)
    print(f"  -> 已保存 backup.json ({len(records)} 条)")

    # 保存原始数据快照
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RAW_DIR / f"hk_stocks_{timestamp}.json"
    save_json(raw_path, records)
    print(f"  -> 已保存原始快照 {raw_path.name}")


def print_statistics(records: list[dict]):
    """输出数据覆盖率统计。"""
    total = len(records)
    if total == 0:
        print("\n无数据，跳过统计")
        return

    fields = [
        ("latest_price", "最新价"),
        ("pe", "PE"),
        ("pb", "PB"),
        ("roe", "ROE"),
        ("revenue_growth", "营收增长率"),
        ("profit_growth", "净利润增长率"),
        ("dividend_yield", "股息率"),
        ("market_cap", "市值"),
        ("final_score", "综合评分"),
    ]

    print("\n" + "=" * 60)
    print("数据覆盖率统计")
    print("=" * 60)
    print(f"总记录数: {total}")
    print("-" * 40)

    for field, label in fields:
        count = sum(1 for r in records if r.get(field) is not None)
        pct = round(count / total * 100, 1) if total > 0 else 0
        print(f"  {label}: {count}/{total} ({pct}%)")

    # final_score 分布
    scored = [r for r in records if r.get("final_score") is not None]
    if scored:
        scores = [r["final_score"] for r in scored]
        print(f"\n  final_score 范围: {min(scores):.1f} ~ {max(scores):.1f}")
        print(f"  final_score 均值: {sum(scores)/len(scores):.1f}")

    print("=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="港股数据采集脚本")
    parser.add_argument("--core-only", action="store_true", help="只使用核心股票池（快速测试用）")
    args = parser.parse_args()

    ensure_dirs()

    records = build_hk_stock_list(use_core_only=args.core_only)

    if records:
        save_results(records)
        print_statistics(records)
    else:
        print("\n警告: 未获取到任何港股数据，保留现有缓存文件")
        # 尝试从 backup.json 恢复
        backup = load_json(BACKUP_PATH)
        if backup:
            print("  从 backup.json 恢复数据")
            save_json(LATEST_PATH, backup)
            print(f"  已恢复 {len(backup)} 条数据到 latest.json")

    print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
