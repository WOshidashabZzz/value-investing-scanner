def detect_board(bs_code: str, symbol: str | None = None, market: str | None = None) -> str:
    """Identify the stock board used by the first-version scoring universe."""
    code = str(bs_code or "").strip().lower()
    stock_symbol = str(symbol or "").strip()
    stock_market = str(market or "").strip().lower()

    if not stock_symbol and "." in code:
        stock_symbol = code.split(".", 1)[1]
    stock_symbol = stock_symbol.zfill(6)[-6:] if stock_symbol else ""

    if code.startswith("bj.") or (stock_market == "bj" and stock_symbol.startswith(("8", "9"))):
        return "bse"

    if code.startswith(("sz.300", "sz.301")):
        return "gem"

    if code.startswith("sh.688"):
        return "star"

    if code.startswith(("sh.600", "sh.601", "sh.603", "sh.605")):
        return "main_board"

    if code.startswith(("sz.000", "sz.001", "sz.002")):
        return "main_board"

    return "unknown"


BOARD_LABELS = {
    "main_board": "沪深主板",
    "gem": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "unknown": "未知",
    "all": "全部已入库",
}


VALID_BOARD_FILTERS = {"main_board", "gem", "star", "bse", "unknown", "all"}
