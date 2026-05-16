"""
从 Wikipedia 获取最新 S&P 500 成分股列表。

数据源：https://en.wikipedia.org/wiki/List_of_S%26P_500_companies

字段映射：
  Symbol           → ticker
  Security         → name（英文名，优先保留旧数据中的中文名）
  GICS Sector      → sector
  GICS Sub-Industry → industry

Ticker 格式兼容：
  BRK.B → 保留 BRK.B（yfinance 兼容 BRK-B）
  BF.B  → 保留 BF.B（yfinance 兼容 BF-B）

用法：
    python -m collector.fetch_sp500_wikipedia
"""

import io
import os
import sys
from pathlib import Path

import pandas as pd
import requests

# 文件路径
DATA_DIR = Path("data")
SP500_CSV = DATA_DIR / "sp500_symbols.csv"
SP500_BACKUP_CSV = Path("data/us_stocks/sp500_symbols.csv")

# Wikipedia S&P 500 页面
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# 预期列名映射（Wikipedia 表格列名 → 标准字段）
COLUMN_MAP = {
    "Symbol": "ticker",
    "Security": "name",
    "GICS Sector": "sector",
    "GICS Sub-Industry": "industry",
}


def _get_proxies() -> dict | None:
    """从 config 或环境变量获取代理配置。"""
    try:
        from config.config import PROXY_CONFIG
        if PROXY_CONFIG:
            print(f"  使用代理: {PROXY_CONFIG.get('http', 'N/A')}")
            return PROXY_CONFIG
    except (ImportError, AttributeError):
        pass
    # 环境变量兜底
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if http_proxy or https_proxy:
        proxies = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        print(f"  使用环境变量代理: {proxies}")
        return proxies
    return None


def fetch_from_wikipedia() -> pd.DataFrame | None:
    """从 Wikipedia 获取 S&P 500 成分股列表。"""
    print(f"正在从 Wikipedia 获取 S&P 500 成分股列表...")
    print(f"  URL: {WIKIPEDIA_URL}")

    try:
        # 使用 requests 下载 HTML（支持代理）
        proxies = _get_proxies()
        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        print(f"  正在下载 HTML...")
        resp = session.get(WIKIPEDIA_URL, timeout=30)
        resp.raise_for_status()
        html_content = resp.text
        print(f"  下载完成: {len(html_content)} bytes")

        # 从 HTML 内容解析表格（用 StringIO 包装，避免被当作文件路径）
        tables = pd.read_html(io.StringIO(html_content))
        print(f"  页面包含 {len(tables)} 个表格")

        # S&P 500 成分股表格通常是第一个表格
        # 检查哪个表格包含 "Symbol" 列
        target_table = None
        for i, table in enumerate(tables):
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols and "Security" in cols:
                target_table = table
                print(f"  找到成分股表格: 第 {i + 1} 个表格, {len(table)} 行")
                break

        if target_table is None:
            print("  ❌ 未找到包含 Symbol/Security 列的表格")
            return None

        df = target_table.copy()

        # 重命名列
        rename_map = {}
        for col in df.columns:
            col_str = str(col).strip()
            if col_str in COLUMN_MAP:
                rename_map[col] = COLUMN_MAP[col_str]

        if rename_map:
            df = df.rename(columns=rename_map)

        # 只保留需要的列
        keep_cols = [v for v in COLUMN_MAP.values() if v in df.columns]
        df = df[keep_cols].copy()

        # 清理数据
        for col in keep_cols:
            df[col] = df[col].astype(str).str.strip()

        # 过滤空 ticker
        before = len(df)
        df = df[df["ticker"].notna() & (df["ticker"] != "") & (df["ticker"] != "nan")]
        after = len(df)
        if before != after:
            print(f"  过滤空 ticker: {before} → {after}")

        print(f"  ✅ 成功获取 {len(df)} 只 S&P 500 成分股")
        return df

    except Exception as exc:
        print(f"  ❌ 从 Wikipedia 获取失败: {exc}")
        return None


def load_old_sp500(path: Path) -> pd.DataFrame | None:
    """加载旧的 S&P 500 CSV 文件。"""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
        print(f"  加载旧文件 {path.name}: {len(df)} 行")
        return df
    except Exception as exc:
        print(f"  加载旧文件 {path.name} 失败: {exc}")
        return None


