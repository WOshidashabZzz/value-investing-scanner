import time
from datetime import date, timedelta

import akshare as ak
import baostock as bs
import pandas as pd

from collector.fetch_a_stock import bs_code_to_symbol, fetch_stock_pool
from collector.timeout_utils import run_with_timeout


def safe_float(value):
    """安全转换 float，空值和异常值返回 None。"""
    if value is None or pd.isna(value):
        return None

    value = str(value).strip()
    if value in {"", "-", "None", "nan", "NaN"}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ratio_to_percent(value):
    """将 Baostock 常见小数比例转换为百分比数值。"""
    number = safe_float(value)
    if number is None:
        return None
    if abs(number) <= 2:
        return round(number * 100, 4)
    return round(number, 4)


def percent_value(value):
    """读取 AKShare 已经是百分比口径的字段。"""
    number = safe_float(value)
    if number is None:
        return None
    return round(number, 4)


def result_to_df(result) -> pd.DataFrame:
    """把 Baostock 查询结果转换成 DataFrame。"""
    rows = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def get_first_value(row: pd.Series, field_names: list[str]):
    """按候选字段顺序取第一个有效值。"""
    for field in field_names:
        if field in row.index:
            value = safe_float(row.get(field))
            if value is not None:
                return value
    return None


def query_financial_akshare(bs_code: str, years_back: int = 3) -> dict | None:
    """优先使用 AKShare 获取最近一期财务指标。"""
    symbol = bs_code_to_symbol(bs_code)
    start_year = str(date.today().year - years_back)

    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year=start_year)
    except Exception as exc:
        print(f"{bs_code} AKShare 财务数据查询失败：{exc}")
        return None

    if df is None or df.empty:
        print(f"{bs_code} AKShare 无财务数据")
        return None

    print(f"{bs_code} AKShare 财务 columns: {list(df.columns)}")

    if "日期" not in df.columns:
        print(f"{bs_code} AKShare 财务字段缺少 日期")
        return None

    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.sort_values(by="日期", ascending=False, na_position="last")
    row = df.iloc[0]

    report_date = row.get("日期")
    if pd.isna(report_date):
        return None

    roe = percent_value(
        get_first_value(
            row,
            ["净资产收益率(%)", "加权净资产收益率(%)", "净资产报酬率(%)"]
        )
    )
    revenue_growth = percent_value(
        get_first_value(
            row,
            ["主营业务收入增长率(%)", "营业收入增长率(%)", "营业总收入同比增长率(%)"]
        )
    )
    profit_growth = percent_value(
        get_first_value(
            row,
            ["净利润增长率(%)", "归属净利润同比增长率(%)", "扣非净利润同比增长率(%)"]
        )
    )

    if roe is None and revenue_growth is None and profit_growth is None:
        return None

    return {
        "bs_code": bs_code,
        "report_date": report_date.strftime("%Y-%m-%d"),
        "roe": roe,
        "revenue_growth": revenue_growth,
        "profit_growth": profit_growth,
        "dividend_yield": None,
    }


def query_financial_by_quarter(bs_code: str, year: int, quarter: int) -> dict | None:
    """备用：使用 Baostock 查询单只股票某个季度的盈利和成长数据。"""
    profit_rs = bs.query_profit_data(code=bs_code, year=year, quarter=quarter)
    growth_rs = bs.query_growth_data(code=bs_code, year=year, quarter=quarter)

    if profit_rs.error_code != "0":
        print(f"{bs_code} {year}Q{quarter} 盈利数据查询失败：{profit_rs.error_msg}")
    if growth_rs.error_code != "0":
        print(f"{bs_code} {year}Q{quarter} 成长数据查询失败：{growth_rs.error_msg}")

    profit_df = result_to_df(profit_rs)
    growth_df = result_to_df(growth_rs)

    if profit_df.empty and growth_df.empty:
        return None

    profit_row = profit_df.iloc[0] if not profit_df.empty else pd.Series(dtype=object)
    growth_row = growth_df.iloc[0] if not growth_df.empty else pd.Series(dtype=object)

    report_date = None
    for row in (profit_row, growth_row):
        for field in ("statDate", "pubDate"):
            value = str(row.get(field, "")).strip()
            if value:
                report_date = value
                break
        if report_date:
            break

    if not report_date:
        return None

    roe = ratio_to_percent(profit_row.get("roeAvg"))
    profit_growth = ratio_to_percent(get_first_value(growth_row, ["YOYNI", "YOYPNI"]))

    # Baostock 成长接口通常没有稳定的营收同比字段，这里做兼容映射。
    revenue_growth = ratio_to_percent(
        get_first_value(
            growth_row,
            ["YOYRevenue", "YOYMBRevenue", "revenueGrowth", "YOYSales"]
        )
    )

    return {
        "bs_code": bs_code,
        "report_date": report_date,
        "roe": roe,
        "revenue_growth": revenue_growth,
        "profit_growth": profit_growth,
        "dividend_yield": None,
    }


def fetch_latest_close(bs_code: str) -> float | None:
    """查询最近可用收盘价，用于股息率粗略计算。"""
    end_date = date.today()
    start_date = end_date - timedelta(days=240)

    result = bs.query_history_k_data_plus(
        bs_code,
        "date,close",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        frequency="d",
        adjustflag="3",
    )

    if result.error_code != "0":
        return None

    df = result_to_df(result)
    if df.empty:
        return None

    close = safe_float(df.iloc[-1].get("close"))
    if close is None or close <= 0:
        return None
    return close


