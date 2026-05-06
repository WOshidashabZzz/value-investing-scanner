import pandas as pd
from sqlalchemy import text

from db import get_engine


def score_pe(pe_ttm):
    """
    PE_TTM 越低越好，但 PE <= 0 直接给 0 分。
    """
    if pe_ttm is None or pe_ttm <= 0:
        return 0
    elif pe_ttm <= 8:
        return 95
    elif pe_ttm <= 15:
        return 85
    elif pe_ttm <= 25:
        return 65
    elif pe_ttm <= 40:
        return 40
    else:
        return 20


def score_pb(pb):
    """
    PB 越低越好。
    """
    if pb is None or pb <= 0:
        return 0
    elif pb <= 1:
        return 90
    elif pb <= 2:
        return 75
    elif pb <= 4:
        return 50
    else:
        return 25

def calculate_score(df: pd.DataFrame, pe_weight: float = 70, pb_weight: float = 30) -> pd.DataFrame:
    total_weight = pe_weight + pb_weight

    pe_w = pe_weight / total_weight
    pb_w = pb_weight / total_weight

    df = df.copy()
    df = df[
        (df["pe_ttm"] > 3) &
        (df["pe_ttm"] < 30) &
        (df["pb"] > 0.5) &
        (df["pb"] < 5)
    ]

    if df.empty:
        return df

    # 排名（越小越好）
    df["pe_rank"] = df["pe_ttm"].rank(method="min", ascending=True)
    df["pb_rank"] = df["pb"].rank(method="min", ascending=True)

    total = len(df)

    # 转换为 0~100 分
    df["pe_score"] = (1 - (df["pe_rank"] - 1) / total) * 100
    df["pb_score"] = (1 - (df["pb_rank"] - 1) / total) * 100

    df["total_score"] = (
        df["pe_score"] * pe_w +
        df["pb_score"] * pb_w
    ).round(2)

    df = df.sort_values(by="total_score", ascending=False)

    return df


def get_latest_valuation_data() -> pd.DataFrame:
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
          AND v.pb IS NOT NULL
          AND v.pb > 0
    """)

    return pd.read_sql(sql, engine)


if __name__ == "__main__":
    df = get_latest_valuation_data()

    result = calculate_score(
        df,
        pe_weight=70,
        pb_weight=30
    )

    print(result[[
        "bs_code",
        "name",
        "close_price",
        "pe_ttm",
        "pb",
        "pe_score",
        "pb_score",
        "total_score"
    ]])
