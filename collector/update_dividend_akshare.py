import re
import time
from typing import Any

import akshare as ak
import baostock as bs
import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from collector.timeout_utils import run_with_timeout


CASH_DIVIDEND_FIELDS = [
    "派息比例",
    "每股派息",
    "税前分红",
    "现金分红",
    "派息",
    "分红",
]


def bs_code_to_symbol(bs_code: str) -> str:
    """将 Baostock 代码转换为 AKShare 常用股票代码。"""
    if not bs_code or "." not in bs_code:
        return str(bs_code or "").strip()
    return bs_code.split(".")[1]


def safe_float(value: Any) -> float | None:
    """安全转换 float，空值和异常值返回 None。"""
    if value is None or pd.isna(value):
        return None

    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value in {"", "-", "--", "None", "nan", "NaN"}:
            return None
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        value = match.group(0)

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_stock_rows(stock_pool: pd.DataFrame | None = None, limit: int | None = None) -> list[dict]:
    """读取股票基础信息、最新收盘价和最新财务报告期。"""
    engine = get_engine()
    sql = text("""
        SELECT
            b.id AS stock_id,
            b.bs_code,
            b.name,
            v.close_price,
            f.report_date
        FROM stock_basic b
        LEFT JOIN stock_valuation v
            ON b.id = v.stock_id
           AND v.trade_date = (
                SELECT MAX(v2.trade_date)
                FROM stock_valuation v2
                WHERE v2.stock_id = b.id
           )
        LEFT JOIN stock_financial f
            ON b.id = f.stock_id
           AND f.report_date = (
                SELECT MAX(f2.report_date)
                FROM stock_financial f2
                WHERE f2.stock_id = b.id
           )
        ORDER BY b.bs_code
    """)

    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(sql)]

    if stock_pool is not None:
        if limit is not None:
            stock_pool = stock_pool.head(limit).copy()
        allowed_codes = set(stock_pool["bs_code"].astype(str).str.strip())
        rows = [row for row in rows if str(row.get("bs_code", "")).strip() in allowed_codes]
    elif limit is not None:
        rows = rows[:limit]

    return rows


def get_latest_dividend_row(symbol: str) -> pd.Series | None:
    """使用 AKShare 获取最近一次个股现金分红记录。"""
    try:
        df = ak.stock_dividend_cninfo(symbol=symbol)
    except Exception as exc:
        print(f"{symbol} AKShare 分红接口失败：{exc}")
        return None

    if df is None or df.empty:
        print(f"{symbol} 无 AKShare 分红数据")
        return None

    print(f"{symbol} AKShare columns: {list(df.columns)}")

    sort_columns = [
        "实施公告日",
        "公告日期",
        "预案公告日",
        "股权登记日",
        "除权除息日",
        "报告期",
    ]
    for column in sort_columns:
        if column in df.columns:
            sortable = df.copy()
            sortable[column] = pd.to_datetime(sortable[column], errors="coerce")
            sortable = sortable.sort_values(by=column, ascending=False, na_position="last")
            return sortable.iloc[0]

    return df.iloc[0]


def baostock_result_to_df(result) -> pd.DataFrame:
    """把 Baostock 查询结果转换成 DataFrame。"""
    rows = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def extract_cash_dividend_per_share(row: pd.Series) -> float | None:
    """从 AKShare 分红记录中提取每股现金分红。"""
    for field in CASH_DIVIDEND_FIELDS:
        if field not in row.index:
            continue

        value = safe_float(row.get(field))
        if value is None or value <= 0:
            continue

        # 巨潮个股分红接口中的“派息比例”通常是每 10 股派息金额。
        if "比例" in field or field in {"派息", "现金分红", "分红"}:
            return round(value / 10, 6)

        return round(value, 6)

    return None


def extract_akshare_cash_per_share(symbol: str) -> tuple[float | None, str]:
    """优先从 AKShare 获取每股现金分红。"""
    dividend_row = get_latest_dividend_row(symbol)
    if dividend_row is None:
        return None, "AKShare 未获取到分红记录"

    cash_per_share = extract_cash_dividend_per_share(dividend_row)
    if cash_per_share is None:
        return None, "AKShare 无法识别现金分红字段"

    return cash_per_share, "AKShare"


def extract_baostock_cash_per_share(bs_code: str, start_year: int | None = None, years_back: int = 4) -> tuple[float | None, str]:
    """备用：从 Baostock 获取每股现金分红。"""
    if not hasattr(bs, "query_dividend_data"):
        return None, "Baostock 当前版本没有 query_dividend_data"

    if start_year is None:
        start_year = pd.Timestamp.today().year

    for year in range(start_year, start_year - years_back - 1, -1):
        try:
            result = bs.query_dividend_data(code=bs_code, year=year, yearType="report")
        except Exception as exc:
            return None, f"Baostock 分红接口异常：{exc}"

        if result.error_code != "0":
            print(f"{bs_code} Baostock {year} 分红查询失败：{result.error_msg}")
            continue

        df = baostock_result_to_df(result)
        if df.empty:
            continue

        print(f"{bs_code} Baostock columns: {list(df.columns)}")
        if "dividCashPsBeforeTax" not in df.columns:
            continue

        values = pd.to_numeric(df["dividCashPsBeforeTax"], errors="coerce")
        values = values.dropna()
        values = values[values > 0]
        if values.empty:
            continue

        return round(float(values.sum()), 6), f"Baostock {year}"

    return None, "Baostock 未获取到可用现金分红"


