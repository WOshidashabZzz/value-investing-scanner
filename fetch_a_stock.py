import time
import akshare as ak
import baostock as bs
import pandas as pd


def fetch_stock_pool() -> pd.DataFrame:
    df = pd.read_csv("stock_pool.csv", dtype={"symbol": str})
    print("成功读取股票池")
    print("股票池数量：", len(df))
    return df


def bs_code_to_symbol(bs_code: str) -> str:
    """将 Baostock 代码转换为 AKShare 常用股票代码。"""
    if not bs_code or "." not in bs_code:
        return str(bs_code or "").strip()
    return bs_code.split(".")[1]


def safe_float(value):
    """安全转换 float，空值和异常值返回 None。"""
    if value is None or pd.isna(value):
        return None

    value = str(value).strip().replace(",", "")
    if value in {"", "-", "--", "None", "nan", "NaN"}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_one_stock_valuation_akshare(bs_code: str, trade_date: str) -> pd.DataFrame:
    """优先使用 AKShare 获取单只股票某天估值数据。"""
    symbol = bs_code_to_symbol(bs_code)

    try:
        df = ak.stock_value_em(symbol=symbol)
    except Exception as exc:
        print(f"{bs_code} AKShare 估值查询失败：{exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"{bs_code} AKShare 无估值数据")
        return pd.DataFrame()

    if "数据日期" not in df.columns:
        print(f"{bs_code} AKShare 估值字段缺少 数据日期，columns={df.columns.tolist()}")
        return pd.DataFrame()

    df = df.copy()
    df["数据日期"] = pd.to_datetime(df["数据日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    row_df = df[df["数据日期"] == trade_date]

    if row_df.empty:
        print(f"{bs_code} AKShare 无 {trade_date} 估值数据")
        return pd.DataFrame()

    row = row_df.iloc[-1]
    result = pd.DataFrame([{
        "date": trade_date,
        "code": bs_code,
        "close": safe_float(row.get("当日收盘价")),
        "peTTM": safe_float(row.get("PE(TTM)")),
        "pbMRQ": safe_float(row.get("市净率")),
        "psTTM": safe_float(row.get("市销率")),
        "pcfNcfTTM": safe_float(row.get("市现率")),
    }])

    print(f"{bs_code} AKShare 估值获取成功")
    return result


def fetch_one_stock_valuation_baostock(bs_code: str, trade_date: str) -> pd.DataFrame:
    """备用：使用 Baostock 获取单只股票某天估值数据。"""
    fields = "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM"

    rs = bs.query_history_k_data_plus(
        bs_code,
        fields,
        start_date=trade_date,
        end_date=trade_date,
        frequency="d",
        adjustflag="3"
    )

    if rs.error_code != "0":
        print(f"{bs_code} 查询失败：{rs.error_msg}")
        return pd.DataFrame()

    data_list = []

    while rs.next():
        data_list.append(rs.get_row_data())

    df = pd.DataFrame(data_list, columns=rs.fields)

    if df.empty:
        print(f"{bs_code} 无数据")
    else:
        print(f"{bs_code} 获取成功")

    return df


def fetch_one_stock_valuation(
    bs_code: str,
    trade_date: str,
    use_baostock_fallback: bool = True,
) -> pd.DataFrame:
    """
    获取单只股票某一天的估值数据。
    AKShare 优先，失败或无数据时 Baostock 兜底。
    """
    df = fetch_one_stock_valuation_akshare(bs_code, trade_date)
    if not df.empty:
        return df

    if not use_baostock_fallback:
        print(f"{bs_code} Baostock 备用估值不可用，跳过")
        return pd.DataFrame()

    print(f"{bs_code} 尝试使用 Baostock 备用估值数据")
    return fetch_one_stock_valuation_baostock(bs_code, trade_date)


def fetch_stock_valuation(trade_date: str) -> pd.DataFrame:
    """
    获取股票池中所有股票某一天的估值数据。
    """
    stock_pool = fetch_stock_pool()

    lg = bs.login()
    baostock_available = lg.error_code == "0"

    if not baostock_available:
        print(f"Baostock 备用估值登录失败，将只使用 AKShare：{lg.error_msg}")

    all_data = []

    try:
        for _, row in stock_pool.iterrows():
            bs_code = row["bs_code"]

            df = fetch_one_stock_valuation(
                bs_code,
                trade_date,
                use_baostock_fallback=baostock_available,
            )

            if not df.empty:
                all_data.append(df)

            time.sleep(0.2)

    finally:
        if baostock_available:
            bs.logout()

    if not all_data:
        print("没有获取到任何估值数据")
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)

    print("估值数据获取完成")
    print("数据行数：", len(result))
    print("字段列表：", result.columns.tolist())

    return result


if __name__ == "__main__":
    df = fetch_stock_valuation("2026-04-30")
    print(df)
