FACTOR_CONFIG = {
    "pe_ttm": {
        "name": "PE_TTM",
        "category": "valuation",
        "direction": "lower_better",
        "weight": 22,
    },
    "pb": {
        "name": "PB",
        "category": "valuation",
        "direction": "lower_better",
        "weight": 13,
    },
    "roe": {
        "name": "ROE",
        "category": "quality",
        "direction": "higher_better",
        "weight": 30,
    },
    "revenue_growth": {
        "name": "营收增长率",
        "category": "growth",
        "direction": "higher_better",
        "weight": 12.5,
    },
    "profit_growth": {
        "name": "净利润增长率",
        "category": "growth",
        "direction": "higher_better",
        "weight": 12.5,
    },
    "dividend_yield": {
        "name": "股息率",
        "category": "dividend",
        "direction": "higher_better",
        "weight": 10,
    },
}


CATEGORY_WEIGHTS = {
    "valuation": 35,
    "quality": 30,
    "growth": 25,
    "dividend": 10,
}
