import pandas as pd
from sqlalchemy import text

from db import get_engine


def screen_low_pe_stocks(
    max_pe_ttm: float = 15,
    max_pb: float = 2,
    limit: int = 50
) -> pd.DataFrame:
    engine = get_engine()

    sql = text("""
        SELECT
            b.bs_code,
            b.symbol,
            b.name,
            b.market,
            v.trade_date,
            v.close_price,
            v.pe_ttm,
            v.pb,
            v.ps_ttm,
            v.pcf_ncf_ttm
        FROM stock_basic b
        JOIN stock_valuation v ON b.id = v.stock_id
        WHERE v.trade_date = (
            SELECT MAX(trade_date)
            FROM stock_valuation
        )
          AND v.pe_ttm IS NOT NULL
          AND v.pe_ttm > 0
          AND v.pe_ttm < :max_pe_ttm
          AND v.pb IS NOT NULL
          AND v.pb > 0
          AND v.pb < :max_pb
        ORDER BY v.pe_ttm ASC
        LIMIT :limit_num
    """)

    df = pd.read_sql(
        sql,
        engine,
        params={
            "max_pe_ttm": max_pe_ttm,
            "max_pb": max_pb,
            "limit_num": limit
        }
    )

    return df


if __name__ == "__main__":
    result = screen_low_pe_stocks(
        max_pe_ttm=15,
        max_pb=2,
        limit=50
    )

    print(result)