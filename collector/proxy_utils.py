"""
统一代理、超时、重试工具模块。

为所有海外 API 请求提供统一的 proxy 配置、超时控制、重试机制和 provider 日志。

支持的 proxy 配置方式（优先级从高到低）：
1. PROXY_CONFIG 字典（从 config 模块导入）
2. HTTP_PROXY / HTTPS_PROXY 环境变量
3. 无代理（直连）

用法：
    from collector.proxy_utils import (
        get_requests_session,
        get_httpx_client,
        patch_yfinance_session,
        log_provider_call,
        ProviderLog,
    )

    # requests
    session = get_requests_session()
    resp = session.get("https://api.example.com")

    # httpx
    client = get_httpx_client()
    resp = client.get("https://api.example.com")

    # yfinance
    patch_yfinance_session()
    import yfinance as yf
    stock = yf.Ticker("AAPL")

    # provider 日志
    with log_provider_call("yfinance", "fetch_fundamentals") as log:
        result = do_something()
        log.success(ticker_count=500)
"""

import functools
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===== 日志配置 =====

logger = logging.getLogger("us_stocks.provider")

# ===== Proxy 配置 =====

# 默认代理地址（mihomo 代理）
DEFAULT_PROXY = "http://127.0.0.1:7890"

# 不需要走代理的域名列表
NO_PROXY_DOMAINS = [
    "localhost",
    "127.0.0.1",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]


def get_proxy_config() -> dict[str, str]:
    """
    获取代理配置。

    优先级：
    1. 尝试从 config 模块导入 PROXY_CONFIG
    2. 环境变量 HTTP_PROXY / HTTPS_PROXY
    3. 默认代理 127.0.0.1:7890

    Returns:
        {"http": "...", "https": "..."} 或空字典（无代理）
    """
    # 尝试从 config 导入
    try:
        from config.config import PROXY_CONFIG

        if PROXY_CONFIG and isinstance(PROXY_CONFIG, dict):
            http_proxy = PROXY_CONFIG.get("http") or PROXY_CONFIG.get("HTTP_PROXY")
            https_proxy = PROXY_CONFIG.get("https") or PROXY_CONFIG.get("HTTPS_PROXY")
            if http_proxy or https_proxy:
                result = {}
                if http_proxy:
                    result["http"] = http_proxy
                if https_proxy:
                    result["https"] = https_proxy
                return result
    except (ImportError, AttributeError):
        pass

    # 尝试从 config.example 导入
    try:
        from config.config_example import PROXY_CONFIG

        if PROXY_CONFIG and isinstance(PROXY_CONFIG, dict):
            http_proxy = PROXY_CONFIG.get("http") or PROXY_CONFIG.get("HTTP_PROXY")
            https_proxy = PROXY_CONFIG.get("https") or PROXY_CONFIG.get("HTTPS_PROXY")
            if http_proxy or https_proxy:
                result = {}
                if http_proxy:
                    result["http"] = http_proxy
                if https_proxy:
                    result["https"] = https_proxy
                return result
    except (ImportError, AttributeError):
        pass

    # 环境变量
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    if http_proxy or https_proxy:
        result = {}
        if http_proxy:
            result["http"] = http_proxy
        if https_proxy:
            result["https"] = https_proxy
        return result

    # 默认代理
    return {
        "http": DEFAULT_PROXY,
        "https": DEFAULT_PROXY,
    }


def is_proxy_available(proxy_url: str = DEFAULT_PROXY, timeout: int = 5) -> bool:
    """
    检测代理是否可用。

    Args:
        proxy_url: 代理地址
        timeout: 超时秒数

    Returns:
        True 如果代理可用
    """
    try:
        test_url = "https://www.google.com"
        resp = requests.get(
            test_url,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=timeout,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ===== requests Session 工厂 =====


def get_requests_session(
    timeout: int = 30,
    retries: int = 3,
    backoff_factor: float = 1.0,
    use_proxy: bool = True,
) -> requests.Session:
    """
    创建配置了 proxy、timeout、retry 的 requests Session。

    Args:
        timeout: 请求超时秒数
        retries: 最大重试次数
        backoff_factor: 重试退避因子（秒）
        use_proxy: 是否使用代理

    Returns:
        配置好的 requests.Session
    """
    session = requests.Session()

    # 重试策略
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 代理配置
    if use_proxy:
        proxy_config = get_proxy_config()
        if proxy_config:
            session.proxies.update(proxy_config)

    # 默认超时
    session.timeout = timeout

    # 默认 headers
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )

    return session


# ===== httpx Client 工厂 =====


