import pandas as pd


def _safe_float(value):
    """Convert empty and abnormal values to None."""
    if value is None or pd.isna(value):
        return None

    if isinstance(value, str):
        value = value.strip()
        if value in {"", "-", "None", "nan", "NaN"}:
            return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_risk(row) -> tuple[str, float]:
    """Generate risk tags without penalizing missing factor values."""
    pe_ttm = _safe_float(row.get("pe_ttm"))
    pb = _safe_float(row.get("pb"))
    roe = _safe_float(row.get("roe"))
    revenue_growth = _safe_float(row.get("revenue_growth"))
    profit_growth = _safe_float(row.get("profit_growth"))
    dividend_yield = _safe_float(row.get("dividend_yield"))

    tags = []
    penalty = 0.0

    if pe_ttm is not None and pe_ttm <= 0:
        tags.append("PE异常")
        penalty += 20

    if pe_ttm is not None and 0 < pe_ttm < 5:
        tags.append("PE过低")
        penalty += 5

    if pb is not None and 0 < pb < 0.5:
        tags.append("PB过低")
        penalty += 5

    if (
        pe_ttm is not None
        and pb is not None
        and roe is not None
        and 0 < pe_ttm < 8
        and 0 < pb < 0.8
        and roe < 8
    ):
        tags.append("可能价值陷阱")
        penalty += 15

    if roe is not None:
        if roe < 0:
            tags.append("ROE为负")
            penalty += 15
        elif roe < 3:
            tags.append("ROE明显偏低")
            penalty += 10
        elif roe < 6:
            tags.append("ROE偏低")
            penalty += 5

    if profit_growth is not None and profit_growth < 0:
        tags.append("利润下滑")
        penalty += 10

    if revenue_growth is not None and revenue_growth < 0:
        tags.append("营收下滑")
        penalty += 8

    if dividend_yield is not None and dividend_yield > 10:
        tags.append("股息率异常偏高")
        penalty += 5

    if not tags:
        tags.append("暂无明显风险")

    return "、".join(tags), float(penalty)
