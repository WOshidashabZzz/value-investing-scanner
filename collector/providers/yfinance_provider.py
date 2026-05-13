"""
yfinance 美股数据 Provider。

数据源：
1. yfinance.Ticker - 获取基本面数据（ROE、增长率、股息率等）
2. 补充 PE/PB（当 AKShare 缺失时）

优先级：中 (priority=20)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from collector.providers.base import BaseProvider, register_provider
from collector.proxy_utils import log_provider_call, patch_yfinance_session
from api.us_stock_schema import safe_float

logger = logging.getLogger("us_stocks.providers.yfinance")


class YFinanceProvider(BaseProvider):
    """yfinance 数据 Provider。"""

    name = "yfinance"
    priority = 20  # 中优先级

    def __init__(self):
        super().__init__()
        self._patched = False

    def _ensure_patched(self):
        """确保 yfinance session 已 patch 代理。"""
        if not self._patched:
            self._patched = patch_yfinance_session()
            if self._patched:
                logger.info("yfinance session 已 patch 代理")

    def fetch_spot(self, tickers: list[str] | None = None) -> pd.DataFrame | None:
        """
        yfinance 不提供批量行情，返回 None（使用 AKShare 替代）。

        Returns:
            None
        """
        return None

    def fetch_valuations(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        从 yfinance 获取估值数据（PE/PB）。

        Args:
            tickers: 股票代码列表

        Returns:
            {ticker: {pe: float, pb: float}}
        """
        result: dict[str, dict[str, Any]] = {}
        failed = 0

        self._ensure_patched()

        with log_provider_call("yfinance", "fetch_valuations") as log:
            try:
                import yfinance as yf

                for i, ticker in enumerate(tickers):
                    try:
                        tk = yf.Ticker(ticker)
                        info = tk.info if hasattr(tk, "info") else {}

                        if not info:
                            continue

                        record = {}
                        pe = safe_float(info.get("trailingPE"))
                        if pe is not None and pe > 0:
                            record["pe"] = pe
                        else:
                            pe = safe_float(info.get("forwardPE"))
                            if pe is not None and pe > 0:
                                record["pe"] = pe

                        pb = safe_float(info.get("priceToBook"))
                        if pb is not None and pb > 0:
                            record["pb"] = pb

                        if record:
                            result[ticker] = record

                        # 请求间隔
                        if i < len(tickers) - 1:
                            time.sleep(0.3)

                    except Exception as e:
                        failed += 1
                        if failed <= 3:
                            logger.warning(f"yfinance 估值获取失败 {ticker}: {e}")

                log.success(ticker_count=len(tickers), success_count=len(result), failed=failed)
                logger.info(f"yfinance 估值获取完成: {len(result)}/{len(tickers)} 成功, {failed} 失败")

            except Exception as e:
                log.fail(error=str(e))
                logger.error(f"yfinance 估值模块初始化失败: {e}")

        return result

    def fetch_fundamentals(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        从 yfinance 获取基本面数据。

        包括：ROE、营收增长率、利润增长率、股息率、市值等。

        Args:
            tickers: 股票代码列表

        Returns:
            {ticker: {roe: float, revenue_growth: float, ...}}
        """
        result: dict[str, dict[str, Any]] = {}
        failed = 0

        self._ensure_patched()

        with log_provider_call("yfinance", "fetch_fundamentals") as log:
            try:
                import yfinance as yf

                for i, ticker in enumerate(tickers):
                    try:
                        tk = yf.Ticker(ticker)
                        info = tk.info if hasattr(tk, "info") else {}

                        if not info:
                            continue

                        record: dict[str, Any] = {}

                        # PE
                        pe = safe_float(info.get("trailingPE"))
                        if pe is not None and pe > 0:
                            record["pe"] = pe

                        # PB
                        pb = safe_float(info.get("priceToBook"))
                        if pb is not None and pb > 0:
                            record["pb"] = pb

                        # ROE = 净利润 / 股东权益
                        net_income = safe_float(info.get("netIncomeToCommon"))
                        equity = safe_float(info.get("bookValue")) * safe_float(info.get("sharesOutstanding", 0)) if safe_float(info.get("bookValue")) else None
                        if net_income and equity and equity > 0:
                            record["roe"] = round((net_income / equity) * 100, 2)
                        elif info.get("returnOnEquity"):
                            roe = safe_float(info.get("returnOnEquity"))
                            if roe is not None:
                                record["roe"] = round(roe * 100, 2)

                        # 营收增长率
                        revenue_growth = safe_float(info.get("revenueGrowth"))
                        if revenue_growth is not None:
                            record["revenue_growth"] = round(revenue_growth * 100, 2)

                        # 利润增长率
                        earnings_growth = safe_float(info.get("earningsGrowth"))
                        if earnings_growth is not None:
                            record["profit_growth"] = round(earnings_growth * 100, 2)

                        # 股息率
                        dividend_yield = safe_float(info.get("dividendYield"))
                        if dividend_yield is not None:
                            record["dividend_yield"] = round(dividend_yield * 100, 2)

                        # 市值
                        market_cap = safe_float(info.get("marketCap"))
                        if market_cap is not None:
                            record["market_cap"] = market_cap

                        # 收盘价
                        current_price = safe_float(info.get("currentPrice"))
                        if current_price is not None:
                            record["close_price"] = current_price

                        if record:
                            result[ticker] = record

                        # 请求间隔
                        if i < len(tickers) - 1:
                            time.sleep(0.3)

                    except Exception as e:
                        failed += 1
                        if failed <= 3:
                            logger.warning(f"yfinance 基本面获取失败 {ticker}: {e}")

                log.success(ticker_count=len(tickers), success_count=len(result), failed=failed)
                logger.info(f"yfinance 基本面获取完成: {len(result)}/{len(tickers)} 成功, {failed} 失败")

            except Exception as e:
                log.fail(error=str(e))
                logger.error(f"yfinance 基本面模块初始化失败: {e}")

        return result

    def health_check(self) -> bool:
        """检查 yfinance 是否可用。"""
        try:
            import yfinance as yf
            return True
        except ImportError:
            logger.warning("yfinance 未安装")
            return False
        except Exception as e:
            logger.warning(f"yfinance 健康检查失败: {e}")
            return False


# 自动注册
register_provider(YFinanceProvider())
