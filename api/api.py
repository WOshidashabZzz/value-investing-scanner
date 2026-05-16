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
from api.risk import _safe_float
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

    # ===== 港股搜索分支 =====
    if market == "hk":
        records = _load_hk_stocks_from_cache()
        if not records:
            return {
                "code": 1,
                "message": "success",
                "market": "hk",
                "total": 0,
                "count": 0,
                "limit": limit,
                "offset": offset,
                "has_next": False,
                "data": [],
                "keyword": q,
            }

        keyword = q.strip().lower()
        filtered = [
            r for r in records
            if keyword in str(r.get("code", "")).lower()
            or keyword in str(r.get("name", "")).lower()
            or keyword in str(r.get("symbol", "")).lower()
        ]

        # 按 final_score 降序
        filtered.sort(
            key=lambda x: (
                x.get("final_score") if x.get("final_score") is not None else -1
            ),
            reverse=True,
        )

        total = len(filtered)
        page = filtered[offset:offset + limit]

        return {
            "code": 1,
            "message": "success",
            "market": "hk",
            "total": total,
            "count": len(page),
            "limit": limit,
            "offset": offset,
            "has_next": offset + limit < total,
            "data": page,
            "keyword": q,
        }

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
    quality_weight: float = Query(40, description="质量模块权重"),
    growth_weight: float = Query(15, description="成长模块权重"),
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
    """获取最新交易日的多因子评分结果。支持 market=us 查询美股（S&P 500）数据，market=hk 查询港股数据。"""
    # ===== 港股分支：从本地缓存读取 =====
    if market == "hk":
        return get_hk_stocks(
            sector=sector,
            limit=limit,
            offset=offset,
            valuation_weight=valuation_weight,
            quality_weight=quality_weight,
            growth_weight=growth_weight,
            dividend_weight=dividend_weight,
            pe_weight=pe_weight or 63,
            pb_weight=pb_weight or 37,
            roe_weight=roe_weight or 100,
            revenue_growth_weight=revenue_growth_weight or 50,
            profit_growth_weight=profit_growth_weight or 50,
            dividend_yield_weight=dividend_yield_weight or 100,
        )

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


def _load_sp500_symbols() -> list[dict]:
    """从 sp500_symbols.csv 加载 S&P 500 股票列表。"""
    csv_path = Path("data/us_stocks/sp500_symbols.csv")
    if not csv_path.exists():
        return []
    try:
        import csv
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception as exc:
        print(f"加载 S&P 500 列表失败: {exc}")
        return []


