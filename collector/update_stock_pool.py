import re
from datetime import date

import akshare as ak
import baostock as bs
import pandas as pd

from collector.save_to_mysql import save_stock_basic_to_mysql
from api.stock_utils import detect_board


OUTPUT_COLUMNS = ["bs_code", "symbol", "name", "market", "board"]


def normalize_symbol(value) -> str:
    return re.sub(r"\D", "", str(value or "").strip()).zfill(6)[-6:]


def symbol_to_market(symbol: str) -> str | None:
    if symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if symbol.startswith(("430", "83", "87", "88", "89", "920")):
        return "bj"
    return None


def is_common_a_share(symbol: str, name: str, board: str) -> bool:
    if not re.fullmatch(r"\d{6}", symbol):
        return False

    if board == "unknown":
        return False

    upper_name = str(name or "").upper().strip()
    blocked_tokens = [
        "退",
        "退市",
        "B股",
        "B 股",
        "ETF",
        "指数",
        "可转债",
        "LOF",
        "REIT",
        "基金",
        "债",
        "优先",
        "ST",
    ]
    if any(token in upper_name for token in blocked_tokens):
        return False

    return True


def build_stock_pool(rows: list[dict]) -> pd.DataFrame:
    cleaned = []
    seen = set()

    for row in rows:
        symbol = normalize_symbol(row.get("symbol") or row.get("code"))
        name = str(row.get("name") or "").strip()
        market = row.get("market") or symbol_to_market(symbol)

        bs_code = f"{market}.{symbol}" if market else ""
        board = row.get("board") or detect_board(bs_code, symbol=symbol, market=market)

        if not name or not market or not is_common_a_share(symbol, name, board):
            continue
        if symbol in seen:
            continue

        seen.add(symbol)
        cleaned.append(
            {
                "bs_code": f"{market}.{symbol}",
                "symbol": symbol,
                "name": name,
                "market": market,
                "board": board,
            }
        )

    result = pd.DataFrame(cleaned, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result

    board_order = {"main_board": 0, "gem": 1, "star": 2, "bse": 3, "unknown": 4}
    market_order = {"sh": 0, "sz": 1, "bj": 2}
    result["_board_order"] = result["board"].map(board_order).fillna(99)
    result["_market_order"] = result["market"].map(market_order).fillna(99)
    return (
        result.sort_values(["_board_order", "_market_order", "symbol"])
        .drop(columns=["_board_order", "_market_order"])
        .reset_index(drop=True)
    )


def fetch_stock_pool_akshare() -> pd.DataFrame:
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        raise RuntimeError("AKShare returned an empty stock list")

    code_col = next((col for col in ["code", "代码", "证券代码"] if col in df.columns), None)
    name_col = next((col for col in ["name", "名称", "证券简称"] if col in df.columns), None)
    if code_col is None or name_col is None:
        raise RuntimeError(f"AKShare stock list columns not recognized: {df.columns.tolist()}")

    rows = [
        {
            "symbol": row.get(code_col),
            "name": row.get(name_col),
        }
        for _, row in df.iterrows()
    ]
    return build_stock_pool(rows)


def fetch_stock_pool_baostock() -> pd.DataFrame:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_msg}")

    try:
        result = bs.query_all_stock(day=date.today().isoformat())
        if result.error_code != "0":
            raise RuntimeError(f"Baostock query_all_stock failed: {result.error_msg}")

        rows = []
        while result.next():
            item = dict(zip(result.fields, result.get_row_data()))
            code = str(item.get("code") or "")
            rows.append(
                {
                    "symbol": code.split(".")[-1],
                    "name": item.get("code_name") or item.get("name"),
                    "market": code.split(".")[0] if "." in code else None,
                }
            )
        return build_stock_pool(rows)
    finally:
        bs.logout()


def fetch_stock_pool_online() -> tuple[pd.DataFrame, str]:
    try:
        df = fetch_stock_pool_akshare()
        if not df.empty:
            return df, "AKShare"
        print("AKShare 股票池为空，尝试 Baostock 备用。")
    except Exception as exc:
        print(f"AKShare 股票池获取失败：{exc}")

    df = fetch_stock_pool_baostock()
    return df, "Baostock"


def main():
    full_stock_pool, source = fetch_stock_pool_online()
    if full_stock_pool.empty:
        raise SystemExit("未获取到可用 A 股股票池，已停止。")

    # 只保留沪深主板股票
    stock_pool = full_stock_pool[full_stock_pool["board"] == "main_board"].copy()

    # 保存全量股票池（用于参考）
    full_stock_pool.to_csv("data/full_stock_pool.csv", index=False, encoding="utf-8-sig")
    # 保存主板股票池（用于本项目）
    stock_pool.to_csv("data/stock_pool.csv", index=False, encoding="utf-8-sig")

    print("股票池更新完成")
    print("数据源：", source)
    print("全量识别股票数量：", len(full_stock_pool))
    print("主板数量：", int((full_stock_pool["board"] == "main_board").sum()))
    print("创业板数量：", int((full_stock_pool["board"] == "gem").sum()))
    print("科创板数量：", int((full_stock_pool["board"] == "star").sum()))
    print("北交所数量：", int((full_stock_pool["board"] == "bse").sum()))
    print("未知数量：", int((full_stock_pool["board"] == "unknown").sum()))
    print("本项目默认股票池数量：", len(stock_pool))
    print("full_stock_pool.csv 已生成")
    print("stock_pool.csv 已生成")


if __name__ == "__main__":
    main()

