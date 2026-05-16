import math

import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from api.factor_config import CATEGORY_WEIGHTS, FACTOR_CONFIG
from api.risk import calculate_risk


def get_latest_strategy_data(
    board: str | None = "main_board",
    market: str | None = None,
    sector: str | None = None,
) -> pd.DataFrame:
    """读取最新交易日估值数据，并关联每只股票最新一期财务数据。"""
    engine = get_engine()

    sql = text("""
        SELECT
            b.bs_code,
            b.symbol,
            b.name,
            b.market,
            b.board,
            b.sector,
            v.trade_date,
            v.close_price,
            v.pe_ttm,
            v.pb,
            v.ps_ttm,
            v.pcf_ncf_ttm,
            f.report_date,
            f.roe,
            f.revenue_growth,
            f.profit_growth,
            f.dividend_yield
        FROM stock_basic b
        JOIN stock_valuation v ON b.id = v.stock_id
        LEFT JOIN stock_financial f
            ON b.id = f.stock_id
           AND f.report_date = (
                SELECT MAX(f2.report_date)
                FROM stock_financial f2
                WHERE f2.stock_id = b.id
           )
        WHERE v.data_version = 'latest'
          AND v.trade_date = (
            SELECT MAX(trade_date)
            FROM stock_valuation
            WHERE data_version = 'latest'
        )
    """)
    filters = []
    params = {}

    if board and board != "all":
        filters.append("b.board = :board")
        params["board"] = board

    if market:
        filters.append("b.market = :market")
        params["market"] = market

    if sector:
        filters.append("b.sector = :sector")
        params["sector"] = sector

    sql_text = sql.text
    if filters:
        sql_text = f"{sql_text}\n        AND {' AND '.join(filters)}"

    return pd.read_sql(text(sql_text), engine, params=params)


def get_latest_valuation_data() -> pd.DataFrame:
    """兼容旧代码：返回最新策略数据。"""
    return get_latest_strategy_data()


def _clamp_growth(value, field: str):
    """对增长率做封顶处理，避免异常值冲榜。"""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
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


def score_pe_ttm(pe: float) -> float | None:
    """PE 区间评分。
    8~25 最优(100~80)，3~8 适当(80~60)，<3 异常低估(30)，
    25~60 逐步降分(80~40)，60~100 低分(40~10)，<=0 或 >100 不参与。
    """
    if pe is None or math.isnan(pe) or pe <= 0 or pe > 100:
        return None
    if pe < 3:
        return 30.0
    if pe < 8:
        # 3~8: 80~60 线性递减
        return 80.0 - (pe - 3) / 5 * 20
    if pe <= 25:
        # 8~25: 100~80 线性递减
        return 100.0 - (pe - 8) / 17 * 20
    if pe <= 60:
        # 25~60: 80~40 线性递减
        return 80.0 - (pe - 25) / 35 * 40
    # 60~100: 40~10 线性递减
    return 40.0 - (pe - 60) / 40 * 30


def score_pb(pb: float) -> float | None:
    """PB 区间评分。
    0.8~3.5 较合理(100~70)，0.5~0.8 偏低(70~50)，
    <0.5 异常(30)，3.5~8 偏高(70~40)，>8 明显降权(20)，<=0 不参与。
    """
    if pb is None or math.isnan(pb) or pb <= 0:
        return None
    if pb < 0.5:
        return 30.0
    if pb < 0.8:
        # 0.5~0.8: 50~70 线性递增
        return 50.0 + (pb - 0.5) / 0.3 * 20
    if pb <= 3.5:
        # 0.8~3.5: 100~70 线性递减
        return 100.0 - (pb - 0.8) / 2.7 * 30
    if pb <= 8:
        # 3.5~8: 70~40 线性递减
        return 70.0 - (pb - 3.5) / 4.5 * 30
    return 20.0


