import baostock as bs
import pandas as pd


def result_to_df(result):
    """把 Baostock 查询结果安全转换成 DataFrame。"""
    rows = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def print_result(title, result):
    """打印接口状态、字段名和前几行数据。"""
    print(f"\n=== {title} ===")
    print("error_code:", result.error_code)
    print("error_msg:", result.error_msg)
    print("fields:", result.fields)

    df = result_to_df(result)
    if df.empty:
        print("暂无数据")
    else:
        print(df.head())


def main():
    """测试 Baostock 是否能获取 ROE、成长和分红相关数据。"""
    code = "sh.600519"
    year = 2025
    quarter = 4

    login = bs.login()
    print("login error_code:", login.error_code)
    print("login error_msg:", login.error_msg)

    if login.error_code != "0":
        return

    try:
        profit = bs.query_profit_data(code=code, year=year, quarter=quarter)
        print_result("盈利能力数据：重点查看 roeAvg，可作为 ROE", profit)

        growth = bs.query_growth_data(code=code, year=year, quarter=quarter)
        print_result("成长能力数据：重点查看 YOYNI / YOYPNI，营收增长率可能无法直接获得", growth)

        if hasattr(bs, "query_dividend_data"):
            dividend = bs.query_dividend_data(code=code, year=year, yearType="report")
            print_result("分红数据：Baostock 可能不直接提供股息率，需要后续结合股价计算", dividend)
        else:
            print("\n=== 分红数据 ===")
            print("当前 baostock 版本没有 query_dividend_data，dividend_yield 第一版可先用 None 占位。")

        # 指标映射建议：
        # ROE：优先使用 query_profit_data 返回的 roeAvg。
        # 净利润增长率：优先使用 query_growth_data 返回的 YOYNI 或 YOYPNI。
        # 营收增长率：Baostock 成长接口未必直接提供，第一版可用 None 占位。
        # 股息率：Baostock 分红接口通常需要结合分红金额和股价计算，第一版可用 None 占位。
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
