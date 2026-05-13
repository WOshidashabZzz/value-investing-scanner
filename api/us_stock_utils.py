"""
美股数据工具模块。

提供美股评分、字段映射、响应格式化等功能。
与 A 股共用相同的评分体系，但更宽容地处理缺失字段。
"""

import math
from typing import Any

import pandas as pd


# ===== 美股响应字段列表 =====
# 与 A 股 STOCK_RESPONSE_FIELDS 保持一致，但去掉 A 股特有字段
US_STOCK_RESPONSE_FIELDS = [
    "code",
    "name",
    "sector",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "profit_growth",
    "dividend_yield",
    "momentum_6m",
    "momentum_1y",
    "volatility_1y",
    "max_drawdown_1y",
    "total_score",
    "final_score",
    "valuation_score",
    "quality_score",
    "growth_score",
    "dividend_score",
    "momentum_score",
    "risk_score",
    "risk_tags",
    "rank",
    "valuation_date",
]


def clean_value(value: Any):
    """将 NaN/None 等空值转换为 JSON 友好的 None。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def records_from_df(df: pd.DataFrame, fields: list[str]) -> list[dict]:
    """按指定字段输出 JSON 记录，缺失列自动补 None。"""
    output = df.copy()
    for field in fields:
        if field not in output.columns:
            output[field] = None

    records = output[fields].to_dict(orient="records")
    return [
        {key: clean_value(value) for key, value in record.items()}
        for record in records
    ]


# ===== 美股评分函数 =====
# 与 A 股评分逻辑类似，但更宽容（允许更多字段为 null）


def score_factor_series(series, direction: str) -> pd.Series:
    """按因子方向将原始数值转换为 0~100 分。"""
    values = pd.to_numeric(series, errors="coerce").replace(
        [float("inf"), float("-inf")], pd.NA
    )
    scores = pd.Series(float("nan"), index=series.index)
    valid = values.dropna()

    if valid.empty:
        return scores

    ascending = direction == "lower_better"
    ranks = valid.rank(method="min", ascending=ascending)
    total = len(valid)

    if total == 1:
        scores.loc[valid.index] = 100.0
    else:
        scores.loc[valid.index] = (1 - (ranks - 1) / (total - 1)) * 100

    return scores.clip(lower=0, upper=100).round(2)


def is_factor_available(df, factor_name, min_valid_ratio=0.1) -> bool:
    """判断某个因子是否有足够有效数据参与评分。
    美股数据可能更稀疏，所以 min_valid_ratio 设得比 A 股低。
    """
    if factor_name not in df.columns or df.empty:
        return False

    values = pd.to_numeric(df[factor_name], errors="coerce")
    valid_count = values.notna().sum()
    if valid_count <= 0:
        return False

    valid_ratio = valid_count / len(df)
    return valid_ratio >= min_valid_ratio


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """归一化权重，返回权重占比。"""
    cleaned = {}
    for key, value in weights.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            cleaned[key] = number

    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {key: value / total for key, value in cleaned.items()}


# 美股因子配置（与 A 股一致）
US_FACTOR_CONFIG = {
    "pe": {"category": "valuation", "direction": "lower_better", "weight": 63},
    "pb": {"category": "valuation", "direction": "lower_better", "weight": 37},
    "roe": {"category": "quality", "direction": "higher_better", "weight": 100},
    "revenue_growth": {
        "category": "growth",
        "direction": "higher_better",
        "weight": 50,
    },
    "profit_growth": {
        "category": "growth",
        "direction": "higher_better",
        "weight": 50,
    },
    "dividend_yield": {
        "category": "dividend",
        "direction": "higher_better",
        "weight": 100,
    },
}

US_CATEGORY_WEIGHTS = {
    "valuation": 35,
    "quality": 30,
    "growth": 25,
    "dividend": 10,
}


def _get_category_factors(category: str) -> list[str]:
    """获取某个模块下的因子列表。"""
    return [
        factor
        for factor, config in US_FACTOR_CONFIG.items()
        if config["category"] == category
    ]


def _calculate_category_score(
    df: pd.DataFrame,
    category: str,
    factor_weights: dict[str, float],
    active_factors: set[str],
) -> pd.Series:
    """按模块内部有效因子权重计算模块得分。"""
    category_factors = [
        factor
        for factor in _get_category_factors(category)
        if factor in active_factors
    ]

    if not category_factors:
        return pd.Series(float("nan"), index=df.index)

    normalized = _normalize_weights(
        {
            factor: factor_weights.get(
                factor, US_FACTOR_CONFIG[factor]["weight"]
            )
            for factor in category_factors
        }
    )

    if not normalized:
        return pd.Series(float("nan"), index=df.index)

    score = pd.Series(float("nan"), index=df.index)

    for index, row in df.iterrows():
        row_weights = {}
        row_score = 0.0

        for factor, weight in normalized.items():
            score_col = f"{factor}_score"
            if score_col not in df.columns or pd.isna(row.get(score_col)):
                continue
            row_weights[factor] = weight

        row_normalized = _normalize_weights(row_weights)
        if not row_normalized:
            continue

        for factor, weight in row_normalized.items():
            row_score += row[f"{factor}_score"] * weight
        score.at[index] = round(row_score, 2)

    return score.round(2)


def _calculate_raw_score(
    df: pd.DataFrame,
    active_categories: list[str],
    category_weights: dict[str, float],
) -> pd.Series:
    """按有效模块动态归一化权重计算原始总分。"""
    normalized = _normalize_weights(
        {
            category: category_weights.get(
                category, US_CATEGORY_WEIGHTS.get(category, 0)
            )
            for category in active_categories
        }
    )

    raw_score = pd.Series(0.0, index=df.index)

    if not normalized:
        return raw_score

    for index, row in df.iterrows():
        row_weights = {}
        score = 0.0

        for category, weight in normalized.items():
            score_col = f"{category}_score"
            if score_col not in df.columns or pd.isna(row.get(score_col)):
                continue
            row_weights[category] = weight

        row_normalized = _normalize_weights(row_weights)
        if not row_normalized:
            continue

        for category, weight in row_normalized.items():
            score += row[f"{category}_score"] * weight
        raw_score.at[index] = round(score, 2)

    return raw_score.round(2)


def _calculate_sector_rank_score(
    df: pd.DataFrame,
    score_column: str = "raw_score",
    sector_column: str = "sector",
) -> pd.Series:
    """
    计算 sector 内排名评分。

    在同一行业内的股票按 raw_score 排名，转换为 0~100 分。
    raw_score 越高，sector_rank_score 越高（ascending=False）。
    这样科技股在科技行业内排名，金融股在金融行业内排名，
    避免科技股因 PE 普遍偏高而被整体低估。

    Args:
        df: 包含评分和行业字段的 DataFrame
        score_column: 用于排名的评分列名
        sector_column: 行业列名

    Returns:
        sector 内排名评分 Series (0~100)
    """
    scores = pd.Series(float("nan"), index=df.index)

    if score_column not in df.columns or sector_column not in df.columns:
        return scores

    raw = pd.to_numeric(df[score_column], errors="coerce")

    for sector in df[sector_column].unique():
        if pd.isna(sector):
            continue
        mask = df[sector_column] == sector
        sector_raw = raw[mask].dropna()

        if sector_raw.empty:
            continue

        if len(sector_raw) == 1:
            scores.loc[sector_raw.index] = 100.0
        else:
            # ascending=False: raw_score 越高，rank 越高，sector_rank_score 越高
            ranks = sector_raw.rank(method="min", ascending=False)
            sector_scores = (1 - (ranks - 1) / (len(sector_raw) - 1)) * 100
            scores.loc[sector_raw.index] = sector_scores

    return scores.clip(lower=0, upper=100).round(2)


def calculate_us_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    美股评分函数。

    使用与 A 股相同的 6 因子评分体系，但更宽容地处理缺失字段。
    缺失的因子自动跳过，不影响其他因子评分。

    新增特性：
    - sector 内排名评分：同一行业内的股票互相比较
    - 科技股不再因 PE 偏高而被整体低估
    - final_score 结合全局评分和 sector 内排名

    Args:
        df: 包含 pe, pb, roe, revenue_growth, profit_growth, dividend_yield,
            sector 等字段的 DataFrame

    Returns:
        添加了评分字段的 DataFrame
    """
    if df.empty:
        return df.copy()

    result = df.copy()

    # 确定有效因子
    active_factors = [
        factor for factor in US_FACTOR_CONFIG if is_factor_available(result, factor)
    ]
    active_factor_set = set(active_factors)
    inactive_factors = [
        factor for factor in US_FACTOR_CONFIG if factor not in active_factor_set
    ]

    # 确定有效模块
    active_categories = [
        category
        for category in US_CATEGORY_WEIGHTS
        if any(
            factor in active_factor_set
            for factor in _get_category_factors(category)
        )
    ]
    inactive_categories = [
        category
        for category in US_CATEGORY_WEIGHTS
        if category not in active_categories
    ]

    # 计算因子得分
    for factor, config in US_FACTOR_CONFIG.items():
        if factor not in result.columns:
            result[factor] = pd.NA
        result[factor] = pd.to_numeric(result[factor], errors="coerce")
        if factor in active_factor_set:
            result[f"{factor}_score"] = score_factor_series(
                result[factor], config["direction"]
            )
        else:
            result[f"{factor}_score"] = float("nan")

    # 计算模块得分
    for category in US_CATEGORY_WEIGHTS:
        result[f"{category}_score"] = _calculate_category_score(
            result, category, {}, active_factor_set
        )

    # 计算原始总分（全局排名）
    result["raw_score"] = _calculate_raw_score(
        result, active_categories, US_CATEGORY_WEIGHTS
    )

    # 计算 sector 内排名评分
    # 在同一行业内比较 raw_score，避免跨行业不公平
    result["sector_rank_score"] = _calculate_sector_rank_score(
        result, score_column="raw_score", sector_column="sector"
    )

    # 最终评分 = 70% 全局评分 + 30% sector 内排名评分
    # sector 内排名确保科技股在科技行业内比较，不会被金融股的低 PE 带偏
    global_score = result["raw_score"].fillna(0)
    sector_score = result["sector_rank_score"].fillna(0)

    # 如果 sector 排名不可用（如所有股票在同一行业），则纯用全局评分
    if sector_score.notna().sum() > 0:
        result["final_score"] = (
            global_score * 0.7 + sector_score * 0.3
        ).round(2)
    else:
        result["final_score"] = global_score.round(2)

    # 简化版风险标签（美股暂无复杂风险计算）
    result["risk_tags"] = ""

    # 添加元信息
    result["active_categories"] = ",".join(active_categories)
    result["inactive_categories"] = ",".join(inactive_categories)
    result["active_factors"] = ",".join(active_factors)
    result["inactive_factors"] = ",".join(inactive_factors)

    return result.sort_values(by="final_score", ascending=False)
