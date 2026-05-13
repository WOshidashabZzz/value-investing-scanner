"""
AKShare 美股数据 Provider。

数据源：
1. stock_us_spot_em() - 东方财富美股实时行情（主数据源）
2. stock_us_valuation_baidu() - 百度美股估值（补充 PE/PB）

优先级：高 (priority=10)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from collector.providers.base import BaseProvider, register_provider
from collector.proxy_utils import log_provider_call, get_requests_session
from api.us_stock_schema import safe_float, extract_ticker

logger = logging.getLogger("us_stocks.providers.akshare")


class AKShareProvider(BaseProvider):
    """AKShare 数据 Provider。"""

    name = "akshare"
    priority = 10  # 高优先级

    def fetch_spot(self, tickers: list[str] | None = None) -> pd.DataFrame | None:
        """
        从东方财富获取美股实时行情。

        API: stock_us_spot_em()

        Returns:
            行情 DataFrame，包含代码、最新价、市盈率、总市值等字段
        """
        with log_provider_call("akshare", "stock_us_spot_em") as log:
            try:
                import akshare as ak

                df = ak.stock_us_spot_em()
                if df is None or df.empty:
                    log.fail(error="返回空数据")
                    return None

                # 过滤需要的字段
                result = df[["代码", "名称", "最新价", "市盈率", "总市值"]].copy()

                # 提取 ticker
                result["_ticker"] = result["代码"].astype(str).str.split(".").str[-1].str.strip()

                # 过滤 ticker（如果指定）
                if tickers:
                    result = result[result["_ticker"].isin(tickers)]

                log.success(ticker_count=len(result))
                logger.info(f"AKShare 行情获取成功: {len(result)} 只")
                return result

            except Exception as e:
                log.fail(error=str(e))
                logger.error(f"AKShare 行情获取失败: {e}")
                return None

    def fetch_valuations(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        从百度获取美股估值数据。

        API: stock_us_valuation_baidu(symbol=ticker)

        Args:
            tickers: 股票代码列表

        Returns:
            {ticker: {pe: float, pb: float}}
        """
        result: dict[str, dict[str, Any]] = {}
        failed = 0

        with log_provider_call("akshare", "stock_us_valuation_baidu") as log:
            try:
                import akshare as ak

                session = self.get_session()

                for i, ticker in enumerate(tickers):
                    try:
                        df = ak.stock_us_valuation_baidu(symbol=ticker)
                        if df is not None and not df.empty:
                            record = {}
                            pe = safe_float(df.iloc[0].get("pe"))
                            if pe is not None and pe > 0:
                                record["pe"] = pe
                            pb = safe_float(df.iloc[0].get("pb"))
                            if pb is not None and pb > 0:
                                record["pb"] = pb
                            if record:
                                result[ticker] = record

                        # 请求间隔，避免被限流
                        if i < len(tickers) - 1:
                            time.sleep(0.5)

                    except Exception as e:
                        failed += 1
                        if failed <= 3:
                            logger.warning(f"百度估值获取失败 {ticker}: {e}")

                log.success(ticker_count=len(tickers), success_count=len(result), failed=failed)
                logger.info(f"百度估值获取完成: {len(result)}/{len(tickers)} 成功, {failed} 失败")

            except Exception as e:
                log.fail(error=str(e))
                logger.error(f"百度估值模块初始化失败: {e}")

        return result

    def fetch_fundamentals(
        self, tickers: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        AKShare 不提供基本面数据，返回空。

        Args:
            tickers: 股票代码列表

        Returns:
            空 dict
        """
        logger.info("AKShare 不提供基本面数据，跳过")
        return {}

    def health_check(self) -> bool:
        """检查 AKShare 是否可用。"""
        try:
            import akshare as ak
            return True
        except ImportError:
            logger.warning("AKShare 未安装")
            return False
        except Exception as e:
            logger.warning(f"AKShare 健康检查失败: {e}")
            return False


# 自动注册
register_provider(AKShareProvider())