def score_roe(roe: float) -> float | None:
    """ROE 区间评分。
    10%~25% 较优(80~100)，25%~40% 高分封顶(100)，
    >40% 不额外加分(100)，3%~10% 一般(30~80)，<3% 明显降权(10)，<=0 不参与。
    """
    if roe is None or math.isnan(roe) or roe <= 0:
        return None
    if roe < 3:
        return 10.0
    if roe < 10:
        # 3~10: 30~80 线性递增
        return 30.0 + (roe - 3) / 7 * 50
    if roe <= 25:
        # 10~25: 80~100 线性递增
        return 80.0 + (roe - 10) / 15 * 20
    # >=25: 封顶 100
    return 100.0


def score_growth_rate(value: float) -> float | None:
    """增长率评分（已封顶后的值）。
    >30% 满分(100)，10%~30% 良好(80~100)，
    0%~10% 一般(50~80)，-20%~0% 较差(20~50)，<-20% 最低(0~20)。
    """
    if value is None or math.isnan(value):
        return None
    if value > 30:
        return 100.0
    if value > 10:
        # 10~30: 80~100
        return 80.0 + (value - 10) / 20 * 20
    if value > 0:
        # 0~10: 50~80
        return 50.0 + value / 10 * 30
    if value > -20:
        # -20~0: 20~50
        return 20.0 + (value + 20) / 20 * 30
    # <= -20: 0~20
    return max(0, 20.0 + (value + 20) / 30 * 20)


def score_dividend_yield(dy: float) -> float | None:
    """股息率区间评分。
    2%~6% 较优(80~100)，6%~10% 高股息(60~80)，
    1%~2% 一般(40~80)，0%~1% 偏低(0~40)，>10% 异常(20)，<=0 不参与。
    """
    if dy is None or math.isnan(dy) or dy <= 0:
        return None
    if dy > 10:
        return 20.0
    if dy > 6:
        # 6~10: 80~60 递减
        return 80.0 - (dy - 6) / 4 * 20
    if dy >= 2:
        # 2~6: 80~100 递增
        return 80.0 + (dy - 2) / 4 * 20
    if dy >= 1:
        # 1~2: 40~80 递增
        return 40.0 + (dy - 1) / 1 * 40
    # 0~1: 0~40
    return dy / 1 * 40


def score_factor_by_range(series, factor_name: str) -> pd.Series:
    """按区间评分函数将因子原始值转换为 0~100 分。"""
    scores = pd.Series(float("nan"), index=series.index)
    values = pd.to_numeric(series, errors="coerce")

    # 先对增长率做封顶
    if factor_name in ("revenue_growth", "profit_growth"):
        values = values.apply(lambda v: _clamp_growth(v, factor_name))

    for idx, val in values.items():
        if pd.isna(val) or val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        if factor_name == "pe_ttm":
            s = score_pe_ttm(v)
        elif factor_name == "pb":
            s = score_pb(v)
        elif factor_name == "roe":
            s = score_roe(v)
        elif factor_name in ("revenue_growth", "profit_growth"):
            s = score_growth_rate(v)
        elif factor_name == "dividend_yield":
            s = score_dividend_yield(v)
        else:
            continue

        if s is not None:
            scores.at[idx] = round(s, 2)

    return scores


def is_factor_available(df, factor_name, min_valid_ratio=0.3) -> bool:
    """判断某个因子是否有足够有效数据参与评分。"""
    if factor_name not in df.columns or df.empty:
        return False

    values = pd.to_numeric(df[factor_name], errors="coerce")
    valid_count = values.notna().sum()
    if valid_count <= 0:
        return False

    factor_min_valid_ratio = FACTOR_CONFIG.get(factor_name, {}).get("min_valid_ratio", min_valid_ratio)
    valid_ratio = valid_count / len(df)
    return valid_ratio >= factor_min_valid_ratio


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


