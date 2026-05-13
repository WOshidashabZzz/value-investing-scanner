"""
美股统一数据 Schema 与标准化层。

职责：
1. 定义美股数据的标准字段名、类型、单位
2. 提供 normalize 函数，将不同数据源的原始数据转换为标准格式
3. 提供 validate 函数，确保输出数据符合前端和评分引擎的期望
4. 与现有 us_stock_utils.py 和 update_us_stocks.py 兼容

使用方式：
    from api.us_stock_schema import normalize_record, US_STOCK_SCHEMA

    raw = {"pe_ratio": 15.5, "code": "AAPL"}
    record = normalize_record(raw, source="akshare")
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

# ============================================================
# 1. 标准字段定义
# ============================================================

# 标准字段列表（与前端 us.html 和评分引擎 us_stock_utils.py 兼容）
STANDARD_FIELDS = [
    # 标识字段
    "code",             # 股票代码，如 "AAPL"
    "name",             # 中文名称，如 "苹果"
    "sector",           # 行业分类，如 "科技"
    # 估值因子
    "pe",               # 市盈率（静态）
    "pb",               # 市净率
    # 质量因子
    "roe",              # 净资产收益率 (%)
    # 成长因子
    "revenue_growth",   # 营收同比增长 (%)
    "profit_growth",    # 利润同比增长 (%)
    # 股息因子
    "dividend_yield",   # 股息率 (%)
    # 动量因子（预留）
    "momentum_6m",      # 6个月动量 (%)
    "momentum_1y",      # 1年动量 (%)
    # 风险因子（预留）
    "volatility_1y",    # 1年波动率 (%)
    "max_drawdown_1y",  # 1年最大回撤 (%)
    # 评分字段（由评分引擎填充）
    "total_score",      # 综合评分（前端使用）
    "final_score",      # 最终评分（评分引擎输出）
    "valuation_score",  # 估值模块评分
    "quality_score",    # 质量模块评分
    "growth_score",     # 成长模块评分
    "dividend_score",   # 股息模块评分
    "momentum_score",   # 动量模块评分
    "risk_score",       # 风险模块评分
    "risk_tags",        # 风险标签
    "rank",             # 排名
    "valuation_date",   # 估值日期
    # 元信息字段
    "close_price",      # 最新收盘价
    "market_cap",       # 总市值
]

# 数值型字段列表（用于类型检查和转换）
NUMERIC_FIELDS = {
    "pe", "pb", "roe", "revenue_growth", "profit_growth",
    "dividend_yield", "momentum_6m", "momentum_1y",
    "volatility_1y", "max_drawdown_1y",
    "total_score", "final_score",
    "valuation_score", "quality_score", "growth_score",
    "dividend_score", "momentum_score", "risk_score",
    "close_price", "market_cap", "rank",
}

# 字符串字段列表
STRING_FIELDS = {
    "code", "name", "sector", "risk_tags", "valuation_date",
}

# ============================================================
# 2. 数据源字段映射表
# ============================================================

# AKShare 现货行情字段映射 (stock_us_spot_em)
AKSHARE_SPOT_FIELD_MAP = {
    "代码": "code",          # 原始格式 "106.AAPL"，需要提取 ticker
    "最新价": "close_price",
    "涨跌幅": None,           # 暂不映射
    "涨跌额": None,
    "成交量": None,
    "成交额": None,
    "振幅": None,
    "最高价": None,
    "最低价": None,
    "今开": None,
    "昨收": None,
    "量比": None,
    "换手率": None,
    "市盈率": "pe",
    "总市值": "market_cap",
    "流通市值": None,
}

# AKShare 百度估值字段映射 (stock_us_valuation_baidu)
AKSHARE_BAIDU_FIELD_MAP = {
    "pe": "pe",
    "pb": "pb",
    "pe_ttm": None,          # 暂不单独映射
}

# yfinance 基本面字段映射
YFINANCE_FIELD_MAP = {
    "pe": "pe",
    "pb": "pb",
    "roe": "roe",
    "revenue_growth": "revenue_growth",
    "profit_growth": "profit_growth",
    "dividend_yield": "dividend_yield",
    "market_cap": "market_cap",
    "close_price": "close_price",
}

# ============================================================
# 3. 标准化函数
# ============================================================


def safe_float(value: Any) -> float | None:
    """安全转换浮点数，处理 None、NaN、字符串等异常值。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or value in ("--", "N/A", "null", "None", ""):
            return None
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def extract_ticker(code_raw: str) -> str:
    """从 AKShare 代码格式中提取 ticker。

    AKShare 格式: "106.AAPL" → "AAPL"
    普通格式: "AAPL" → "AAPL"
    """
    if not code_raw:
        return ""
    code_str = str(code_raw).strip()
    if "." in code_str:
        return code_str.split(".")[-1].strip()
    return code_str


def normalize_akshare_spot(row: dict | pd.Series) -> dict:
    """标准化 AKShare 现货行情数据。

    Args:
        row: AKShare stock_us_spot_em 返回的单行数据

    Returns:
        标准化后的记录 dict
    """
    record: dict[str, Any] = {}

    # 提取 ticker
    raw_code = row.get("代码", "")
    record["code"] = extract_ticker(raw_code)

    # 名称
    record["name"] = str(row.get("名称", "")) if row.get("名称") else None

    # 市盈率
    pe = safe_float(row.get("市盈率"))
    if pe is not None and pe > 0:
        record["pe"] = pe

    # 最新价
    close_price = safe_float(row.get("最新价"))
    if close_price is not None:
        record["close_price"] = close_price

    # 总市值
    market_cap = safe_float(row.get("总市值"))
    if market_cap is not None:
        record["market_cap"] = market_cap

    return record


