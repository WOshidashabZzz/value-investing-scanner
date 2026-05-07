from fetch_financial import fetch_stock_financial
from save_to_mysql import save_stock_financial_to_mysql
from update_dividend_akshare import main as update_dividend_yield


def main():
    """只更新 stock_financial 财务指标表。"""
    financial_df = fetch_stock_financial()
    result = save_stock_financial_to_mysql(financial_df)
    update_dividend_yield()

    print("财务数据更新任务完成")
    print("成功获取财务数据数量：", len(financial_df))
    print("成功入库数量：", result["saved"])
    print("失败/跳过数量：", result["skipped"])


if __name__ == "__main__":
    main()
