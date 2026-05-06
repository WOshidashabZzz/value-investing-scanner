from fetch_a_stock import fetch_stock_pool, fetch_stock_valuation
from fetch_financial import fetch_stock_financial
from save_to_mysql import (
    save_stock_basic_to_mysql,
    save_stock_financial_to_mysql,
    save_stock_valuation_to_mysql,
)


def main():
    trade_date = "2026-04-30"

    stock_pool_df = fetch_stock_pool()
    save_stock_basic_to_mysql(stock_pool_df)

    valuation_df = fetch_stock_valuation(trade_date)
    save_stock_valuation_to_mysql(valuation_df)

    financial_df = fetch_stock_financial()
    save_stock_financial_to_mysql(financial_df)


if __name__ == "__main__":
    main()