def normalize_baidu_valuation(data: dict) -> dict:
    """标准化百度估值数据。

    Args:
        data: 百度估值返回的 dict，包含 pe, pb 等字段

    Returns:
        标准化后的记录 dict
    """
    record: dict[str, Any] = {}

    pe = safe_float(data.get("pe"))
    if pe is not None and pe > 0:
        record["pe"] = pe

    pb = safe_float(data.get("pb"))
    if pb is not None and pb > 0:
        record["pb"] = pb

    return record


def normalize_yfinance_fundamentals(data: dict) -> dict:
    """标准化 yfinance 基本面数据。

    Args:
        data: yfinance 返回的 dict，包含 pe, pb, roe 等字段

    Returns:
        标准化后的记录 dict
    """
    record: dict[str, Any] = {}

    # 估值
    pe = safe_float(data.get("pe"))
    if pe is not None and pe > 0:
        record["pe"] = pe

    pb = safe_float(data.get("pb"))
    if pb is not None and pb > 0:
        record["pb"] = pb

    # 质量
    roe = safe_float(data.get("roe"))
    if roe is not None:
        record["roe"] = roe

    # 成长
    revenue_growth = safe_float(data.get("revenue_growth"))
    if revenue_growth is not None:
        record["revenue_growth"] = revenue_growth

    profit_growth = safe_float(data.get("profit_growth"))
    if profit_growth is not None:
        record["profit_growth"] = profit_growth

    # 股息
    dividend_yield = safe_float(data.get("dividend_yield"))
    if dividend_yield is not None:
        record["dividend_yield"] = dividend_yield

    # 市值
    market_cap = safe_float(data.get("market_cap"))
    if market_cap is not None:
        record["market_cap"] = market_cap

    return record


def normalize_record(
    record: dict[str, Any],
    source: str = "unknown",
) -> dict[str, Any]:
    """对单条记录进行最终标准化。

    确保所有标准字段存在，数值字段为 float|None，字符串字段为 str|None。

    Args:
        record: 待标准化的记录
        source: 数据来源标识，仅用于日志

    Returns:
        标准化后的记录
    """
    result: dict[str, Any] = {}

    for field in STANDARD_FIELDS:
        value = record.get(field)

        if field in NUMERIC_FIELDS:
            result[field] = safe_float(value)
        elif field in STRING_FIELDS:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                result[field] = None
            else:
                result[field] = str(value)
        else:
            result[field] = value

    return result


def normalize_dataframe(
    df: pd.DataFrame,
    source: str = "unknown",
) -> pd.DataFrame:
    """对整个 DataFrame 进行标准化。

    确保所有标准字段存在，类型正确。

    Args:
        df: 待标准化的 DataFrame
        source: 数据来源标识，仅用于日志

    Returns:
        标准化后的 DataFrame
    """
    result = df.copy()

    # 确保所有标准字段存在
    for field in STANDARD_FIELDS:
        if field not in result.columns:
            result[field] = None

    # 确保字段顺序一致
    result = result[STANDARD_FIELDS]

    return result


# ============================================================
# 4. 验证函数
# ============================================================


def validate_record(record: dict[str, Any]) -> list[str]:
    """验证单条记录是否合法。

    Args:
        record: 待验证的记录

    Returns:
        验证错误列表，空列表表示无错误
    """
    errors: list[str] = []

    # 必填字段
    code = record.get("code")
    if not code:
        errors.append("缺少 code 字段")

    # 数值字段类型检查
    for field in NUMERIC_FIELDS:
        value = record.get(field)
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"{field} 类型错误: 期望数值，实际 {type(value).__name__}")

    return errors


def validate_dataframe(df: pd.DataFrame) -> list[str]:
    """验证 DataFrame 是否合法。

    Args:
        df: 待验证的 DataFrame

    Returns:
        验证错误列表
    """
    errors: list[str] = []

    if df.empty:
        errors.append("DataFrame 为空")
        return errors

    # 检查必填字段
    for field in ["code", "name", "sector"]:
        if field not in df.columns:
            errors.append(f"缺少必填字段: {field}")
        elif df[field].isna().all():
            errors.append(f"字段 {field} 全部为空")

    # 检查数值字段类型
    for field in NUMERIC_FIELDS:
        if field in df.columns:
            non_null = df[field].dropna()
            if len(non_null) > 0:
                bad_types = non_null.apply(lambda x: not isinstance(x, (int, float)))
                if bad_types.any():
                    errors.append(f"{field} 包含非数值类型数据")

    return errors


# ============================================================
# 5. 工具函数
# ============================================================


def merge_records(
    base: dict[str, Any],
    *updates: dict[str, Any],
) -> dict[str, Any]:
    """合并多条记录，后面的记录覆盖前面的。

    只合并非 None 的值，保留已有值。

    Args:
        base: 基础记录
        updates: 更新记录（优先级递增）

    Returns:
        合并后的记录
    """
    result = dict(base)
    for update in updates:
        for key, value in update.items():
            if value is not None:
                result[key] = value
    return result


def records_from_df(df: pd.DataFrame, fields: list[str] | None = None) -> list[dict]:
    """将 DataFrame 转换为记录列表，处理 NaN 值。

    Args:
        df: 源 DataFrame
        fields: 要提取的字段列表，None 表示全部字段

    Returns:
        记录列表
    """
    if fields is None:
        fields = STANDARD_FIELDS

    result: list[dict] = []
    for _, row in df.iterrows():
        record = {}
        for field in fields:
            if field in row:
                value = row[field]
                if isinstance(value, float) and math.isnan(value):
                    record[field] = None
                elif pd.isna(value):
                    record[field] = None
                else:
                    record[field] = value
        result.append(record)
    return result