def merge_with_old_names(
    new_df: pd.DataFrame, old_df: pd.DataFrame | None
) -> pd.DataFrame:
    """
    将 Wikipedia 新数据与旧数据合并，保留旧数据中的中文名。

    策略：
    1. Wikipedia 数据为主（ticker, sector, industry 以 Wikipedia 为准）
    2. 旧数据中已有的 ticker，保留其 name（中文名）
    3. 新 ticker 使用 Wikipedia 的英文名
    """
    if old_df is None or old_df.empty:
        return new_df

    # 构建旧数据 ticker → name 映射
    old_names = {}
    for _, row in old_df.iterrows():
        ticker = str(row.get("ticker", "")).strip()
        name = str(row.get("name", "")).strip()
        if ticker and name:
            old_names[ticker] = name

    print(f"  旧数据中有中文名的 ticker: {len(old_names)} 个")

    # 对 Wikipedia 数据，如果旧数据有中文名则使用
    name_replace_count = 0
    for i, row in new_df.iterrows():
        ticker = row.get("ticker", "")
        if ticker in old_names:
            new_df.at[i, "name"] = old_names[ticker]
            name_replace_count += 1

    print(f"  保留中文名: {name_replace_count} 个 ticker")
    return new_df


def main():
    """主流程：从 Wikipedia 获取 S&P 500 成分股列表并写入 CSV。"""
    print("=" * 50)
    print("S&P 500 成分股列表更新（Wikipedia 源）")
    print("=" * 50)

    # 步骤 1: 从 Wikipedia 获取
    print(f"\n{'─' * 40}")
    print("步骤 1/3: 从 Wikipedia 获取成分股列表")
    wiki_df = fetch_from_wikipedia()
    if wiki_df is None or wiki_df.empty:
        print("❌ 获取失败，终止")
        sys.exit(1)

    # 步骤 2: 加载旧数据，保留中文名
    print(f"\n{'─' * 40}")
    print("步骤 2/3: 合并旧数据中的中文名")
    old_df = load_old_sp500(SP500_CSV)
    merged_df = merge_with_old_names(wiki_df, old_df)

    # 去重（按 ticker）
    before_dedup = len(merged_df)
    merged_df = merged_df.drop_duplicates(subset=["ticker"])
    after_dedup = len(merged_df)
    if before_dedup != after_dedup:
        print(f"  去重: {before_dedup} → {after_dedup}")

    # 按 ticker 排序
    merged_df = merged_df.sort_values(by="ticker").reset_index(drop=True)

    # 步骤 3: 统计并写入
    print(f"\n{'─' * 40}")
    print("步骤 3/3: 统计与写入")

    total = len(merged_df)
    has_name = merged_df["name"].str.len() > 0
    has_sector = merged_df["sector"].str.len() > 0
    has_industry = merged_df["industry"].str.len() > 0

    print(f"\n  总股票数: {total}")
    print(f"  有 name: {has_name.sum()} ({has_name.sum()/total*100:.1f}%)")
    print(f"  有 sector: {has_sector.sum()} ({has_sector.sum()/total*100:.1f}%)")
    print(f"  有 industry: {has_industry.sum()} ({has_industry.sum()/total*100:.1f}%)")

    # Sector 分布
    print(f"\n  Sector 分布:")
    sector_counts = merged_df["sector"].value_counts()
    for sector, count in sector_counts.items():
        print(f"    {sector}: {count}")

    # 检查特殊 ticker 格式
    dot_tickers = merged_df[merged_df["ticker"].str.contains(r"\.")]
    if not dot_tickers.empty:
        print(f"\n  含 '.' 的 ticker ({len(dot_tickers)} 个):")
        for _, row in dot_tickers.iterrows():
            print(f"    {row['ticker']} - {row['name']}")

    # 写入 data/sp500_symbols.csv
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(SP500_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ 已写入: {SP500_CSV}")

    # 同步写入 data/us_stocks/sp500_symbols.csv（只保留 ticker, name）
    backup_dir = Path("data/us_stocks")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_df = merged_df[["ticker", "name"]].copy()
    backup_df.to_csv(SP500_BACKUP_CSV, index=False, encoding="utf-8-sig")
    print(f"  ✅ 已同步备份: {SP500_BACKUP_CSV}")

    print(f"\n{'=' * 50}")
    print("S&P 500 成分股列表更新成功")
    print(f"  旧 ticker 数量: {len(old_df) if old_df is not None else 0}")
    print(f"  新 ticker 数量: {total}")
    print(f"  新增 ticker: {total - (len(old_df) if old_df is not None else 0)}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