def get_httpx_client(
    timeout: int = 30,
    retries: int = 3,
    use_proxy: bool = True,
):
    """
    创建配置了 proxy、timeout 的 httpx Client。

    注意：httpx 的重试需要额外配置，这里只设置超时和代理。

    Args:
        timeout: 请求超时秒数
        retries: 最大重试次数（httpx 原生不支持，这里仅记录）
        use_proxy: 是否使用代理

    Returns:
        配置好的 httpx.Client 或 None（如果 httpx 未安装）
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx 未安装，无法创建 httpx Client")
        return None

    # 超时配置
    timeout_config = httpx.Timeout(timeout, connect=timeout, read=timeout, write=timeout)

    # 代理配置
    proxy_url = None
    if use_proxy:
        proxy_config = get_proxy_config()
        if proxy_config:
            proxy_url = proxy_config.get("https") or proxy_config.get("http")

    client_kwargs = {
        "timeout": timeout_config,
        "follow_redirects": True,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    }

    if proxy_url:
        client_kwargs["proxies"] = proxy_url

    return httpx.Client(**client_kwargs)


# ===== yfinance Session 补丁 =====


def patch_yfinance_session(use_proxy: bool = True) -> bool:
    """
    为 yfinance 设置代理 session。

    通过替换 yfinance 的默认 session 创建方式，使其请求走代理。

    Args:
        use_proxy: 是否使用代理

    Returns:
        True 如果 patch 成功，False 如果 yfinance 未安装或 patch 失败
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，无法 patch session")
        return False

    try:
        session = get_requests_session(use_proxy=use_proxy)

        # yfinance 使用 requests.Session 进行所有 HTTP 请求
        # 通过替换默认 session 来实现代理
        original_ticker = yf.Ticker

        class PatchedTicker(original_ticker):
            def __init__(self, ticker, session=None):
                super().__init__(ticker, session=session or session)

        yf.Ticker = PatchedTicker
        logger.info("yfinance session 已 patch，代理已启用")
        return True
    except Exception as exc:
        logger.warning(f"yfinance session patch 失败: {exc}")
        return False


# ===== Provider 日志 =====


@dataclass
class ProviderLog:
    """Provider 调用日志记录。"""

    provider: str
    action: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: str = "unknown"
    ticker_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def success(self, ticker_count: int = 0, success_count: int = 0, **kwargs):
        """标记为成功。"""
        self.status = "success"
        self.end_time = time.time()
        self.ticker_count = ticker_count or success_count
        self.success_count = success_count or ticker_count
        self.extra.update(kwargs)
        self._log()

    def fail(self, error: str, ticker_count: int = 0, **kwargs):
        """标记为失败。"""
        self.status = "fail"
        self.end_time = time.time()
        self.error = error
        self.ticker_count = ticker_count
        self.extra.update(kwargs)
        self._log()

    @property
    def duration_ms(self) -> float:
        """响应时间（毫秒）。"""
        if self.start_time and self.end_time:
            return round((self.end_time - self.start_time) * 1000, 2)
        return 0.0

    def _log(self):
        """输出格式化日志。"""
        duration = self.duration_ms
        ticker_info = f"tickers={self.ticker_count}" if self.ticker_count else ""
        success_info = (
            f" success={self.success_count} failed={self.failed_count}"
            if self.success_count or self.failed_count
            else ""
        )
        error_info = f" error={self.error}" if self.error else ""

        msg = (
            f"[Provider] {self.provider}.{self.action} "
            f"status={self.status}"
            f" duration={duration}ms"
            f"{ticker_info}{success_info}{error_info}"
        )

        if self.status == "success":
            logger.info(msg)
        else:
            logger.error(msg)

        # 同时 print 到控制台（兼容现有日志方式）
        prefix = "✅" if self.status == "success" else "❌"
        print(f"  {prefix} {self.provider}.{self.action}: {self.status} ({duration}ms){error_info}")


@contextmanager
def log_provider_call(provider: str, action: str, **kwargs):
    """
    Provider 调用日志上下文管理器。

    用法：
        with log_provider_call("yfinance", "fetch_fundamentals") as log:
            result = do_something()
            log.success(ticker_count=500)
            # 或 log.fail(error="rate limited", ticker_count=500)
    """
    log = ProviderLog(provider=provider, action=action, **kwargs)
    try:
        yield log
    except Exception as exc:
        log.fail(error=str(exc))
        raise


def provider_call(provider: str, action: str):
    """
    Provider 调用日志装饰器。

    用法：
        @provider_call("yfinance", "fetch_fundamentals")
        def fetch_fundamentals(tickers):
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with log_provider_call(provider, action) as log:
                try:
                    result = func(*args, **kwargs)
                    if isinstance(result, dict):
                        log.success(ticker_count=len(result))
                    elif hasattr(result, "__len__"):
                        log.success(ticker_count=len(result))
                    else:
                        log.success()
                    return result
                except Exception as exc:
                    log.fail(error=str(exc))
                    raise

        return wrapper

    return decorator


# ===== 便捷函数 =====


def check_proxy_and_log() -> bool:
    """检测代理可用性并输出日志。"""
    proxy_config = get_proxy_config()
    proxy_url = proxy_config.get("https") or proxy_config.get("http", DEFAULT_PROXY)
    available = is_proxy_available(proxy_url)

    if available:
        print(f"✅ 代理可用: {proxy_url}")
    else:
        print(f"⚠️  代理不可用: {proxy_url}，将尝试直连")

    return available