def fetch_dividend_yield(bs_code: str, year: int) -> float | None:
    """尝试用每股现金分红和最近收盘价计算股息率。"""
    if not hasattr(bs, "query_dividend_data"):
        return None

    result = bs.query_dividend_data(code=bs_code, year=year, yearType="report")
    if result.error_code != "0":
        return None

    df = result_to_df(result)
    if df.empty or "dividCashPsBeforeTax" not in df.columns:
        return None

    cash_values = pd.to_numeric(df["dividCashPsBeforeTax"], errors="coerce").dropna()
    if cash_values.empty:
        return None

    close = fetch_latest_close(bs_code)
    if close is None:
        return None

    return round(float(cash_values.sum()) / close * 100, 4)


def fetch_one_stock_financial(
    bs_code: str,
    years_back: int = 3,
    use_baostock_fallback: bool = True,
) -> dict | None:
    """获取单只股票最近一期财务数据，AKShare 优先，Baostock 兜底。"""
    financial = query_financial_akshare(bs_code, years_back=years_back)
    if financial is not None:
        print(f"{bs_code} AKShare 财务数据获取成功：{financial['report_date']}")
        return financial

    if not use_baostock_fallback:
        print(f"{bs_code} Baostock 备用财务不可用，跳过")
        return None

    print(f"{bs_code} 尝试使用 Baostock 备用财务数据")
    current_year = date.today().year

    for year in range(current_year, current_year - years_back - 1, -1):
        for quarter in (4, 3, 2, 1):
            financial = query_financial_by_quarter(bs_code, year, quarter)
            if financial is None:
                continue

            # 股息率优先级较低，失败时保持 None，不阻塞主流程。
            financial["dividend_yield"] = fetch_dividend_yield(bs_code, year)
            print(f"{bs_code} 财务数据获取成功：{financial['report_date']}")
            return financial

    print(f"{bs_code} 未获取到财务数据")
    return None


def fetch_stock_financial_legacy() -> pd.DataFrame:
    """读取股票池并批量获取最近一期财务数据。"""
    stock_pool = fetch_stock_pool()
    login = bs.login()
    baostock_available = login.error_code == "0"

    if not baostock_available:
        print(f"Baostock 备用财务登录失败，将只使用 AKShare：{login.error_msg}")

    rows = []
    failed_count = 0

    try:
        for _, stock in stock_pool.iterrows():
            bs_code = str(stock.get("bs_code", "")).strip()
            if not bs_code:
                failed_count += 1
                continue

            try:
                financial = fetch_one_stock_financial(
                    bs_code,
                    use_baostock_fallback=baostock_available,
                )
                if financial is None:
                    failed_count += 1
                else:
                    rows.append(financial)
            except Exception as exc:
                failed_count += 1
                print(f"{bs_code} 财务数据获取异常：{exc}")

            time.sleep(0.2)
    finally:
        if baostock_available:
            bs.logout()

    df = pd.DataFrame(
        rows,
        columns=[
            "bs_code",
            "report_date",
            "roe",
            "revenue_growth",
            "profit_growth",
            "dividend_yield",
        ],
    )

    print("财务数据获取完成")
    print("股票池数量：", len(stock_pool))
    print("成功获取财务数据数量：", len(df))
    print("失败/跳过数量：", failed_count)
    return df


def fetch_stock_financial(
    stock_pool: pd.DataFrame | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """读取股票池并批量获取最近一期财务数据。"""
    if stock_pool is None:
        stock_pool = fetch_stock_pool(limit=limit)
    elif limit is not None:
        stock_pool = stock_pool.head(limit).copy()

    login = bs.login()
    baostock_available = login.error_code == "0"

    if not baostock_available:
        print(f"Baostock 备用财务登录失败，将只使用 AKShare：{login.error_msg}")

    rows = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    try:
        for _, stock in stock_pool.iterrows():
            bs_code = str(stock.get("bs_code", "")).strip()
            name = str(stock.get("name", "")).strip()

            if not bs_code:
                skipped_count += 1
                print(f"财务跳过：bs_code=- name={name or '-'} 原因=缺少代码")
                continue

            try:
                completed, value = run_with_timeout(
                    fetch_one_stock_financial,
                    45,
                    bs_code,
                    use_baostock_fallback=baostock_available,
                )
                if not completed:
                    failed_count += 1
                    print(f"财务失败：bs_code={bs_code} name={name or '-'} 原因={value}")
                    continue

                financial = value
                if financial is None:
                    failed_count += 1
                    print(f"财务失败：bs_code={bs_code} name={name or '-'} 原因=无可用财务数据")
                else:
                    rows.append(financial)
                    success_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"财务异常：bs_code={bs_code} name={name or '-'} 原因={exc}")

            time.sleep(0.2)
    finally:
        if baostock_available:
            bs.logout()

    df = pd.DataFrame(
        rows,
        columns=[
            "bs_code",
            "report_date",
            "roe",
            "revenue_growth",
            "profit_growth",
            "dividend_yield",
        ],
    )

    print("财务数据获取完成")
    print("股票池数量：", len(stock_pool))
    print("成功获取财务数据数量：", success_count)
    print("财务失败数量：", failed_count)
    print("财务跳过数量：", skipped_count)
    return df


if __name__ == "__main__":
    print(fetch_stock_financial())
