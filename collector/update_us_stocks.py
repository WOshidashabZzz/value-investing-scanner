"""
美股数据离线更新脚本。

数据源优先级（通过 Provider 架构）：
1. AKShare stock_us_spot_em() - 东方财富美股实时行情（主数据源，priority=10）
2. AKShare stock_us_valuation_baidu() - 百度美股估值（补充 PE/PB，priority=10）
3. yfinance - 补充基本面数据（ROE、增长率、股息率等，priority=20）
4. Alpha Vantage - 预留备用接口

使用 staging/latest/backup 安全更新机制。
只保留 latest 和 backup 两份数据。

用法：
    python -m collector.update_us_stocks
    python -m collector.update_us_stocks --force  # 强制重新采集所有数据
"""

import argparse
import json
import logging
import math
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from collector.proxy_utils import (
    check_proxy_and_log,
    get_requests_session,
    log_provider_call,
    patch_yfinance_session,
)

from api.us_stock_schema import (
    normalize_akshare_spot,
    normalize_baidu_valuation,
    normalize_yfinance_fundamentals,
    merge_records,
    safe_float,
    normalize_record,
)

# Provider 架构
from collector.providers import (
    get_best_provider,
    get_provider,
    get_all_providers,
)

# ===== 日志配置 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("us_stocks.update")

# ===== 数据目录（使用 cache_manager） =====
from collector.cache_manager import (
    ensure_dirs,
    read_latest,
    write_latest,
    read_staging,
    write_staging,
    read_backup,
    write_backup,
    read_raw_spot,
    write_raw_spot,
    read_raw_baidu,
    write_raw_baidu,
    read_raw_yfinance,
    write_raw_yfinance,
    safe_update,
    rollback,
    get_cache_stats,
    DATA_DIR,
    LATEST_FILE,
    STAGING_FILE,
    BACKUP_FILE,
)

# S&P 500 成分股列表
SP500_CSV = Path("data/sp500_symbols.csv")

# 最小有效股票数量（S&P 500 的 90%）
MIN_STOCK_COUNT = 450

# 核心字段列表
REQUIRED_FIELDS = ["code", "name", "pe", "pb"]

# 请求会话（全局复用）
_session = None


def get_session():
    """获取全局 requests session（带 proxy/retry/timeout）。"""
    global _session
    if _session is None:
        _session = get_requests_session(timeout=30, retries=3)
    return _session


# ===== 目录管理 =====


