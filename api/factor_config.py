FACTOR_CONFIG = {
    "pe_ttm": {
        "name": "PE_TTM",
        "category": "valuation",
        "direction": "lower_better",
        "weight": 63,
    },
    "pb": {
        "name": "PB",
        "category": "valuation",
        "direction": "lower_better",
        "weight": 37,
    },
    "roe": {
        "name": "ROE",
        "category": "quality",
        "direction": "higher_better",
        "weight": 100,
    },
    "revenue_growth": {
        "name": "营收增长率",
        "category": "growth",
        "direction": "higher_better",
        "weight": 50,
    },
    "profit_growth": {
        "name": "净利润增长率",
        "category": "growth",
        "direction": "higher_better",
        "weight": 50,
    },
    "dividend_yield": {
        "name": "股息率",
        "category": "dividend",
        "direction": "higher_better",
        "weight": 100,
        "min_valid_ratio": 0,
    },
}


CATEGORY_WEIGHTS = {
    "valuation": 35,
    "quality": 40,
    "growth": 15,
    "dividend": 10,
}