def get_cash_dividend_per_share(bs_code: str, close_price: float, report_date) -> tuple[float | None, str]:
    """双数据源获取每股现金分红：AKShare 优先，Baostock 兜底。"""
    symbol = bs_code_to_symbol(bs_code)

    cash_per_share, source = extract_akshare_cash_per_share(symbol)
    if cash_per_share is not None:
        return cash_per_share, source

    print(f"{bs_code} AKShare 跳过原因：{source}，尝试 Baostock 备用数据")
    start_year = getattr(report_date, "year", None)
    cash_per_share, source = extract_baostock_cash_per_share(bs_code, start_year=start_year)
    if cash_per_share is not None:
        return cash_per_share, source

    return None, source


def calculate_dividend_yield(cash_per_share: float, close_price: float) -> float | None:
    """根据每股分红和收盘价计算股息率。"""
    if close_price <= 0 or cash_per_share <= 0:
        return None

    dividend_yield = cash_per_share / close_price * 100
    if dividend_yield < 0:
        return None
    if dividend_yield > 20:
        print(f"股息率异常偏高，已跳过：{dividend_yield:.4f}%")
        return None

    return round(dividend_yield, 4)


def update_dividend_yield(stock_id: int, report_date, dividend_yield: float) -> None:
    """只更新 stock_financial 最新报告期的 dividend_yield。"""
    engine = get_engine()
    sql = text("""
        UPDATE stock_financial
        SET dividend_yield = :dividend_yield,
            updated_at = CURRENT_TIMESTAMP
        WHERE stock_id = :stock_id
          AND report_date = :report_date
    """)

    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "stock_id": stock_id,
                "report_date": report_date,
                "dividend_yield": dividend_yield,
            },
        )


def main(stock_pool: pd.DataFrame | None = None, limit: int | None = None):
    """使用 AKShare 优先、Baostock 备用来更新 dividend_yield。"""
    stocks = fetch_stock_rows(stock_pool=stock_pool, limit=limit)
    total_count = len(stocks)
    fetched_count = 0
    akshare_count = 0
    baostock_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    print("总股票数量：", total_count)

    login = bs.login()
    if login.error_code != "0":
        print(f"Baostock 备用数据登录失败：{login.error_msg}")

    try:
        for stock in stocks:
            bs_code = stock["bs_code"]
            name = stock["name"]
            close_price = safe_float(stock.get("close_price"))
            report_date = stock.get("report_date")

            try:
                if report_date is None:
                    skipped_count += 1
                    print(f"{bs_code} {name} 跳过：stock_financial 中没有记录")
                    continue

                if close_price is None or close_price <= 0:
                    skipped_count += 1
                    print(f"{bs_code} {name} 跳过：close_price 缺失或无效")
                    continue

                completed, value = run_with_timeout(
                    get_cash_dividend_per_share,
                    30,
                    bs_code,
                    close_price,
                    report_date,
                )
                if not completed:
                    failed_count += 1
                    print(f"{bs_code} {name} 股息率更新失败：{value}")
                    continue

                cash_per_share, source = value
                if cash_per_share is None:
                    skipped_count += 1
                    print(f"{bs_code} {name} 跳过：{source}")
                    continue

                fetched_count += 1
                if source.startswith("AKShare"):
                    akshare_count += 1
                elif source.startswith("Baostock"):
                    baostock_count += 1

                dividend_yield = calculate_dividend_yield(cash_per_share, close_price)
                if dividend_yield is None:
                    skipped_count += 1
                    print(f"{bs_code} {name} 跳过：股息率无效")
                    continue

                update_dividend_yield(stock["stock_id"], report_date, dividend_yield)
                updated_count += 1
                print(f"{bs_code} {name} {source} dividend_yield={dividend_yield}%")
            except Exception as exc:
                failed_count += 1
                print(f"{bs_code} {name} 更新失败：{exc}")
            time.sleep(0.2)
    finally:
        if login.error_code == "0":
            bs.logout()

    print("双数据源股息率更新完成")
    print("总股票数量：", total_count)
    print("成功获取分红数据数量：", fetched_count)
    print("AKShare 成功数量：", akshare_count)
    print("Baostock 备用成功数量：", baostock_count)
    print("成功更新 dividend_yield 数量：", updated_count)
    print("跳过数量：", skipped_count)
    print("失败数量：", failed_count)


if __name__ == "__main__":
    main()