def _build_factor_weights(factor_weights=None, pe_weight=None, pb_weight=None) -> dict[str, float]:
    """合并默认因子权重和可选覆盖值。"""
    weights = {
        factor: config["weight"]
        for factor, config in FACTOR_CONFIG.items()
    }

    if factor_weights:
        weights.update(factor_weights)

    # 兼容旧调用参数，不作为新策略默认权重来源。
    if pe_weight is not None:
        weights["pe_ttm"] = pe_weight
    if pb_weight is not None:
        weights["pb"] = pb_weight

    return weights


def _get_category_factors(category: str) -> list[str]:
    """获取某个模块下的因子列表。"""
    return [
        factor
        for factor, config in FACTOR_CONFIG.items()
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

    normalized = _normalize_weights({
        factor: factor_weights.get(factor, FACTOR_CONFIG[factor]["weight"])
        for factor in category_factors
    })

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
    normalized = _normalize_weights({
        category: category_weights.get(category, CATEGORY_WEIGHTS.get(category, 0))
        for category in active_categories
    })

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


def calculate_score(
    df: pd.DataFrame,
    factor_weights: dict[str, float] | None = None,
    category_weights: dict[str, float] | None = None,
    pe_weight: float | None = None,
    pb_weight: float | None = None,
) -> pd.DataFrame:
    """使用 6 因子稳健价值策略计算综合评分。"""
    if df.empty:
        return df.copy()

    result = df.copy()
    weights = _build_factor_weights(factor_weights, pe_weight, pb_weight)
    categories = category_weights or CATEGORY_WEIGHTS
    active_factors = [
        factor
        for factor in FACTOR_CONFIG
        if is_factor_available(result, factor)
    ]
    active_factor_set = set(active_factors)
    inactive_factors = [
        factor
        for factor in FACTOR_CONFIG
        if factor not in active_factor_set
    ]
    active_categories = [
        category
        for category in CATEGORY_WEIGHTS
        if any(factor in active_factor_set for factor in _get_category_factors(category))
    ]
    inactive_categories = [
        category
        for category in CATEGORY_WEIGHTS
        if category not in active_categories
    ]

    for factor, config in FACTOR_CONFIG.items():
        if factor not in result.columns:
            result[factor] = pd.NA
        result[factor] = pd.to_numeric(result[factor], errors="coerce")
        if factor in active_factor_set:
            # 使用区间评分替代原来的相对排名评分
            result[f"{factor}_score"] = score_factor_by_range(result[factor], factor)
        else:
            result[f"{factor}_score"] = float("nan")

    for category in CATEGORY_WEIGHTS:
        result[f"{category}_score"] = _calculate_category_score(
            result,
            category,
            weights,
            active_factor_set,
        )

    result["active_categories"] = ",".join(active_categories)
    result["inactive_categories"] = ",".join(inactive_categories)
    result["active_factors"] = ",".join(active_factors)
    result["inactive_factors"] = ",".join(inactive_factors)
    result["raw_score"] = _calculate_raw_score(result, active_categories, categories)

    risk_result = result.apply(calculate_risk, axis=1)
    result["risk_tags"] = risk_result.apply(lambda item: item[0])
    result["risk_penalty"] = risk_result.apply(lambda item: item[1])
    result["raw_score"] = result["raw_score"].round(2)
    result["final_score"] = (result["raw_score"] - result["risk_penalty"]).clip(0, 100).round(2)

    return result.sort_values(by="final_score", ascending=False)


if __name__ == "__main__":
    df = get_latest_strategy_data()
    result = calculate_score(df)

    if result.empty:
        print("暂无估值数据，请先运行 python main.py 抓取并写入数据。")
        raise SystemExit(0)

    columns = [
        "bs_code",
        "name",
        "close_price",
        "pe_ttm",
        "pb",
        "roe",
        "revenue_growth",
        "profit_growth",
        "dividend_yield",
        "raw_score",
        "risk_penalty",
        "final_score",
        "risk_tags",
        "active_categories",
        "inactive_categories",
        "active_factors",
        "inactive_factors",
    ]
    print(result[columns].head(50))
