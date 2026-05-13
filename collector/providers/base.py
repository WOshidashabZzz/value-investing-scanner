"""
美股数据 Provider 基类。

定义统一的数据获取接口，所有具体 Provider 必须继承 BaseProvider。
支持：
- 统一的 fetch 接口 (fetch_spot, fetch_valuations, fetch_fundamentals)
- 自动重试和 fallback
- Provider 日志记录
- 健康检查
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from collector.proxy_utils import log_provider_call

logger = logging.getLogger("us_stocks.providers")


class BaseProvider(ABC):
    """
    数据 Provider 基类。

    所有具体 Provider 必须实现 fetch_spot, fetch_valuations, fetch_fundamentals 方法。
    """

    # Provider 名称（用于日志和配置）
    name: str = "base"

    # 优先级（数字越小优先级越高）
    priority: int = 100

    # 是否可用
    available: bool = True

    def __init__(self):
        self._session = None

    @abstractmethod
    def fetch_spot(self, tickers: list[str] | None = None) -> pd.DataFrame | None:
        """
        获取实时行情数据。

        Args:
            tickers: 股票代码列表，None 表示获取全部

        Returns:
            行情 DataFrame，包含代码、最新价、市盈率、总市值等字段
        """
        ...

    @abstractmethod
    def fetch_valuations(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        获取估值数据（PE/PB 补充）。

        Args:
            tickers: 股票代码列表

        Returns:
            {ticker: {pe: float, pb: float}}
        """
        ...

    @abstractmethod
    def fetch_fundamentals(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        获取基本面数据（ROE、增长率、股息率等）。

        Args:
            tickers: 股票代码列表

        Returns:
            {ticker: {roe: float, revenue_growth: float, ...}}
        """
        ...

    def health_check(self) -> bool:
        """
        健康检查。

        Returns:
            True 表示 Provider 可用
        """
        return self.available

    def get_session(self):
        """获取 requests session（子类可覆盖）。"""
        if self._session is None:
            from collector.proxy_utils import get_requests_session

            self._session = get_requests_session(timeout=30, retries=3)
        return self._session


class ProviderRegistry:
    """
    Provider 注册中心。

    管理所有可用的 Provider，支持按优先级排序和自动 fallback。
    """

    def __init__(self):
        self._providers: dict[str, BaseProvider] = {}
        self._ordered: list[BaseProvider] = []

    def register(self, provider: BaseProvider) -> None:
        """注册一个 Provider。"""
        self._providers[provider.name] = provider
        self._ordered = sorted(
            self._providers.values(), key=lambda p: p.priority
        )
        logger.info(
            f"Provider 已注册: {provider.name} (优先级 {provider.priority})"
        )

    def get(self, name: str) -> BaseProvider | None:
        """按名称获取 Provider。"""
        return self._providers.get(name)

    def get_all(self) -> list[BaseProvider]:
        """获取所有已注册的 Provider（按优先级排序）。"""
        return list(self._ordered)

    def get_available(self) -> list[BaseProvider]:
        """获取所有可用的 Provider（按优先级排序）。"""
        return [p for p in self._ordered if p.health_check()]

    def get_best(self, method: str = "spot") -> BaseProvider | None:
        """
        获取最适合指定方法的最佳 Provider。

        按优先级遍历，返回第一个可用的 Provider。

        Args:
            method: 方法名 (spot, valuations, fundamentals)

        Returns:
            最佳 Provider，None 表示无可用 Provider
        """
        for provider in self.get_available():
            if hasattr(provider, f"fetch_{method}"):
                return provider
        return None

    def unregister(self, name: str) -> None:
        """注销一个 Provider。"""
        if name in self._providers:
            del self._providers[name]
            self._ordered = sorted(
                self._providers.values(), key=lambda p: p.priority
            )
            logger.info(f"Provider 已注销: {name}")


# 全局注册中心实例
_registry = ProviderRegistry()


def register_provider(provider: BaseProvider) -> None:
    """注册 Provider 到全局注册中心。"""
    _registry.register(provider)


def get_provider(name: str) -> BaseProvider | None:
    """从全局注册中心获取 Provider。"""
    return _registry.get(name)


def get_best_provider(method: str = "spot") -> BaseProvider | None:
    """从全局注册中心获取最佳 Provider。"""
    return _registry.get_best(method)


def get_all_providers() -> list[BaseProvider]:
    """获取所有已注册的 Provider。"""
    return _registry.get_all()
