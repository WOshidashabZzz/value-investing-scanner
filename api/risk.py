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
    """
    增强版风险标签生成。
    检测 PE 异常/过低/过高、PB 异常、ROE 偏低、增长异常、股息率异常、利润波动大等。
    """
    pe_ttm = _safe_float(row.get("pe_ttm"))
    pb = _safe_float(row.get("pb"))
    roe = _safe_float(row.get("roe"))
    revenue_growth = _safe_float(row.get("revenue_growth"))
    profit_growth = _safe_float(row.get("profit_growth"))
    dividend_yield = _safe_float(row.get("dividend_yield"))

    tags = []
    penalty = 0.0

    # --- PE 风险 ---
    if pe_ttm is not None and pe_ttm <= 0:
        tags.append("PE异常")
        penalty += 20
    elif pe_ttm is not None and pe_ttm < 3:
        tags.append("PE过低")
        penalty += 10
    elif pe_ttm is not None and pe_ttm > 60:
        tags.append("PE过高")
        penalty += 8

    # --- PB 风险 ---
    if pb is not None and 0 < pb < 0.5:
        tags.append("PB异常")
        penalty += 10
    elif pb is not None and pb > 8:
        tags.append("PB过高")
        penalty += 5

    # --- 可能价值陷阱（低PE+低PB+低ROE） ---
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

    # --- ROE 风险 ---
    if roe is not None:
        if roe < 0:
            tags.append("ROE为负")
            penalty += 15
        elif roe < 3:
            tags.append("ROE偏低")
            penalty += 10
        elif roe < 6:
            tags.append("ROE偏低")
            penalty += 5

    # --- 增长率风险 ---
    if revenue_growth is not None:
        if revenue_growth > 100:
            tags.append("增长异常")
            penalty += 5
        elif revenue_growth < -50:
            tags.append("营收大幅下滑")
            penalty += 10
        elif revenue_growth < 0:
            tags.append("营收下滑")
            penalty += 8

    if profit_growth is not None:
        if profit_growth > 150:
            tags.append("增长异常")
            penalty += 5
        elif profit_growth < -100:
            tags.append("利润大幅下滑")
            penalty += 10
        elif profit_growth < 0:
            tags.append("利润下滑")
            penalty += 10

    # --- 利润波动大（高增长但低ROE，可能是一次性利润） ---
    if (
        profit_growth is not None
        and profit_growth > 100
        and roe is not None
        and roe < 5
    ):
        if "利润波动大" not in tags:
            tags.append("利润波动大")
        penalty += 8

    # --- 股息率风险 ---
    if dividend_yield is not None:
        if dividend_yield > 10:
            tags.append("股息率异常偏高")
            penalty += 8
        elif dividend_yield > 6:
            tags.append("高股息")
            penalty += 2

    if not tags:
        tags.append("暂无明显风险")

    return "、".join(tags), float(penalty)
