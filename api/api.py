import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.db import get_engine
from api.factor_config import CATEGORY_WEIGHTS, FACTOR_CONFIG
from api.scoring import calculate_score, get_latest_strategy_data
from api.stock_utils import BOARD_LABELS, VALID_BOARD_FILTERS, SECTOR_LABELS, VALID_SECTORS
from api.us_stock_utils import (
    US_STOCK_RESPONSE_FIELDS,
    calculate_us_score,
    records_from_df,
)


app = FastAPI(
    title="稳健价值评分系统 API",
    description="基于估值、质量、成长和分红因子的价值投资辅助筛选接口，支持 A 股和美股（S&P 500）。不构成投资建议。",
    version="2.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


STOCK_RESPONSE_FIELDS = [
    "bs_code",
    "symbol",
    "name",
    "market",
    "board",
    "sector",
    "trade_date",
    "report_date",
    "close_price",
    "pe_ttm",
    "pb",
    "roe",
    "revenue_growth",
    "profit_growth",
    "dividend_yield",
    "valuation_score",
    "quality_score",
    "growth_score",
    "dividend_score",
    "raw_score",
    "risk_penalty",
    "final_score",
    "risk_tags",
    "active_categories",
    "inactive_categories",
    "active_factors",
    "inactive_factors",
    "rank",
]


def _clean_value(value: Any):
    """将 Pandas/NumPy 空值和日期转换成 JSON 友好格式。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _records(df: pd.DataFrame, fields: list[str]):
    """按指定字段输出 JSON 记录，并补齐缺失列。"""
    output = df.copy()
    for field in fields:
        if field not in output.columns:
            output[field] = None

    records = output[fields].to_dict(orient="records")
    return [
        {key: _clean_value(value) for key, value in record.items()}
        for record in records
    ]


def _validate_stock_query_weights(
    valuation_weight: float,
    quality_weight: float,
    growth_weight: float,
    dividend_weight: float,
    pe_weight: float | None = None,
    pb_weight: float | None = None,
    roe_weight: float | None = None,
    revenue_growth_weight: float | None = None,
    profit_growth_weight: float | None = None,
    dividend_yield_weight: float | None = None,
):
    """校验评分权重参数，返回错误提示。"""
    weights = {
        "估值权重": valuation_weight,
        "质量权重": quality_weight,
        "成长权重": growth_weight,
        "分红权重": dividend_weight,
    }

    for name, value in weights.items():
        if value < 0 or value > 100:
            return f"{name}必须是 0 到 100 之间的数字，不能输入负数。"

    total_weight = sum(weights.values())
    if abs(total_weight - 100) > 0.0001:
        return f"四个模块权重之和必须等于 100%，当前合计为 {total_weight:.2f}%。"

    factor_weights = {
        "pe_ttm": pe_weight,
        "pb": pb_weight,
        "roe": roe_weight,
        "revenue_growth": revenue_growth_weight,
        "profit_growth": profit_growth_weight,
        "dividend_yield": dividend_yield_weight,
    }
    factor_names = {
        "pe_ttm": "PE_TTM",
        "pb": "PB",
        "roe": "ROE",
        "revenue_growth": "营收增长率",
        "profit_growth": "净利润增长率",
        "dividend_yield": "股息率",
    }
    effective_factor_weights = {}

    for factor, value in factor_weights.items():
        effective_value = FACTOR_CONFIG[factor]["weight"] if value is None else value

        if effective_value < 0 or effective_value > 100:
            return f"{factor_names[factor]} 因子权重必须是 0 到 100 之间的数字，不能输入负数。"

        effective_factor_weights[factor] = effective_value

    module_factor_rules = [
        ("估值模块", valuation_weight, ["pe_ttm", "pb"]),
        ("质量模块", quality_weight, ["roe"]),
        ("成长模块", growth_weight, ["revenue_growth", "profit_growth"]),
        ("分红模块", dividend_weight, ["dividend_yield"]),
    ]

    for module_name, module_weight, factors in module_factor_rules:
        factor_total = sum(effective_factor_weights[factor] for factor in factors)
        if abs(factor_total - 100) > 0.0001:
            return f"{module_name}模块内因子权重之和必须等于 100%，当前合计为 {factor_total:.2f}%。"
        if module_weight > 0 and factor_total <= 0:
            return f"{module_name}权重大于 0 时，模块内至少要有一个因子权重大于 0。"

    return None


@app.get("/")
def root():
    return {
        "message": "稳健价值评分系统 API 已启动",
        "docs": "/docs",
        "stocks_api": "/stocks",
        "strategy_api": "/strategy/default",
        "factors_api": "/factors",
        "markets": ["cn", "us"],
    }


def _search_stocks_raw(
    q: str,
    board: str | None = None,
    market: str | None = None,
) -> pd.DataFrame:
    """按关键词搜索股票，返回原始 DataFrame（未评分）。"""
    engine = get_engine()
    keyword = f"%{q}%"

    sql = text("""
        SELECT
            b.bs_code,
            b.symbol,
            b.name,
            b.market,
            b.board,
            v.trade_date,
            v.close_price,
            v.pe_ttm,
            v.pb,
            v.ps_ttm,
            v.pcf_ncf_ttm,
            f.report_date,
            f.roe,
            f.revenue_growth,
            f.profit_growth,
            f.dividend_yield
        FROM stock_basic b
        JOIN stock_valuation v ON b.id = v.stock_id
        LEFT JOIN stock_financial f
            ON b.id = f.stock_id
           AND f.report_date = (
                SELECT MAX(f2.report_date)
                FROM stock_financial f2
                WHERE f2.stock_id = b.id
           )
        WHERE v.data_version = 'latest'
          AND v.trade_date = (
            SELECT MAX(trade_date)
            FROM stock_valuation
            WHERE data_version = 'latest'
        )
          AND (b.bs_code LIKE :q OR b.name LIKE :q OR b.symbol LIKE :q)
    """)
    filters = []
    params = {"q": keyword}

    if board and board != "all":
        filters.append("b.board = :board")
        params["board"] = board

    if market:
        filters.append("b.market = :market")
        params["market"] = market

    sql_text = sql.text
    if filters:
        sql_text = f"{sql_text}\n        AND {' AND '.join(filters)}"

    return pd.read_sql(text(sql_text), engine, params=params)


@app.get("/stocks/search")
def search_stocks(
    q: str = Query("", description="搜索关键词：股票代码或名称"),
    valuation_weight: float = Query(35, description="估值模块权重"),
    quality_weight: float = Query(30, description="质量模块权重"),
    growth_weight: float = Query(25, description="成长模块权重"),
    dividend_weight: float = Query(10, description="分红模块权重"),
    board: str | None = Query(None, description="股票板块：main_board/gem/star/bse/all"),
    market: str | None = Query(None, description="市场：sh/sz/bj"),
    sector: str | None = Query(None, description="一级板块：金融/消费/医药/科技/制造/周期/地产基建/公用环保"),
    limit: int = Query(50, description="返回股票数量", ge=1, le=500),
    offset: int = Query(0, description="分页偏移量", ge=0),
    pe_weight: float | None = Query(63, description="兼容旧接口：PE_TTM 因子权重"),
    pb_weight: float | None = Query(37, description="兼容旧接口：PB 因子权重"),
    roe_weight: float | None = Query(100, description="ROE 因子权重"),
    revenue_growth_weight: float | None = Query(50, description="营收增长率因子权重"),
    profit_growth_weight: float | None = Query(50, description="净利润增长率因子权重"),
    dividend_yield_weight: float | None = Query(100, description="股息率因子权重"),
):
    """按关键词搜索股票代码或名称，返回评分结果。"""
    q = q.strip()

    # 如果关键词为空，返回正常 /stocks 数据
    if not q:
        return get_stocks(
            valuation_weight=valuation_weight,
            quality_weight=quality_weight,
            growth_weight=growth_weight,
            dividend_weight=dividend_weight,
            board=board,
            market=market,
            sector=sector,
            limit=limit,
            offset=offset,
            pe_weight=pe_weight,
            pb_weight=pb_weight,
            roe_weight=roe_weight,
            revenue_growth_weight=revenue_growth_weight,
            profit_growth_weight=profit_growth_weight,
            dividend_yield_weight=dividend_yield_weight,
        )

    validation_error = _validate_stock_query_weights(
        valuation_weight,
        quality_weight,
        growth_weight,
        dividend_weight,
        pe_weight,
        pb_weight,
        roe_weight,
        revenue_growth_weight,
        profit_growth_weight,
        dividend_yield_weight,
    )

    if validation_error:
        current_board = board or "main_board"
        return {
            "code": 0,
            "message": validation_error,
            "current_board": current_board,
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
            "keyword": q,
        }

    current_board = board or "main_board"

    # 第一步：获取全量股票池并完成评分和排名
    df = get_latest_strategy_data(board=current_board, market=market, sector=sector)

    if df.empty:
        return {
            "code": 1,
            "message": "success",
            "current_board": current_board,
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
            "keyword": q,
        }

    factor_weights = {}
    if pe_weight is not None:
        factor_weights["pe_ttm"] = pe_weight
    if pb_weight is not None:
        factor_weights["pb"] = pb_weight
    if roe_weight is not None:
        factor_weights["roe"] = roe_weight
    if revenue_growth_weight is not None:
        factor_weights["revenue_growth"] = revenue_growth_weight
    if profit_growth_weight is not None:
        factor_weights["profit_growth"] = profit_growth_weight
    if dividend_yield_weight is not None:
        factor_weights["dividend_yield"] = dividend_yield_weight

    # 在全量股票池上评分
    scored = calculate_score(
        df,
        factor_weights=factor_weights or None,
        category_weights={
            "valuation": valuation_weight,
            "quality": quality_weight,
            "growth": growth_weight,
            "dividend": dividend_weight,
        },
    )
    scored = scored.reset_index(drop=True)
    scored["rank"] = scored.index + 1

    # 第二步：在已评分的全量池中按关键词过滤
    keyword = q.strip()
    mask = (
        scored["bs_code"].str.contains(keyword, case=False, na=False)
        | scored["name"].str.contains(keyword, case=False, na=False)
        | scored["symbol"].str.contains(keyword, case=False, na=False)
    )
    filtered = scored[mask]

    total = len(filtered)
    result = filtered.iloc[offset:offset + limit]

    return {
        "code": 1,
        "message": "success",
        "current_board": current_board,
        "total": total,
        "count": len(result),
        "limit": limit,
        "offset": offset,
        "has_next": offset + limit < total,
        "data": _records(result, STOCK_RESPONSE_FIELDS),
        "keyword": q,
    }


@app.get("/stocks")
def get_stocks(
    valuation_weight: float = Query(35, description="估值模块权重"),
    quality_weight: float = Query(30, description="质量模块权重"),
    growth_weight: float = Query(25, description="成长模块权重"),
    dividend_weight: float = Query(10, description="分红模块权重"),
    board: str | None = Query(None, description="股票板块：main_board/gem/star/bse/all"),
    market: str | None = Query(None, description="市场：sh/sz/bj（A股）；us（美股）"),
    sector: str | None = Query(None, description="一级板块：金融/消费/医药/科技/制造/周期/地产基建/公用环保"),
    limit: int = Query(50, description="返回股票数量", ge=1, le=500),
    offset: int = Query(0, description="分页偏移量", ge=0),
    pe_weight: float | None = Query(63, description="兼容旧接口：PE_TTM 因子权重"),
    pb_weight: float | None = Query(37, description="兼容旧接口：PB 因子权重"),
    roe_weight: float | None = Query(100, description="ROE 因子权重"),
    revenue_growth_weight: float | None = Query(50, description="营收增长率因子权重"),
    profit_growth_weight: float | None = Query(50, description="净利润增长率因子权重"),
    dividend_yield_weight: float | None = Query(100, description="股息率因子权重"),
):
    """获取最新交易日的多因子评分结果。支持 market=us 查询美股（S&P 500）数据。"""
    # ===== 美股分支：只读本地缓存，不实时抓取 =====
    if market == "us":
        return get_us_stocks(
            sector=sector,
            limit=limit,
            offset=offset,
        )

    # ===== A 股原有逻辑 =====
    validation_error = _validate_stock_query_weights(
        valuation_weight,
        quality_weight,
        growth_weight,
        dividend_weight,
        pe_weight,
        pb_weight,
        roe_weight,
        revenue_growth_weight,
        profit_growth_weight,
        dividend_yield_weight,
    )

    if validation_error:
        current_board = board or "main_board"
        return {
            "code": 0,
            "message": validation_error,
            "current_board": current_board,
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    current_board = board or "main_board"
    if current_board not in VALID_BOARD_FILTERS:
        return {
            "code": 0,
            "message": f"board 参数不支持：{current_board}",
            "current_board": current_board,
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    if sector and sector not in VALID_SECTORS:
        return {
            "code": 0,
            "message": f"sector 参数不支持：{sector}",
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    df = get_latest_strategy_data(board=current_board, market=None, sector=sector)

    if df.empty:
        return {
            "code": 1,
            "message": "success",
            "current_board": current_board,
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    factor_weights = {}
    if pe_weight is not None:
        factor_weights["pe_ttm"] = pe_weight
    if pb_weight is not None:
        factor_weights["pb"] = pb_weight
    if roe_weight is not None:
        factor_weights["roe"] = roe_weight
    if revenue_growth_weight is not None:
        factor_weights["revenue_growth"] = revenue_growth_weight
    if profit_growth_weight is not None:
        factor_weights["profit_growth"] = profit_growth_weight
    if dividend_yield_weight is not None:
        factor_weights["dividend_yield"] = dividend_yield_weight

    scored = calculate_score(
        df,
        factor_weights=factor_weights or None,
        category_weights={
            "valuation": valuation_weight,
            "quality": quality_weight,
            "growth": growth_weight,
            "dividend": dividend_weight,
        },
    )
    scored = scored.reset_index(drop=True)
    scored["rank"] = scored.index + 1
    total = len(scored)
    result = scored.iloc[offset:offset + limit]

    return {
        "code": 1,
        "message": "success",
        "current_board": current_board,
        "total": total,
        "count": len(result),
        "limit": limit,
        "offset": offset,
        "has_next": offset + limit < total,
        "data": _records(result, STOCK_RESPONSE_FIELDS),
    }


@app.get("/stocks/low-pe")
def get_low_pe_stocks(
    max_pe: float = Query(15, description="最大 PE_TTM"),
    max_pb: float = Query(2, description="最大 PB"),
    limit: int = Query(50, description="返回股票数量", ge=1, le=500),
):
    """获取低 PE、低 PB 股票，并使用新策略评分。"""
    df = get_latest_strategy_data(board="main_board")

    if df.empty:
        return {
            "code": 0,
            "message": "数据库中暂无估值数据，请先运行数据采集流程。",
            "count": 0,
            "data": [],
        }

    filtered = df[
        (pd.to_numeric(df["pe_ttm"], errors="coerce") > 0)
        & (pd.to_numeric(df["pe_ttm"], errors="coerce") < max_pe)
        & (pd.to_numeric(df["pb"], errors="coerce") > 0)
        & (pd.to_numeric(df["pb"], errors="coerce") < max_pb)
    ]

    result = calculate_score(filtered).head(limit)

    return {
        "code": 1,
        "message": "success",
        "count": len(result),
        "data": _records(result, STOCK_RESPONSE_FIELDS),
    }


@app.get("/strategy/default")
def get_default_strategy():
    """返回默认稳健价值策略说明。"""
    return {
        "strategy_name": "稳健价值策略",
        "description": "综合考虑估值、盈利能力、成长性和分红水平，筛选可能被低估且基本面相对稳健的股票。",
        "category_weights": CATEGORY_WEIGHTS,
        "factors": [
            {"key": key, **config}
            for key, config in FACTOR_CONFIG.items()
        ],
        "disclaimer": "结果仅用于研究和初筛，需结合基本面进一步分析，不构成投资建议。",
    }


@app.get("/factors")
def get_factors():
    """返回因子配置，供前端自动渲染权重设置。"""
    return {
        "factor_config": FACTOR_CONFIG,
        "category_weights": CATEGORY_WEIGHTS,
    }


@app.get("/valuation/date")
def get_valuation_date():
    """返回 latest 版本的最新估值日期，供前端展示。"""
    engine = get_engine()
    sql = text("""
        SELECT MAX(trade_date) AS valuation_date
        FROM stock_valuation
        WHERE data_version = 'latest'
    """)
    df = pd.read_sql(sql, engine)
    date_val = df.iloc[0]["valuation_date"] if not df.empty else None
    return {
        "valuation_date": str(date_val) if date_val else None,
        "data_version": "latest",
    }


@app.get("/sectors")
def get_sectors():
    """返回一级板块列表，供前端渲染板块筛选按钮。"""
    return {
        "sectors": [
            {"key": key, "label": label}
            for key, label in SECTOR_LABELS.items()
        ],
    }


# ===== 美股接口 =====

US_STOCKS_CACHE: dict | None = None
"""美股数据内存缓存，避免每次请求都读磁盘。"""


def _load_us_stocks_from_cache() -> list[dict] | None:
    """从本地缓存文件加载美股数据（只读，不实时抓取）。"""
    global US_STOCKS_CACHE

    if US_STOCKS_CACHE is not None:
        return US_STOCKS_CACHE

    latest_path = Path("data/us_stocks/latest.json")
    if not latest_path.exists():
        return None

    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 清理 NaN / Inf 值（JSON 标准不支持这些浮点值）
        US_STOCKS_CACHE = _clean_nan_recursive(data)
        return US_STOCKS_CACHE
    except Exception as exc:
        print(f"读取美股缓存失败: {exc}")
        return None


def _clean_nan_recursive(obj):
    """递归清理数据中的 NaN / Inf 浮点值，替换为 None。"""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: _clean_nan_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan_recursive(v) for v in obj]
    return obj


def get_us_stocks(
    sector: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    获取美股（S&P 500）评分数据。

    只读取本地缓存文件 data/us_stocks/latest.json，不实时抓取外部网站。
    """
    records = _load_us_stocks_from_cache()

    if records is None:
        return {
            "code": 0,
            "message": "美股数据尚未更新，请先运行 python -m collector.update_us_stocks",
            "market": "us",
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    # 按 sector 筛选
    if sector:
        filtered = [r for r in records if r.get("sector") == sector]
    else:
        filtered = list(records)

    # 按 rank 排序（如果存在）
    filtered.sort(key=lambda x: x.get("rank", 9999) if x.get("rank") is not None else 9999)

    total = len(filtered)
    page = filtered[offset: offset + limit]

    # 统一字段名：将 final_score 映射为 total_score（前端兼容）
    for record in page:
        if "final_score" in record and "total_score" not in record:
            record["total_score"] = record["final_score"]

    return {
        "code": 1,
        "message": "success",
        "market": "us",
        "total": total,
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "has_next": offset + limit < total,
        "data": page,
    }


@app.get("/us/valuation/date")
def get_us_valuation_date():
    """返回美股最新估值日期。"""
    records = _load_us_stocks_from_cache()
    if records and len(records) > 0:
        date_val = records[0].get("valuation_date")
        return {
            "valuation_date": str(date_val) if date_val else None,
            "data_version": "latest",
            "market": "us",
        }
    return {
        "valuation_date": None,
        "data_version": "latest",
        "market": "us",
    }