def _load_old_financial_cache() -> dict:
    """从旧 financial_cache.json 加载基本面数据。"""
    path = Path("data/us_stocks/cache/financial_cache.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_old_daily_cache() -> dict:
    """从旧 daily_cache.json 加载动量/波动率数据。"""
    path = Path("data/us_stocks/cache/daily_cache.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _build_records_from_sp500_and_cache() -> list[dict]:
    """
    从 S&P 500 列表 + 旧缓存构建完整 records。
    当 latest.json 数据不足时使用此方法。
    """
    symbols = _load_sp500_symbols()
    if not symbols:
        return []

    fin_cache = _load_old_financial_cache()
    daily_cache = _load_old_daily_cache()

    records = []
    for sym in symbols:
        ticker = sym.get("ticker", "")
        name = sym.get("name", "")
        if not ticker:
            continue

        rec = {
            "code": ticker,
            "name": name,
            "sector": None,
            "pe": None,
            "pb": None,
            "roe": None,
            "revenue_growth": None,
            "profit_growth": None,
            "dividend_yield": None,
            "momentum_6m": None,
            "momentum_1y": None,
            "volatility_1y": None,
            "max_drawdown_1y": None,
            "final_score": None,
            "total_score": None,
            "rank": None,
        }

        # 从 financial_cache 补充基本面数据
        if ticker in fin_cache:
            fc = fin_cache[ticker]
            if rec["roe"] is None and fc.get("roe") is not None:
                rec["roe"] = fc["roe"]
            if rec["revenue_growth"] is None and fc.get("revenue_growth") is not None:
                rec["revenue_growth"] = fc["revenue_growth"]
            if rec["profit_growth"] is None and fc.get("profit_growth") is not None:
                rec["profit_growth"] = fc["profit_growth"]

        # 从 daily_cache 补充技术指标
        if ticker in daily_cache:
            dc = daily_cache[ticker]
            if rec["momentum_1y"] is None and dc.get("momentum_1y") is not None:
                rec["momentum_1y"] = dc["momentum_1y"]
            if rec["momentum_6m"] is None and dc.get("momentum_6m") is not None:
                rec["momentum_6m"] = dc["momentum_6m"]
            if rec["volatility_1y"] is None and dc.get("volatility_1y") is not None:
                rec["volatility_1y"] = dc["volatility_1y"]
            if rec["max_drawdown_1y"] is None and dc.get("max_drawdown_1y") is not None:
                rec["max_drawdown_1y"] = dc["max_drawdown_1y"]

        records.append(rec)

    return records


def _merge_latest_with_cache(latest_records: list[dict]) -> list[dict]:
    """
    将 latest.json 的记录与旧缓存合并。
    latest.json 中的值优先（因为更新），旧缓存补充缺失字段。
    """
    fin_cache = _load_old_financial_cache()
    daily_cache = _load_old_daily_cache()

    if not fin_cache and not daily_cache:
        return latest_records

    merged = []
    for rec in latest_records:
        ticker = rec.get("code", "")
        r = dict(rec)

        # 从 financial_cache 补充
        if ticker in fin_cache:
            fc = fin_cache[ticker]
            for src_field, dst_field in [
                ("roe", "roe"),
                ("revenue_growth", "revenue_growth"),
                ("profit_growth", "profit_growth"),
            ]:
                if r.get(dst_field) is None and src_field in fc and fc[src_field] is not None:
                    r[dst_field] = fc[src_field]

        # 从 daily_cache 补充
        if ticker in daily_cache:
            dc = daily_cache[ticker]
            for src_field, dst_field in [
                ("momentum_1y", "momentum_1y"),
                ("momentum_6m", "momentum_6m"),
                ("volatility_1y", "volatility_1y"),
                ("max_drawdown_1y", "max_drawdown_1y"),
            ]:
                if r.get(dst_field) is None and src_field in dc and dc[src_field] is not None:
                    r[dst_field] = dc[src_field]

        merged.append(r)

    return merged


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
        data = _clean_nan_recursive(data)

        if len(data) >= 100:
            # 数据充足，直接使用 latest.json，但补充旧缓存中缺失的字段
            US_STOCKS_CACHE = _merge_latest_with_cache(data)
            print(f"美股数据加载完成: {len(US_STOCKS_CACHE)} 条 (来自 latest.json)")
        else:
            # 数据不足，从 S&P 500 列表 + 旧缓存构建完整 records
            print(f"latest.json 数据不足 ({len(data)} 条)，从 S&P 500 列表 + 旧缓存构建")
            built = _build_records_from_sp500_and_cache()
            if built:
                # 将 latest.json 中的值覆盖到构建的记录上（latest 数据更新）
                latest_by_code = {r.get("code", ""): r for r in data}
                for rec in built:
                    code = rec.get("code", "")
                    if code in latest_by_code:
                        lr = latest_by_code[code]
                        for k, v in lr.items():
                            if v is not None:
                                rec[k] = v
                US_STOCKS_CACHE = built
                print(f"美股数据加载完成: {len(US_STOCKS_CACHE)} 条 (来自 S&P 500 列表 + 旧缓存)")
            else:
                US_STOCKS_CACHE = data

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
    如果 final_score 为空，自动运行评分引擎计算。
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

    # 检查是否需要运行评分
    need_scoring = all(r.get("final_score") is None for r in records)
    if need_scoring:
        try:
            from api.us_stock_utils import calculate_us_score
            df = pd.DataFrame(records)
            # 确保评分需要的字段存在
            for col in ["pe", "pb", "roe", "revenue_growth", "profit_growth", "dividend_yield"]:
                if col not in df.columns:
                    df[col] = None
            scored_df = calculate_us_score(df)
            # 将评分结果写回 records
            scored_map = {}
            for _, row in scored_df.iterrows():
                code = row.get("code")
                if code:
                    scored_map[code] = {
                        "final_score": row.get("final_score"),
                        "total_score": row.get("final_score"),
                        "rank": row.get("rank"),
                    }
            for rec in records:
                code = rec.get("code", "")
                if code in scored_map:
                    rec["final_score"] = scored_map[code]["final_score"]
                    rec["total_score"] = scored_map[code]["total_score"]
                    if scored_map[code]["rank"] is not None:
                        rec["rank"] = scored_map[code]["rank"]
            print(f"美股评分完成: {sum(1 for r in records if r.get('final_score') is not None)}/{len(records)} 有评分")
        except Exception as exc:
            print(f"美股评分失败: {exc}")

    # 按 sector 筛选
    if sector:
        filtered = [r for r in records if r.get("sector") == sector]
    else:
        filtered = list(records)

    # 按 final_score 降序排序（有评分的排前面）
    filtered.sort(key=lambda x: (
        0 if x.get("final_score") is not None else 1,
        -(x.get("final_score") or 0)
    ))

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


# ============================================================
# 港股接口
# ============================================================

HK_DATA_PATH = Path("data/hk_stock/latest.json")


def _load_hk_stocks_from_cache() -> list[dict] | None:
    """从本地缓存文件加载港股数据。"""
    try:
        path = Path(__file__).resolve().parent.parent / HK_DATA_PATH
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[港股] 读取缓存失败: {e}")
        return None


import math


def _hk_score_pe(pe: float) -> float | None:
    """港股 PE 区间评分，与 A 股一致。"""
    if pe is None or math.isnan(pe) or pe <= 0 or pe > 100:
        return None
    if pe < 3:
        return 30.0
    if pe < 8:
        return 80.0 - (pe - 3) / 5 * 20
    if pe <= 25:
        return 100.0 - (pe - 8) / 17 * 20
    if pe <= 60:
        return 80.0 - (pe - 25) / 35 * 40
    return 40.0 - (pe - 60) / 40 * 30


def _hk_score_pb(pb: float) -> float | None:
    """港股 PB 区间评分，与 A 股一致。"""
    if pb is None or math.isnan(pb) or pb <= 0:
        return None
    if pb < 0.5:
        return 30.0
    if pb < 0.8:
        return 50.0 + (pb - 0.5) / 0.3 * 20
    if pb <= 3.5:
        return 100.0 - (pb - 0.8) / 2.7 * 30
    if pb <= 8:
        return 70.0 - (pb - 3.5) / 4.5 * 30
    return 20.0


def _hk_score_roe(roe: float) -> float | None:
    """港股 ROE 区间评分，与 A 股一致。"""
    if roe is None or math.isnan(roe) or roe <= 0:
        return None
    if roe < 3:
        return 10.0
    if roe < 10:
        return 30.0 + (roe - 3) / 7 * 50
    if roe <= 25:
        return 80.0 + (roe - 10) / 15 * 20
    return 100.0


def _hk_score_growth(value: float) -> float | None:
    """港股增长率评分（已封顶），与 A 股一致。"""
    if value is None or math.isnan(value):
        return None
    if value > 30:
        return 100.0
    if value > 10:
        return 80.0 + (value - 10) / 20 * 20
    if value > 0:
        return 50.0 + value / 10 * 30
    if value > -20:
        return 20.0 + (value + 20) / 20 * 30
    return max(0, 20.0 + (value + 20) / 30 * 20)


def _hk_score_dividend(dy: float) -> float | None:
    """港股股息率区间评分，与 A 股一致。"""
    if dy is None or math.isnan(dy) or dy <= 0:
        return None
    if dy > 10:
        return 20.0
    if dy > 6:
        return 80.0 - (dy - 6) / 4 * 20
    if dy >= 2:
        return 80.0 + (dy - 2) / 4 * 20
    if dy >= 1:
        return 40.0 + (dy - 1) / 1 * 40
    return dy / 1 * 40


def _hk_clamp_growth(value, field: str):
    """港股增长率封顶，与 A 股一致。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if field == "revenue_growth":
        return max(-50.0, min(100.0, v))
    elif field == "profit_growth":
        return max(-100.0, min(150.0, v))
    return v


def _hk_generate_risk_tag(record: dict) -> str:
    """港股风险标签生成，与 A 股 risk.py 逻辑一致。"""
    pe = _safe_float(record.get("pe"))
    pb = _safe_float(record.get("pb"))
    roe = _safe_float(record.get("roe"))
    revenue_growth = _safe_float(record.get("revenue_growth"))
    profit_growth = _safe_float(record.get("profit_growth"))
    dividend_yield = _safe_float(record.get("dividend_yield"))

    tags = []
    penalty = 0.0

    # PE
    if pe is not None and pe <= 0:
        tags.append("PE异常")
        penalty += 20
    elif pe is not None and pe < 3:
        tags.append("PE过低")
        penalty += 10
    elif pe is not None and pe > 60:
        tags.append("PE过高")
        penalty += 8

    # PB
    if pb is not None and 0 < pb < 0.5:
        tags.append("PB异常")
        penalty += 10
    elif pb is not None and pb > 8:
        tags.append("PB过高")
        penalty += 5

    # 可能价值陷阱
    if (
        pe is not None and pb is not None and roe is not None
        and 0 < pe < 8 and 0 < pb < 0.8 and roe < 8
    ):
        tags.append("可能价值陷阱")
        penalty += 15

    # ROE
    if roe is not None:
        if roe < 0:
            tags.append("ROE为负")
            penalty += 15
        elif roe < 3:
            tags.append("ROE偏低")
            penalty += 10
        elif roe < 6:
            tags.append("ROE偏低")
            penalty += 5

    # 增长率
    if revenue_growth is not None:
        if revenue_growth > 100:
            tags.append("增长异常")
            penalty += 5
        elif revenue_growth < -50:
            tags.append("营收大幅下滑")
            penalty += 10
        elif revenue_growth < 0:
            tags.append("营收下滑")
            penalty += 8

    if profit_growth is not None:
        if profit_growth > 150:
            tags.append("增长异常")
            penalty += 5
        elif profit_growth < -100:
            tags.append("利润大幅下滑")
            penalty += 10
        elif profit_growth < 0:
            tags.append("利润下滑")
            penalty += 10

    # 利润波动大
    if profit_growth is not None and profit_growth > 100 and roe is not None and roe < 5:
        if "利润波动大" not in tags:
            tags.append("利润波动大")
        penalty += 8

    # 股息率
    if dividend_yield is not None:
        if dividend_yield > 10:
            tags.append("股息率异常偏高")
            penalty += 8
        elif dividend_yield > 6:
            tags.append("高股息")
            penalty += 2

    if not tags:
        tags.append("暂无明显风险")

    return "；".join(tags), penalty


def _recalculate_hk_scores(
    records: list[dict],
    valuation_weight: float,
    quality_weight: float,
    growth_weight: float,
    dividend_weight: float,
    pe_weight: float,
    pb_weight: float,
    roe_weight: float,
    revenue_growth_weight: float,
    profit_growth_weight: float,
    dividend_yield_weight: float,
) -> list[dict]:
    """根据传入的权重重新计算港股评分（区间评分 + 增长率封顶 + 风险标签实时生成）。"""
    result = []
    for record in records:
        r = dict(record)

        # 各因子原始值
        pe = _safe_float(r.get("pe"))
        pb = _safe_float(r.get("pb"))
        roe = _safe_float(r.get("roe"))
        revenue_growth = _safe_float(r.get("revenue_growth"))
        profit_growth = _safe_float(r.get("profit_growth"))
        dividend_yield = _safe_float(r.get("dividend_yield"))

        # 增长率封顶
        revenue_growth = _hk_clamp_growth(revenue_growth, "revenue_growth")
        profit_growth = _hk_clamp_growth(profit_growth, "profit_growth")

        # 各因子区间评分（0~100）
        pe_score_raw = _hk_score_pe(pe)
        pb_score_raw = _hk_score_pb(pb)
        roe_score_raw = _hk_score_roe(roe)
        rg_score_raw = _hk_score_growth(revenue_growth)
        pg_score_raw = _hk_score_growth(profit_growth)
        dy_score_raw = _hk_score_dividend(dividend_yield)

        # 模块得分（因子加权平均，权重归一化）
        def _weighted_avg(scores_raw, weights):
            """计算加权平均分，scores_raw 和 weights 对应，None 的跳过。"""
            total_weight = 0.0
            weighted_sum = 0.0
            for s, w in zip(scores_raw, weights):
                if s is not None:
                    weighted_sum += s * w
                    total_weight += w
            if total_weight > 0:
                return weighted_sum / total_weight
            return None

        valuation_score = _weighted_avg(
            [pe_score_raw, pb_score_raw],
            [pe_weight, pb_weight]
        )
        quality_score = _weighted_avg(
            [roe_score_raw],
            [roe_weight]
        )
        growth_score = _weighted_avg(
            [rg_score_raw, pg_score_raw],
            [revenue_growth_weight, profit_growth_weight]
        )
        dividend_score = _weighted_avg(
            [dy_score_raw],
            [dividend_yield_weight]
        )

        # 综合评分（模块加权）
        active_cat_scores = []
        active_cat_weights = []
        if valuation_score is not None:
            active_cat_scores.append(valuation_score)
            active_cat_weights.append(valuation_weight)
        if quality_score is not None:
            active_cat_scores.append(quality_score)
            active_cat_weights.append(quality_weight)
        if growth_score is not None:
            active_cat_scores.append(growth_score)
            active_cat_weights.append(growth_weight)
        if dividend_score is not None:
            active_cat_scores.append(dividend_score)
            active_cat_weights.append(dividend_weight)

        if active_cat_scores and sum(active_cat_weights) > 0:
            raw_score = sum(s * w for s, w in zip(active_cat_scores, active_cat_weights)) / sum(active_cat_weights)
        else:
            raw_score = None

        # 实时生成风险标签（不再复用缓存）
        risk_tag, risk_penalty = _hk_generate_risk_tag(r)

        if raw_score is not None:
            r["final_score"] = round(max(0, min(100, raw_score - risk_penalty)), 2)
        else:
            r["final_score"] = None

        r["risk_tag"] = risk_tag

        # 记录各模块得分
        r["valuation_score"] = round(valuation_score, 2) if valuation_score is not None else None
        r["quality_score"] = round(quality_score, 2) if quality_score is not None else None
        r["growth_score"] = round(growth_score, 2) if growth_score is not None else None
        r["dividend_score"] = round(dividend_score, 2) if dividend_score is not None else None

        result.append(r)

    return result


def get_hk_stocks(
    sector: str | None = None,
    limit: int = 50,
    offset: int = 0,
    valuation_weight: float = 35,
    quality_weight: float = 40,
    growth_weight: float = 15,
    dividend_weight: float = 10,
    pe_weight: float = 63,
    pb_weight: float = 37,
    roe_weight: float = 100,
    revenue_growth_weight: float = 50,
    profit_growth_weight: float = 50,
    dividend_yield_weight: float = 100,
) -> dict:
    """获取港股数据（从本地缓存读取，根据权重实时评分）。"""
    records = _load_hk_stocks_from_cache()

    if not records:
        return {
            "code": 1,
            "message": "success",
            "market": "hk",
            "total": 0,
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_next": False,
            "data": [],
        }

    # 板块筛选
    if sector:
        filtered = [
            r for r in records
            if r.get("sector") == sector or r.get("industry") == sector
        ]
    else:
        filtered = records

    # 根据传入的权重重新评分
    scored = _recalculate_hk_scores(
        filtered,
        valuation_weight=valuation_weight,
        quality_weight=quality_weight,
        growth_weight=growth_weight,
        dividend_weight=dividend_weight,
        pe_weight=pe_weight,
        pb_weight=pb_weight,
        roe_weight=roe_weight,
        revenue_growth_weight=revenue_growth_weight,
        profit_growth_weight=profit_growth_weight,
        dividend_yield_weight=dividend_yield_weight,
    )

    # 排序：按 final_score 降序
    scored.sort(
        key=lambda x: (
            x.get("final_score") if x.get("final_score") is not None else -1
        ),
        reverse=True,
    )

    total = len(scored)
    page = scored[offset:offset + limit]

    # 从第一条记录提取数据日期
    date_str = "-"
    if page:
        ut = page[0].get("update_time", "")
        if ut:
            date_str = ut[:10]  # 只取日期部分 "2026-05-15"

    return {
        "code": 1,
        "message": "success",
        "market": "hk",
        "date": date_str,
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
