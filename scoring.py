import pandas as pd
from sqlalchemy import text

from db import get_engine
from factor_config import CATEGORY_WEIGHTS, FACTOR_CONFIG
from risk import calculate_risk


def get_latest_strategy_data(board: str | None = "main_board", market: str | None = None) -> pd.DataFrame:
    """读取最新交易日估值数据，并关联每只股票最新一期财务数据。"""
    engine = get_engine()

    sql = text("""
        SELECT
            b.bs_code,
            b.symbol,
            b.name,
            b.market,
            b.board,
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
        WHERE v.trade_date = (
            SELECT MAX(trade_date)
            FROM stock_valuation
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

    sql_text = sql.text
    if filters:
        sql_text = f"{sql_text}\n        AND {' AND '.join(filters)}"

    return pd.read_sql(text(sql_text), engine, params=params)


def get_latest_valuation_data() -> pd.DataFrame:
    """兼容旧代码：返回最新策略数据。"""
    return get_latest_strategy_data()


def score_factor_series(series, direction: str) -> pd.Series:
    """按因子方向将原始数值转换为 0~100 分。"""
    values = pd.to_numeric(series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA)
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
            result[f"{factor}_score"] = score_factor_series(result[factor], config["direction"])
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
