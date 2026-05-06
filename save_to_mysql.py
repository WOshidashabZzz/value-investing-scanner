import pandas as pd
from sqlalchemy import text

from db import get_engine


def safe_float(value):
    if pd.isna(value):
        return None

    value = str(value).strip()

    if value in ["", "-", "None", "nan", "NaN"]:
        return None

    try:
        return float(value)
    except Exception:
        return None


def save_stock_basic_to_mysql(stock_pool_df: pd.DataFrame):
    engine = get_engine()
    count = 0

    with engine.begin() as conn:
        for _, row in stock_pool_df.iterrows():
            bs_code = str(row.get("bs_code", "")).strip()
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            market = str(row.get("market", "")).strip()

            if not bs_code or not symbol:
                continue

            conn.execute(
                text("""
                    INSERT INTO stock_basic (
                        bs_code,
                        symbol,
                        name,
                        market
                    )
                    VALUES (
                        :bs_code,
                        :symbol,
                        :name,
                        :market
                    )
                    ON DUPLICATE KEY UPDATE
                        symbol = VALUES(symbol),
                        name = VALUES(name),
                        market = VALUES(market),
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "bs_code": bs_code,
                    "symbol": symbol,
                    "name": name,
                    "market": market
                }
            )

            count += 1

    print(f"股票基础信息保存完成，共处理 {count} 条")


def save_stock_valuation_to_mysql(valuation_df: pd.DataFrame):
    if valuation_df.empty:
        print("估值数据为空，不执行入库")
        return

    engine = get_engine()
    count = 0
    missing_stock_count = 0

    with engine.begin() as conn:
        for _, row in valuation_df.iterrows():
            bs_code = str(row.get("code", "")).strip()

            if not bs_code:
                continue

            stock = conn.execute(
                text("""
                    SELECT id
                    FROM stock_basic
                    WHERE bs_code = :bs_code
                """),
                {"bs_code": bs_code}
            ).fetchone()

            if stock is None:
                missing_stock_count += 1
                continue

            stock_id = stock[0]

            conn.execute(
                text("""
                    INSERT INTO stock_valuation (
                        stock_id,
                        trade_date,
                        close_price,
                        pe_ttm,
                        pb,
                        ps_ttm,
                        pcf_ncf_ttm
                    )
                    VALUES (
                        :stock_id,
                        :trade_date,
                        :close_price,
                        :pe_ttm,
                        :pb,
                        :ps_ttm,
                        :pcf_ncf_ttm
                    )
                    ON DUPLICATE KEY UPDATE
                        close_price = VALUES(close_price),
                        pe_ttm = VALUES(pe_ttm),
                        pb = VALUES(pb),
                        ps_ttm = VALUES(ps_ttm),
                        pcf_ncf_ttm = VALUES(pcf_ncf_ttm)
                """),
                {
                    "stock_id": stock_id,
                    "trade_date": row.get("date"),
                    "close_price": safe_float(row.get("close")),
                    "pe_ttm": safe_float(row.get("peTTM")),
                    "pb": safe_float(row.get("pbMRQ")),
                    "ps_ttm": safe_float(row.get("psTTM")),
                    "pcf_ncf_ttm": safe_float(row.get("pcfNcfTTM")),
                }
            )

            count += 1

    print(f"估值数据保存完成，共处理 {count} 条")
    print(f"未找到基础信息的股票数量：{missing_stock_count}")


def save_stock_financial_to_mysql(financial_df: pd.DataFrame):
    """将股票财务指标保存到 stock_financial 表。"""
    if financial_df.empty:
        print("财务数据为空，不执行入库")
        return {"saved": 0, "skipped": 0}

    engine = get_engine()
    saved_count = 0
    skipped_count = 0

    with engine.begin() as conn:
        for _, row in financial_df.iterrows():
            try:
                bs_code = str(row.get("bs_code", "")).strip()
                report_date = str(row.get("report_date", "")).strip()

                if not bs_code or not report_date or report_date in ["None", "nan", "NaN"]:
                    skipped_count += 1
                    continue

                stock = conn.execute(
                    text("""
                        SELECT id
                        FROM stock_basic
                        WHERE bs_code = :bs_code
                    """),
                    {"bs_code": bs_code}
                ).fetchone()

                if stock is None:
                    skipped_count += 1
                    continue

                conn.execute(
                    text("""
                        INSERT INTO stock_financial (
                            stock_id,
                            report_date,
                            roe,
                            revenue_growth,
                            profit_growth,
                            dividend_yield
                        )
                        VALUES (
                            :stock_id,
                            :report_date,
                            :roe,
                            :revenue_growth,
                            :profit_growth,
                            :dividend_yield
                        )
                        ON DUPLICATE KEY UPDATE
                            roe = COALESCE(VALUES(roe), roe),
                            revenue_growth = COALESCE(VALUES(revenue_growth), revenue_growth),
                            profit_growth = COALESCE(VALUES(profit_growth), profit_growth),
                            dividend_yield = COALESCE(VALUES(dividend_yield), dividend_yield),
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "stock_id": stock[0],
                        "report_date": report_date,
                        "roe": safe_float(row.get("roe")),
                        "revenue_growth": safe_float(row.get("revenue_growth")),
                        "profit_growth": safe_float(row.get("profit_growth")),
                        "dividend_yield": safe_float(row.get("dividend_yield")),
                    }
                )

                saved_count += 1
            except Exception as exc:
                skipped_count += 1
                print(f"财务数据入库失败，已跳过：{exc}")

    print(f"财务数据保存完成，成功入库 {saved_count} 条")
    print(f"财务数据跳过数量：{skipped_count}")
    return {"saved": saved_count, "skipped": skipped_count}
