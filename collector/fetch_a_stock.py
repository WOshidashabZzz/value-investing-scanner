import time

import akshare as ak
import baostock as bs
import pandas as pd

from collector.timeout_utils import run_with_timeout


def fetch_stock_pool(limit: int | None = None) -> pd.DataFrame:
    df = pd.read_csv("data/stock_pool.csv", dtype={"symbol": str, "bs_code": str, "market": str})
    if "board" not in df.columns:
        df["board"] = "main_board"
    df = df[["bs_code", "symbol", "name", "market", "board"]].copy()
    total_count = len(df)

    if limit is not None:
        df = df.head(limit).copy()

    print("成功读取股票池")
    print("当前股票池总数：", total_count)
    print("本次处理数量：", len(df))
    return df


def bs_code_to_symbol(bs_code: str) -> str:
    if not bs_code or "." not in bs_code:
        return str(bs_code or "").strip()
    return bs_code.split(".")[1]


def safe_float(value):
    if value is None or pd.isna(value):
        return None

    value = str(value).strip().replace(",", "")
    if value in {"", "-", "--", "None", "nan", "NaN"}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_first_existing(row: pd.Series, columns: list[str]):
    for column in columns:
        if column in row.index:
            value = row.get(column)
            if value is not None and not pd.isna(value):
                return value
    return None


def fetch_one_stock_valuation_akshare(bs_code: str, trade_date: str) -> pd.DataFrame:
    symbol = bs_code_to_symbol(bs_code)

    try:
        df = ak.stock_value_em(symbol=symbol)
    except Exception as exc:
        print(f"{bs_code} AKShare 估值查询失败：{exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"{bs_code} AKShare 无估值数据")
        return pd.DataFrame()

    date_col = next((col for col in ["数据日期", "日期", "trade_date"] if col in df.columns), None)
    if date_col is None:
        print(f"{bs_code} AKShare 估值字段缺少日期，columns={df.columns.tolist()}")
        return pd.DataFrame()

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    row_df = df[df[date_col] == trade_date]

    if row_df.empty:
        print(f"{bs_code} AKShare 无 {trade_date} 估值数据")
        return pd.DataFrame()

    row = row_df.iloc[-1]
    result = pd.DataFrame([{
        "date": trade_date,
        "code": bs_code,
        "close": safe_float(get_first_existing(row, ["当日收盘价", "收盘价", "close"])),
        "peTTM": safe_float(get_first_existing(row, ["PE(TTM)", "市盈率(TTM)", "peTTM"])),
        "pbMRQ": safe_float(get_first_existing(row, ["市净率", "PB", "pbMRQ"])),
        "psTTM": safe_float(get_first_existing(row, ["市销率", "PS(TTM)", "psTTM"])),
        "pcfNcfTTM": safe_float(get_first_existing(row, ["市现率", "PCF", "pcfNcfTTM"])),
    }])

    print(f"{bs_code} AKShare 估值获取成功")
    return result


def fetch_one_stock_valuation_baostock(bs_code: str, trade_date: str) -> pd.DataFrame:
    fields = "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM"

    try:
        result = bs.query_history_k_data_plus(
            bs_code,
            fields,
            start_date=trade_date,
            end_date=trade_date,
            frequency="d",
            adjustflag="3",
        )
    except Exception as exc:
        print(f"{bs_code} Baostock 估值查询异常：{exc}")
        return pd.DataFrame()

    if result.error_code != "0":
        print(f"{bs_code} Baostock 估值查询失败：{result.error_msg}")
        return pd.DataFrame()

    rows = []
    while result.next():
        rows.append(result.get_row_data())

    df = pd.DataFrame(rows, columns=result.fields)
    if df.empty:
        print(f"{bs_code} Baostock 无估值数据")
    else:
        print(f"{bs_code} Baostock 估值获取成功")
    return df


def fetch_one_stock_valuation(
    bs_code: str,
    trade_date: str,
    use_baostock_fallback: bool = True,
) -> pd.DataFrame:
    df = fetch_one_stock_valuation_akshare(bs_code, trade_date)
    if not df.empty:
        return df

    if not use_baostock_fallback:
        print(f"{bs_code} Baostock 备用估值不可用，跳过")
        return pd.DataFrame()

    print(f"{bs_code} 尝试使用 Baostock 备用估值数据")
    return fetch_one_stock_valuation_baostock(bs_code, trade_date)


def fetch_stock_valuation(
    trade_date: str,
    stock_pool: pd.DataFrame | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    if stock_pool is None:
        stock_pool = fetch_stock_pool(limit=limit)
    elif limit is not None:
        stock_pool = stock_pool.head(limit).copy()

    login = bs.login()
    baostock_available = login.error_code == "0"
    if not baostock_available:
        print(f"Baostock 备用估值登录失败，将只使用 AKShare：{login.error_msg}")

    all_data = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    try:
        for _, row in stock_pool.iterrows():
            bs_code = str(row.get("bs_code", "")).strip()
            name = str(row.get("name", "")).strip()

            if not bs_code:
                skipped_count += 1
                print(f"估值跳过：bs_code=- name={name or '-'} 原因=缺少代码")
                continue

            try:
                completed, value = run_with_timeout(
                    fetch_one_stock_valuation,
                    30,
                    bs_code,
                    trade_date,
                    use_baostock_fallback=baostock_available,
                )
                if not completed:
                    failed_count += 1
                    print(f"估值失败：bs_code={bs_code} name={name or '-'} 原因={value}")
                    continue

                df = value
                if df.empty:
                    failed_count += 1
                    print(f"估值失败：bs_code={bs_code} name={name or '-'} 原因=无可用估值数据")
                else:
                    all_data.append(df)
                    success_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"估值异常：bs_code={bs_code} name={name or '-'} 原因={exc}")

            time.sleep(0.2)
    finally:
        if baostock_available:
            bs.logout()

    if not all_data:
        print("没有获取到任何估值数据")
        print(f"估值采集完成，成功 {success_count} 只，失败 {failed_count} 只，跳过 {skipped_count} 只")
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    print("估值数据获取完成")
    print("股票池数量：", len(stock_pool))
    print("估值成功数量：", success_count)
    print("估值失败数量：", failed_count)
    print("估值跳过数量：", skipped_count)
    print("估值数据行数：", len(result))
    return result


if __name__ == "__main__":
    df = fetch_stock_valuation("2026-04-30")
    print(df)
