"""
美股数据 Provider 包。

提供统一的数据源抽象层，支持热切换和自动 fallback。

使用方式：
    from collector.providers import get_provider, get_best_provider

    provider = get_provider("akshare")
    data = provider.fetch_spot(tickers)
"""

from collector.providers.base import (
    BaseProvider,
    ProviderRegistry,
    register_provider,
    get_provider,
    get_best_provider,
    get_all_providers,
)

# 导入 Provider 实现（触发自动注册）
from collector.providers import akshare_provider  # noqa: F401
from collector.providers import yfinance_provider  # noqa: F401

__all__ = [
    "BaseProvider",
    "ProviderRegistry",
    "register_provider",
    "get_provider",
    "get_best_provider",
    "get_all_providers",
]
