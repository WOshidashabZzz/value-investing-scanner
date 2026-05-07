import argparse
from pathlib import Path

import pandas as pd

from fetch_a_stock import fetch_stock_pool, fetch_stock_valuation
from fetch_financial import fetch_stock_financial
from save_to_mysql import (
    save_stock_basic_to_mysql,
    save_stock_financial_to_mysql,
    save_stock_valuation_to_mysql,
)
from update_dividend_akshare import main as update_dividend_yield


BOARD_LABELS = {
    "main_board": "沪深主板",
    "gem": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "unknown": "未知",
}


def parse_args():
    parser = argparse.ArgumentParser(description="采集股票池估值、财务和股息率数据。")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理 stock_pool.csv 前 N 只股票；不传则处理全部股票池。",
    )
    return parser.parse_args()


def main(limit: int | None = None):
    if limit is not None and limit <= 0:
        raise SystemExit("--limit 必须是正整数")

    trade_date = "2026-04-30"

    if Path("full_stock_pool.csv").exists():
        full_pool = pd.read_csv("full_stock_pool.csv", dtype={"symbol": str, "bs_code": str, "market": str})
        print("全量识别股票数量：", len(full_pool))
        if "board" in full_pool.columns:
            for board, label in BOARD_LABELS.items():
                print(f"{label}数量：", int((full_pool["board"] == board).sum()))

    stock_pool_df = fetch_stock_pool(limit=limit)
    print("本次使用股票池数量：", len(pd.read_csv("stock_pool.csv", dtype={"symbol": str})))
    print("本次实际处理数量：", len(stock_pool_df))
    print("当前股票池范围：沪深主板")
    save_stock_basic_to_mysql(stock_pool_df)

    valuation_df = fetch_stock_valuation(trade_date, stock_pool=stock_pool_df)
    save_stock_valuation_to_mysql(valuation_df)

    financial_df = fetch_stock_financial(stock_pool=stock_pool_df)
    save_stock_financial_to_mysql(financial_df)

    update_dividend_yield(stock_pool=stock_pool_df)


if __name__ == "__main__":
    args = parse_args()
    main(limit=args.limit)