def ensure_data_dir():
    """确保数据目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ===== S&P 500 成分股加载 =====


def load_sp500_symbols() -> pd.DataFrame:
    """加载 S&P 500 成分股列表（自动去重）。"""
    if not SP500_CSV.exists():
        raise FileNotFoundError(f"S&P 500 成分股列表不存在: {SP500_CSV}")

    df = pd.read_csv(SP500_CSV, dtype=str)
    df = df.fillna("")
    # 按 ticker 去重，保留第一个出现的记录
    before = len(df)
    df = df.drop_duplicates(subset=["ticker"])
    after = len(df)
    if before != after:
        print(f"去重: {before} → {after}（移除 {before - after} 个重复 ticker）")
    print(f"已加载 S&P 500 成分股: {len(df)} 只")
    return df


# ===== AKShare 数据源 =====


def fetch_us_spot_from_akshare() -> pd.DataFrame | None:
    """
    使用 AKShare stock_us_spot_em() 获取美股实时行情。

    返回字段：代码、名称、最新价、市盈率、总市值等。
    AKShare 返回的列名：序号、名称、最新价、涨跌额、涨跌幅、开盘价、最高价、最低价、昨收价、总市值、市盈率、成交量、成交额、振幅、换手率、代码
    其中"代码"列格式为 "106.AAPL"（前缀.股票代码），"名称"列为公司简称。
    """
    with log_provider_call("akshare", "stock_us_spot_em") as log:
        try:
            import akshare as ak

            df = ak.stock_us_spot_em()
            if df is None or df.empty:
                log.fail(error="返回空数据")
                return None

            # 统一列名：AKShare 不同版本可能返回不同列名
            column_rename = {}
            if "简称" in df.columns and "名称" not in df.columns:
                column_rename["简称"] = "名称"
            if "编码" in df.columns and "代码" not in df.columns:
                column_rename["编码"] = "代码"

            if column_rename:
                df = df.rename(columns=column_rename)

            log.success(ticker_count=len(df))
            print(f"AKShare 东方财富行情: 获取到 {len(df)} 只股票")
            return df
        except Exception as exc:
            log.fail(error=str(exc))
            print(f"AKShare stock_us_spot_em() 失败: {exc}")
            return None


def fetch_us_valuation_from_baidu(ticker: str) -> dict:
    """
    使用 AKShare stock_us_valuation_baidu() 获取单只美股的估值数据。

    可获取：市盈率(TTM)、市净率、总市值等。
    """
    try:
        import akshare as ak

        result = {}
        # 获取市盈率(TTM)
        try:
            pe_df = ak.stock_us_valuation_baidu(
                symbol=ticker, indicator="市盈率(TTM)", period="近一年"
            )
            if pe_df is not None and not pe_df.empty:
                latest_pe = pe_df["value"].iloc[-1]
                if pd.notna(latest_pe) and latest_pe > 0:
                    result["pe"] = round(float(latest_pe), 2)
        except Exception:
            pass

        # 获取市净率
        try:
            pb_df = ak.stock_us_valuation_baidu(
                symbol=ticker, indicator="市净率", period="近一年"
            )
            if pb_df is not None and not pb_df.empty:
                latest_pb = pb_df["value"].iloc[-1]
                if pd.notna(latest_pb) and latest_pb > 0:
                    result["pb"] = round(float(latest_pb), 2)
        except Exception:
            pass

        return result
    except Exception as exc:
        print(f"  百度估值查询失败 {ticker}: {exc}")
        return {}


def fetch_us_valuations_baidu_batch(tickers: list[str]) -> dict[str, dict]:
    """
    批量查询百度估值数据。

    由于百度接口按 ticker 逐个查询，速度较慢，只对 spot 中缺失的数据补充。
    """
    with log_provider_call("akshare", "stock_us_valuation_baidu") as log:
        results = {}
        total = len(tickers)
        failed = 0
        for i, ticker in enumerate(tickers):
            if (i + 1) % 50 == 0:
                print(f"  百度估值进度: {i + 1}/{total}")
            result = fetch_us_valuation_from_baidu(ticker)
            if result:
                results[ticker] = result
            else:
                failed += 1
            time.sleep(0.3)  # 避免请求过快

        log.success(
            ticker_count=total,
            success_count=len(results),
            failed_count=failed,
        )
        return results


# ===== yfinance 兜底数据源 =====


def fetch_fundamentals_from_yfinance(ticker: str) -> dict:
    """
    使用 yfinance 获取单只美股的基本面数据。

    获取：ROE、营收增长率、利润增长率、股息率等。
    """
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info = stock.info

        if not info:
            return {}

        result = {}

        # ROE
        roe = info.get("returnOnEquity")
        if roe is not None:
            result["roe"] = round(float(roe) * 100, 2)  # 转为百分比

        # 营收增长率
        revenue_growth = info.get("revenueGrowth")
        if revenue_growth is not None:
            result["revenue_growth"] = round(float(revenue_growth) * 100, 2)

        # 利润增长率
        earnings_growth = info.get("earningsGrowth")
        if earnings_growth is not None:
            result["profit_growth"] = round(float(earnings_growth) * 100, 2)

        # 股息率
        dividend_yield = info.get("dividendYield")
        if dividend_yield is not None:
            result["dividend_yield"] = round(float(dividend_yield) * 100, 2)

        # PE（如果 AKShare 没获取到）
        if "pe" not in result:
            trailing_pe = info.get("trailingPE")
            if trailing_pe is not None and trailing_pe > 0:
                result["pe"] = round(float(trailing_pe), 2)

        # PB（如果 AKShare 没获取到）
        if "pb" not in result:
            price_to_book = info.get("priceToBook")
            if price_to_book is not None and price_to_book > 0:
                result["pb"] = round(float(price_to_book), 2)

        return result
    except Exception as exc:
        print(f"  yfinance 查询失败 {ticker}: {exc}")
        return {}


def fetch_fundamentals_yfinance_batch(
    tickers: list[str], max_workers: int = 5
) -> dict[str, dict]:
    """
    批量使用 yfinance 获取基本面数据。

    使用简单的串行方式，避免并发问题。
    """
    with log_provider_call("yfinance", "fetch_fundamentals") as log:
        results = {}
        total = len(tickers)
        failed = 0
        for i, ticker in enumerate(tickers):
            if (i + 1) % 20 == 0:
                print(f"  yfinance 进度: {i + 1}/{total}")
            result = fetch_fundamentals_from_yfinance(ticker)
            if result:
                results[ticker] = result
            else:
                failed += 1
            time.sleep(0.1)  # 避免请求过快

        log.success(
            ticker_count=total,
            success_count=len(results),
            failed_count=failed,
        )
        return results


# ===== 数据合并与评分 =====


def safe_float(value) -> float | None:
    """安全转换浮点数。"""
    if value is None:
        return None
    try:
        v = float(value)
        if pd.isna(v) or v == float("inf") or v == float("-inf"):
            return None
        return v
    except (TypeError, ValueError):
        return None


def merge_stock_data(
    sp500_df: pd.DataFrame,
    spot_data: pd.DataFrame | None,
    baidu_data: dict[str, dict],
    yfinance_data: dict[str, dict],
) -> pd.DataFrame:
    """
    合并多个数据源的美股数据。

    使用 us_stock_schema 标准化函数处理各数据源。
    优先级：AKShare spot > 百度估值 > yfinance
    """
    records = []

    for _, row in sp500_df.iterrows():
        ticker = str(row["ticker"]).strip()
        name = str(row["name"]).strip()
        sector = str(row["sector"]).strip()

        # 基础记录（来自 S&P 500 列表）
        base_record = {
            "code": ticker,
            "name": name,
            "sector": sector,
        }

        # 1. 从 AKShare spot 数据中获取
        spot_update: dict = {}
        if spot_data is not None and not spot_data.empty:
            spot_data["_ticker"] = spot_data["代码"].astype(str).str.split(".").str[-1].str.strip()
            spot_row = spot_data[spot_data["_ticker"] == ticker]
            if not spot_row.empty:
                spot = spot_row.iloc[0]
                spot_update = normalize_akshare_spot(spot.to_dict())

        # 2. 从百度估值补充
        baidu_update: dict = {}
        if ticker in baidu_data:
            baidu_update = normalize_baidu_valuation(baidu_data[ticker])

        # 3. 从 yfinance 补充基本面
        yfinance_update: dict = {}
        if ticker in yfinance_data:
            yfinance_update = normalize_yfinance_fundamentals(yfinance_data[ticker])

        # 合并：基础记录 + spot + 百度 + yfinance（后面覆盖前面）
        merged = merge_records(base_record, spot_update, baidu_update, yfinance_update)

        # 最终标准化
        record = normalize_record(merged, source="merge")
        records.append(record)

    result = pd.DataFrame(records)
    logger.info(f"数据合并完成: {len(result)} 条记录 (使用 us_stock_schema 标准化)")
    return result


def calculate_and_score(df: pd.DataFrame) -> pd.DataFrame:
    """对合并后的数据进行评分。"""
    from api.us_stock_utils import calculate_us_score

    if df.empty:
        return df

    # 评分
    scored = calculate_us_score(df)
    scored = scored.reset_index(drop=True)
    scored["rank"] = scored.index + 1

    # 添加 total_score 字段（前端使用 total_score，评分输出 final_score）
    scored["total_score"] = scored["final_score"]

    # 添加估值日期
    today = datetime.now().strftime("%Y-%m-%d")
    scored["valuation_date"] = today

    print(f"评分完成: {len(scored)} 只股票")
    return scored


# ===== staging 校验 =====


def validate_staging(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """
    校验 staging 数据质量。

    规则：
    1. 股票数量 >= 450
    2. 核心字段（code, name, pe, pb）非空比例 > 50%
    3. 评分可用性检查（final_score 不能全空）
    """
    errors = []

    # 规则1: 股票数量
    if len(df) < MIN_STOCK_COUNT:
        errors.append(
            f"股票数量不足: 当前 {len(df)}，要求 >= {MIN_STOCK_COUNT}"
        )
    else:
        print(f"✅ 股票数量检查通过: {len(df)}")

    # 规则2: 核心字段检查
    for field in REQUIRED_FIELDS:
        if field not in df.columns:
            errors.append(f"核心字段 '{field}' 不存在")
            continue
        valid_count = df[field].notna().sum()
        ratio = valid_count / len(df) if len(df) > 0 else 0
        if ratio < 0.5:
            errors.append(
                f"核心字段 '{field}' 非空比例过低: {ratio:.1%} ({valid_count}/{len(df)})"
            )
        else:
            print(f"  ✅ 字段 '{field}' 非空比例: {ratio:.1%}")

    # 规则3: 评分可用性
    if "final_score" in df.columns:
        valid_scores = df["final_score"].notna().sum()
        if valid_scores == 0:
            errors.append("所有股票的 final_score 均为空")
        else:
            print(f"✅ 评分可用性检查通过: {valid_scores}/{len(df)} 有评分")
    else:
        errors.append("缺少 final_score 字段")

    passed = len(errors) == 0
    if passed:
        print("🎉 所有校验规则通过")
    else:
        print("❌ 校验失败:")
        for err in errors:
            print(f"   - {err}")

    return passed, errors


# ===== 版本管理（使用 cache_manager） =====


def save_staging(df: pd.DataFrame):
    """将数据写入 staging 文件（使用 cache_manager）。"""
    ensure_dirs()
    records = df.to_dict(orient="records")
    # 清理 NaN / Inf 值（JSON 标准不支持）
    def clean(obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        elif isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean(v) for v in obj]
        return obj
    records = clean(records)
    write_staging(records)
    logger.info(f"staging 数据已写入: {STAGING_FILE} ({len(records)} 条)")


def promote_staging():
    """
    将 staging 提升为 latest，原 latest 降级为 backup。

    使用 cache_manager.safe_update 进行安全更新。
    """
    staging = read_staging()
    if staging is None:
        logger.warning("staging 文件不存在，无法提升")
        return False

    success, msg = safe_update(staging, min_count=MIN_STOCK_COUNT)
    if success:
        # 删除 staging
        if STAGING_FILE.exists():
            STAGING_FILE.unlink()
        logger.info(f"staging 已提升为 latest: {msg}")
        return True
    else:
        logger.error(f"提升失败: {msg}")
        return False


def rollback_staging():
    """删除 staging 数据，保留 latest/backup 不变。"""
    if STAGING_FILE.exists():
        STAGING_FILE.unlink()
        logger.info("staging 文件已删除（回滚）")
    else:
        logger.info("staging 文件不存在，无需回滚")


# ===== 主流程 =====


def _get_provider_data(
    method: str,
    tickers: list[str],
    label: str,
    fallback_func=None,
    fallback_args=None,
) -> tuple:
    """
    通过 Provider 架构获取数据，失败时自动 fallback。

    Args:
        method: 方法名 (spot, valuations, fundamentals)
        tickers: 股票代码列表
        label: 日志标签
        fallback_func: 可选的 fallback 函数
        fallback_args: fallback 函数参数

    Returns:
        (数据, 使用的 provider 名称)
    """
    provider = get_best_provider(method)
    if provider:
        print(f"  使用 Provider: {provider.name} (优先级 {provider.priority})")
        try:
            if method == "spot":
                data = provider.fetch_spot(tickers)
            elif method == "valuations":
                data = provider.fetch_valuations(tickers)
            elif method == "fundamentals":
                data = provider.fetch_fundamentals(tickers)
            else:
                data = None

            if data is not None and (isinstance(data, pd.DataFrame) and not data.empty) or (isinstance(data, dict) and data):
                return data, provider.name
            else:
                print(f"  ⚠️  Provider {provider.name} 返回空数据")
        except Exception as e:
            print(f"  ⚠️  Provider {provider.name} 失败: {e}")
    else:
        print(f"  ⚠️  无可用 Provider (method={method})")

    # Fallback
    if fallback_func and fallback_args is not None:
        print(f"  使用 fallback: {fallback_func.__name__}")
        data = fallback_func(*fallback_args)
        return data, "fallback"

    return None, "none"


def main(force: bool = False):
    """
    美股数据更新主流程。

    使用 Provider 架构获取数据，支持自动 fallback。

    Args:
        force: 是否强制重新采集所有数据（忽略缓存）
    """
    print("=" * 50)
    print("美股数据更新任务启动")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 打印已注册的 Provider
    providers = get_all_providers()
    if providers:
        print(f"已注册 Provider: {', '.join(f'{p.name}({p.priority})' for p in providers)}")
    else:
        print("⚠️  未注册任何 Provider，将使用传统方式")

    # 检测代理可用性
    proxy_available = check_proxy_and_log()
    if proxy_available:
        # patch yfinance session 使用代理
        patch_yfinance_session()
    else:
        print("⚠️  代理不可用，yfinance 请求可能失败")

    # 加载 S&P 500 成分股
    sp500_df = load_sp500_symbols()
    tickers = sp500_df["ticker"].tolist()
    print(f"待处理股票: {len(tickers)} 只")

    # 阶段1: 行情数据（通过 Provider）
    print(f"\n{'─' * 40}")
    print("阶段 1/4: 美股行情数据")
    spot_data, spot_provider = _get_provider_data(
        "spot", tickers, "行情",
        fallback_func=fetch_us_spot_from_akshare,
        fallback_args=[],
    )
    print(f"  行情数据来源: {spot_provider}, 获取到: {len(spot_data) if spot_data is not None else 0} 只")

    # 阶段2: 估值补充
    print(f"\n{'─' * 40}")
    print("阶段 2/4: 估值数据补充")
    # 只对 spot 中缺失 PE/PB 的股票查询估值
    missing_pe_tickers = []
    if spot_data is not None:
        # 从"代码"列提取 ticker（去掉前缀，如 "106.AAPL" → "AAPL"）
        spot_data["_ticker"] = spot_data["代码"].astype(str).str.split(".").str[-1].str.strip()
        for ticker in tickers:
            spot_row = spot_data[spot_data["_ticker"] == ticker]
            if spot_row.empty:
                missing_pe_tickers.append(ticker)
            else:
                pe = safe_float(spot_row.iloc[0].get("市盈率"))
                if pe is None or pe <= 0:
                    missing_pe_tickers.append(ticker)
    else:
        missing_pe_tickers = tickers

    print(f"需要补充 PE/PB 的股票: {len(missing_pe_tickers)} 只")
    baidu_data = {}
    val_provider = "none"
    if missing_pe_tickers:
        baidu_data, val_provider = _get_provider_data(
            "valuations", missing_pe_tickers, "估值",
            fallback_func=fetch_us_valuations_baidu_batch,
            fallback_args=[missing_pe_tickers],
        )
        print(f"  估值数据来源: {val_provider}, 获取到: {len(baidu_data)} 只")
    else:
        print("  所有股票已有 PE/PB，跳过估值补充")

    # 阶段3: 基本面数据
    print(f"\n{'─' * 40}")
    print("阶段 3/4: 基本面数据补充")
    print(f"正在获取 {len(tickers)} 只股票的基本面数据...")
    yfinance_data, fund_provider = _get_provider_data(
        "fundamentals", tickers, "基本面",
        fallback_func=fetch_fundamentals_yfinance_batch,
        fallback_args=[tickers],
    )
    print(f"  基本面数据来源: {fund_provider}, 获取到: {len(yfinance_data)} 只")

    # 阶段4: 数据合并、评分、写入 staging
    print(f"\n{'─' * 40}")
    print("阶段 4/4: 数据合并与评分")
    merged_df = merge_stock_data(sp500_df, spot_data, baidu_data, yfinance_data)
    scored_df = calculate_and_score(merged_df)

    # 写入 staging
    save_staging(scored_df)

    # 校验 staging
    print(f"\n{'─' * 40}")
    print("校验 staging 数据")
    passed, errors = validate_staging(scored_df)

    if passed:
        # 提升为 latest
        promote_staging()
        print("\n✅ 美股数据更新成功完成")
    else:
        # 回滚
        rollback_staging()
        print("\n❌ 美股数据更新失败，已回滚 staging")

    # 打印统计
    print(f"\n{'─' * 40}")
    print("更新统计:")
    print(f"  S&P 500 成分股: {len(sp500_df)}")
    print(f"  行情数据 ({spot_provider}): {len(spot_data) if spot_data is not None else 0}")
    print(f"  估值补充 ({val_provider}): {len(baidu_data)}")
    print(f"  基本面 ({fund_provider}): {len(yfinance_data)}")
    print(f"  最终评分: {len(scored_df)}")
    if not scored_df.empty and "final_score" in scored_df.columns:
        valid = scored_df["final_score"].notna().sum()
        print(f"  有评分的股票: {valid}")

    return passed


def parse_args():
    parser = argparse.ArgumentParser(description="美股数据离线更新")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新采集所有数据",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(force=args.force)
