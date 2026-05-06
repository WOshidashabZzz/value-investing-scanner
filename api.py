import math
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from factor_config import CATEGORY_WEIGHTS, FACTOR_CONFIG
from scoring import calculate_score, get_latest_strategy_data


app = FastAPI(
    title="A股稳健价值评分系统 API",
    description="基于估值、质量、成长和分红因子的价值投资辅助筛选接口，不构成投资建议。",
    version="2.0.0",
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
        if module_weight > 0 and factor_total <= 0:
            return f"{module_name}权重大于 0 时，模块内至少要有一个因子权重大于 0。"

    return None


@app.get("/")
def root():
    return {
        "message": "A股稳健价值评分系统 API 已启动",
        "docs": "/docs",
        "stocks_api": "/stocks",
        "strategy_api": "/strategy/default",
        "factors_api": "/factors",
    }


@app.get("/stocks")
def get_stocks(
    valuation_weight: float = Query(35, description="估值模块权重"),
    quality_weight: float = Query(30, description="质量模块权重"),
    growth_weight: float = Query(25, description="成长模块权重"),
    dividend_weight: float = Query(10, description="分红模块权重"),
    limit: int = Query(50, description="返回股票数量", ge=1, le=500),
    pe_weight: float | None = Query(None, description="兼容旧接口：PE_TTM 因子权重"),
    pb_weight: float | None = Query(None, description="兼容旧接口：PB 因子权重"),
    roe_weight: float | None = Query(None, description="ROE 因子权重"),
    revenue_growth_weight: float | None = Query(None, description="营收增长率因子权重"),
    profit_growth_weight: float | None = Query(None, description="净利润增长率因子权重"),
    dividend_yield_weight: float | None = Query(None, description="股息率因子权重"),
):
    """获取最新交易日的多因子评分结果。"""
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
        return {
            "code": 0,
            "message": validation_error,
            "count": 0,
            "data": [],
        }

    df = get_latest_strategy_data()

    if df.empty:
        return {
            "code": 0,
            "message": "数据库中暂无估值数据，请先运行数据采集流程。",
            "count": 0,
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

    result = calculate_score(
        df,
        factor_weights=factor_weights or None,
        category_weights={
            "valuation": valuation_weight,
            "quality": quality_weight,
            "growth": growth_weight,
            "dividend": dividend_weight,
        },
    ).head(limit)

    return {
        "code": 1,
        "message": "success",
        "count": len(result),
        "data": _records(result, STOCK_RESPONSE_FIELDS),
    }


@app.get("/stocks/low-pe")
def get_low_pe_stocks(
    max_pe: float = Query(15, description="最大 PE_TTM"),
    max_pb: float = Query(2, description="最大 PB"),
    limit: int = Query(50, description="返回股票数量", ge=1, le=500),
):
    """获取低 PE、低 PB 股票，并使用新策略评分。"""
    df = get_latest_strategy_data()

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
