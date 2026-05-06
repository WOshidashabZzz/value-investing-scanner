import time
import baostock as bs
import pandas as pd


def fetch_stock_pool() -> pd.DataFrame:
    df = pd.read_csv("stock_pool.csv", dtype={"symbol": str})
    print("成功读取股票池")
    print("股票池数量：", len(df))
    return df


def fetch_one_stock_valuation(bs_code: str, trade_date: str) -> pd.DataFrame:
    """
    获取单只股票某一天的估值数据。
    trade_date 格式：YYYY-MM-DD，例如 2026-04-30
    """
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


def fetch_stock_valuation(trade_date: str) -> pd.DataFrame:
    """
    获取股票池中所有股票某一天的估值数据。
    """
    stock_pool = fetch_stock_pool()

    lg = bs.login()

    if lg.error_code != "0":
        raise RuntimeError(f"Baostock 登录失败：{lg.error_msg}")

    all_data = []

    try:
        for _, row in stock_pool.iterrows():
            bs_code = row["bs_code"]

            df = fetch_one_stock_valuation(bs_code, trade_date)

            if not df.empty:
                all_data.append(df)

            time.sleep(0.2)

    finally:
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