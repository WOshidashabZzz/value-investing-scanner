"""
股票数据 staging 校验模块。

在数据从 staging 提升为 latest 之前，对 staging 版本的数据进行质量检查。
校验失败则回滚 staging 数据，不影响当前 latest 版本。
"""

import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from api.scoring import calculate_score

# 最小股票数量阈值（沪深主板通常 ~3000+）
MIN_STOCK_COUNT = 2500

# 核心字段列表（必须存在且非空比例 > 50%）
REQUIRED_FIELDS = ["bs_code", "name", "pe_ttm", "pb", "trade_date"]

# 综合评分相关字段
SCORE_FIELDS = ["final_score"]

# 可选字段列表（建议有数据）
OPTIONAL_FIELDS = ["roe", "close_price"]


def _count_staging_stocks(trade_date: str) -> int:
    """统计 staging 版本中指定交易日的股票数量。"""
    engine = get_engine()
    sql = text("""
        SELECT COUNT(*) AS cnt
        FROM stock_valuation v
        JOIN stock_basic b ON b.id = v.stock_id
        WHERE v.data_version = 'staging'
          AND v.trade_date = :trade_date
    """)
    df = pd.read_sql(sql, engine, params={"trade_date": trade_date})
    return int(df.iloc[0]["cnt"]) if not df.empty else 0


def _check_required_fields(trade_date: str) -> list[str]:
    """检查核心字段是否都存在且非空比例 > 50%。"""
    engine = get_engine()
    errors = []
    field_checks = []

    for field in REQUIRED_FIELDS:
        if field == "bs_code":
            field_checks.append(
                f"COUNT(b.{field}) AS cnt_{field}"
            )
        elif field in ("name",):
            field_checks.append(
                f"COUNT(b.{field}) AS cnt_{field}"
            )
        elif field == "trade_date":
            field_checks.append(
                f"COUNT(v.{field}) AS cnt_{field}"
            )
        else:
            field_checks.append(
                f"SUM(CASE WHEN v.{field} IS NOT NULL THEN 1 ELSE 0 END) AS cnt_{field}"
            )

    sql_str = f"""
        SELECT
            COUNT(*) AS total,
            {', '.join(field_checks)}
        FROM stock_valuation v
        JOIN stock_basic b ON b.id = v.stock_id
        WHERE v.data_version = 'staging'
          AND v.trade_date = :trade_date
    """
    df = pd.read_sql(text(sql_str), engine, params={"trade_date": trade_date})

    if df.empty:
        return ["无法读取 staging 数据"]

    total = int(df.iloc[0]["total"])

    for field in REQUIRED_FIELDS:
        cnt = int(df.iloc[0][f"cnt_{field}"])
        ratio = cnt / total if total > 0 else 0
        if ratio < 0.5:
            errors.append(
                f"核心字段 '{field}' 非空比例过低: {ratio:.1%} ({cnt}/{total})"
            )

    return errors


def _check_score_available(trade_date: str) -> list[str]:
    """用 staging 数据运行评分引擎，检查 final_score 是否全空。"""
    engine = get_engine()
    errors = []

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
        WHERE v.data_version = 'staging'
          AND v.trade_date = :trade_date
    """)

    df = pd.read_sql(sql, engine, params={"trade_date": trade_date})

    if df.empty:
        return ["staging 数据为空，无法评分"]

    try:
        scored = calculate_score(df)
        if scored.empty:
            return ["评分结果为空"]

        if scored["final_score"].isna().all():
            return ["所有股票的 final_score 均为空，评分引擎无法计算有效分数"]

    except Exception as exc:
        return [f"评分引擎运行异常: {exc}"]

    return errors


def _check_trade_date_consistency(trade_date: str) -> list[str]:
    """检查 staging 数据中的 trade_date 是否全部等于预期日期。"""
    engine = get_engine()
    errors = []

    sql = text("""
        SELECT DISTINCT trade_date
        FROM stock_valuation
        WHERE data_version = 'staging'
          AND trade_date != :trade_date
        LIMIT 10
    """)
    df = pd.read_sql(sql, engine, params={"trade_date": trade_date})

    if not df.empty:
        unexpected_dates = df["trade_date"].tolist()
        errors.append(
            f"staging 数据中存在非预期的交易日: {unexpected_dates}"
        )

    return errors


def validate_staging_data(trade_date: str) -> tuple[bool, list[str]]:
    """
    校验 staging 版本的估值数据。

    校验规则：
    1. 股票数量 >= 2500
    2. 核心字段（bs_code, name, pe_ttm, pb, trade_date）非空比例 > 50%
    3. trade_date 一致性检查
    4. 评分引擎可用性检查（final_score 不能全空）

    Args:
        trade_date: 预期交易日字符串，如 "2026-05-07"

    Returns:
        (passed, errors): passed=True 表示校验通过，errors 列出所有错误
    """
    all_errors = []

    # 规则1: 股票数量检查
    stock_count = _count_staging_stocks(trade_date)
    if stock_count < MIN_STOCK_COUNT:
        all_errors.append(
            f"股票数量不足: 当前 {stock_count}，要求 >= {MIN_STOCK_COUNT}"
        )
    else:
        print(f"✅ 股票数量检查通过: {stock_count}")

    # 规则2: 核心字段检查
    field_errors = _check_required_fields(trade_date)
    all_errors.extend(field_errors)
    if not field_errors:
        print("✅ 核心字段检查通过")

    # 规则3: trade_date 一致性
    date_errors = _check_trade_date_consistency(trade_date)
    all_errors.extend(date_errors)
    if not date_errors:
        print("✅ 交易日一致性检查通过")

    # 规则4: 评分可用性检查
    score_errors = _check_score_available(trade_date)
    all_errors.extend(score_errors)
    if not score_errors:
        print("✅ 评分引擎可用性检查通过")

    passed = len(all_errors) == 0

    if passed:
        print("🎉 所有校验规则通过，可以切换 staging → latest")
    else:
        print("❌ 校验失败:")
        for err in all_errors:
            print(f"   - {err}")

    return passed, all_errors
