import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from api.stock_utils import detect_board, map_sector_by_name


def safe_float(value):
    if value is None or pd.isna(value):
        return None

    value = str(value).strip()
    if value in ["", "-", "--", "None", "nan", "NaN"]:
        return None

    try:
        return float(value)
    except Exception:
        return None


def save_stock_basic_to_mysql(stock_pool_df: pd.DataFrame):
    engine = get_engine()
    saved_count = 0
    skipped_count = 0
    failed_count = 0

    with engine.begin() as conn:
        for _, row in stock_pool_df.iterrows():
            try:
                bs_code = str(row.get("bs_code", "")).strip()
                symbol = str(row.get("symbol", "")).strip()
                name = str(row.get("name", "")).strip()
                market = str(row.get("market", "")).strip()
                board = str(row.get("board", "")).strip() or detect_board(bs_code, symbol=symbol, market=market)
                sector = map_sector_by_name(name)

                if not bs_code or not symbol:
                    skipped_count += 1
                    print(f"stock_basic 跳过：bs_code={bs_code or '-'} name={name or '-'} 原因=缺少代码")
                    continue

                conn.execute(
                    text("""
                        INSERT INTO stock_basic (
                            bs_code,
                            symbol,
                            name,
                            market,
                            board,
                            sector
                        )
                        VALUES (
                            :bs_code,
                            :symbol,
                            :name,
                            :market,
                            :board,
                            :sector
                        )
                        ON DUPLICATE KEY UPDATE
                            symbol = VALUES(symbol),
                            name = VALUES(name),
                            market = VALUES(market),
                            board = VALUES(board),
                            sector = VALUES(sector),
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "bs_code": bs_code,
                        "symbol": symbol,
                        "name": name,
                        "market": market,
                        "board": board,
                        "sector": sector,
                    },
                )
                saved_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"stock_basic 入库失败：bs_code={row.get('bs_code', '-')} name={row.get('name', '-')} 原因={exc}")

    print(f"股票基础信息保存完成，成功 {saved_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 条")
    return {"saved": saved_count, "skipped": skipped_count, "failed": failed_count}


def save_stock_valuation_to_mysql(valuation_df: pd.DataFrame, data_version: str = "latest"):
    if valuation_df.empty:
        print("估值数据为空，不执行入库")
        return {"saved": 0, "skipped": 0, "failed": 0}

    engine = get_engine()
    saved_count = 0
    skipped_count = 0
    failed_count = 0
    missing_stock_count = 0

    with engine.begin() as conn:
        for _, row in valuation_df.iterrows():
            try:
                bs_code = str(row.get("code", "")).strip()

                if not bs_code:
                    skipped_count += 1
                    print("stock_valuation 跳过：bs_code=- 原因=缺少代码")
                    continue

                stock = conn.execute(
                    text("""
                        SELECT id
                        FROM stock_basic
                        WHERE bs_code = :bs_code
                    """),
                    {"bs_code": bs_code},
                ).fetchone()

                if stock is None:
                    missing_stock_count += 1
                    skipped_count += 1
                    print(f"stock_valuation 跳过：bs_code={bs_code} 原因=stock_basic 中不存在")
                    continue

                conn.execute(
                    text("""
                        INSERT INTO stock_valuation (
                            stock_id,
                            trade_date,
                            close_price,
                            pe_ttm,
                            pb,
                            ps_ttm,
                            pcf_ncf_ttm,
                            data_version
                        )
                        VALUES (
                            :stock_id,
                            :trade_date,
                            :close_price,
                            :pe_ttm,
                            :pb,
                            :ps_ttm,
                            :pcf_ncf_ttm,
                            :data_version
                        )
                        ON DUPLICATE KEY UPDATE
                            close_price = VALUES(close_price),
                            pe_ttm = VALUES(pe_ttm),
                            pb = VALUES(pb),
                            ps_ttm = VALUES(ps_ttm),
                            pcf_ncf_ttm = VALUES(pcf_ncf_ttm),
                            data_version = VALUES(data_version)
                    """),
                    {
                        "stock_id": stock[0],
                        "trade_date": row.get("date"),
                        "close_price": safe_float(row.get("close")),
                        "pe_ttm": safe_float(row.get("peTTM")),
                        "pb": safe_float(row.get("pbMRQ")),
                        "ps_ttm": safe_float(row.get("psTTM")),
                        "pcf_ncf_ttm": safe_float(row.get("pcfNcfTTM")),
                        "data_version": data_version,
                    },
                )
                saved_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"stock_valuation 入库失败：bs_code={row.get('code', '-')} 原因={exc}")

    print(f"估值数据保存完成，成功 {saved_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 条")
    print(f"未找到基础信息的股票数量：{missing_stock_count}")
    return {"saved": saved_count, "skipped": skipped_count, "failed": failed_count}


def save_stock_financial_to_mysql(financial_df: pd.DataFrame):
    """将股票财务指标保存到 stock_financial 表。"""
    if financial_df.empty:
        print("财务数据为空，不执行入库")
        return {"saved": 0, "skipped": 0, "failed": 0}

    engine = get_engine()
    saved_count = 0
    skipped_count = 0
    failed_count = 0

    with engine.begin() as conn:
        for _, row in financial_df.iterrows():
            try:
                bs_code = str(row.get("bs_code", "")).strip()
                report_date = str(row.get("report_date", "")).strip()

                if not bs_code or not report_date or report_date in ["None", "nan", "NaN"]:
                    skipped_count += 1
                    print(f"stock_financial 跳过：bs_code={bs_code or '-'} 原因=缺少代码或报告期")
                    continue

                stock = conn.execute(
                    text("""
                        SELECT id
                        FROM stock_basic
                        WHERE bs_code = :bs_code
                    """),
                    {"bs_code": bs_code},
                ).fetchone()

                if stock is None:
                    skipped_count += 1
                    print(f"stock_financial 跳过：bs_code={bs_code} 原因=stock_basic 中不存在")
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
                    },
                )
                saved_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"stock_financial 入库失败：bs_code={row.get('bs_code', '-')} 原因={exc}")

    print(f"财务数据保存完成，成功 {saved_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 条")
    return {"saved": saved_count, "skipped": skipped_count, "failed": failed_count}
