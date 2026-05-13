"""
S&P 500 成分股列表更新脚本。

从本地已有数据源合并去重，生成完整的 S&P 500 成分股列表。

数据源（按优先级）：
1. data/sp500_symbols.csv - 主成分股列表
2. data/us_stocks/latest.json - 美股评分缓存数据（含 sector 信息）
3. data/us_stocks/sp500_symbols.csv - 备份成分股列表

用法：
    python -m collector.update_sp500_list
"""

import json
import sys
from pathlib import Path

import pandas as pd

# 文件路径
DATA_DIR = Path("data")
SP500_CSV = DATA_DIR / "sp500_symbols.csv"
SP500_BACKUP_CSV = Path("data/us_stocks/sp500_symbols.csv")
LATEST_JSON = Path("data/us_stocks/latest.json")


def load_sp500_csv(path: Path) -> pd.DataFrame | None:
    """加载 S&P 500 CSV 文件。"""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
        print(f"  加载 {path.name}: {len(df)} 行")
        return df
    except Exception as exc:
        print(f"  加载 {path.name} 失败: {exc}")
        return None


def load_latest_json(path: Path) -> pd.DataFrame | None:
    """加载 latest.json 文件。"""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return None
        df = pd.DataFrame(data)
        print(f"  加载 {path.name}: {len(df)} 行")
        return df
    except Exception as exc:
        print(f"  加载 {path.name} 失败: {exc}")
        return None


def main():
    """主流程：合并去重，生成完整的 S&P 500 成分股列表。"""
    print("=" * 50)
    print("S&P 500 成分股列表更新")
    print("=" * 50)

    # 加载所有数据源
    print(f"\n{'─' * 40}")
    print("加载数据源:")

    df_main = load_sp500_csv(SP500_CSV)
    df_backup = load_sp500_csv(SP500_BACKUP_CSV)
    df_latest = load_latest_json(LATEST_JSON)

    # 构建 ticker → 记录 的映射（按优先级合并）
    # 优先级：latest.json > sp500_symbols.csv > us_stocks/sp500_symbols.csv
    records: dict[str, dict] = {}

    # 1. 从 latest.json 获取（最高优先级，含 sector）
    if df_latest is not None and not df_latest.empty:
        for _, row in df_latest.iterrows():
            ticker = str(row.get("code", "")).strip()
            if not ticker:
                continue
            records[ticker] = {
                "ticker": ticker,
                "name": str(row.get("name", "")).strip(),
                "sector": str(row.get("sector", "")).strip(),
                "industry": "",  # latest.json 没有 industry
            }

    # 2. 从 sp500_symbols.csv 补充（次优先级，有中文名和 sector）
    if df_main is not None and not df_main.empty:
        for _, row in df_main.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            name = str(row.get("name", "")).strip()
            sector = str(row.get("sector", "")).strip()
            industry = str(row.get("industry", "")).strip()

            if ticker in records:
                # 补充缺失字段
                if name and not records[ticker]["name"]:
                    records[ticker]["name"] = name
                if sector and not records[ticker]["sector"]:
                    records[ticker]["sector"] = sector
                if industry and not records[ticker]["industry"]:
                    records[ticker]["industry"] = industry
            else:
                records[ticker] = {
                    "ticker": ticker,
                    "name": name,
                    "sector": sector,
                    "industry": industry,
                }

    # 3. 从备份 CSV 补充（最低优先级）
    if df_backup is not None and not df_backup.empty:
        for _, row in df_backup.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            name = str(row.get("name", "")).strip()

            if ticker in records:
                if name and not records[ticker]["name"]:
                    records[ticker]["name"] = name
            else:
                records[ticker] = {
                    "ticker": ticker,
                    "name": name,
                    "sector": "",
                    "industry": "",
                }

    # 转为 DataFrame
    result_df = pd.DataFrame(list(records.values()))

    # 按 ticker 排序
    result_df = result_df.sort_values(by="ticker").reset_index(drop=True)

    # 统计
    total = len(result_df)
    sector_counts = result_df["sector"].value_counts().to_dict()
    has_sector = result_df["sector"].str.len() > 0
    has_industry = result_df["industry"].str.len() > 0

    print(f"\n{'─' * 40}")
    print(f"合并完成: {total} 只股票")
    print(f"  有 sector 分类: {has_sector.sum()} 只 ({has_sector.sum()/total*100:.1f}%)")
    print(f"  有 industry 分类: {has_industry.sum()} 只")
    print(f"\n板块分布:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        if sector:
            print(f"  {sector}: {count}")
        else:
            print(f"  (未分类): {count}")

    # 写入 data/sp500_symbols.csv
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(SP500_CSV, index=False, encoding="utf-8-sig")
    print(f"\n✅ 已写入: {SP500_CSV}")

    # 同步写入 data/us_stocks/sp500_symbols.csv（只保留 ticker, name）
    backup_dir = Path("data/us_stocks")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_df = result_df[["ticker", "name"]].copy()
    backup_df.to_csv(SP500_BACKUP_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ 已同步备份: {SP500_BACKUP_CSV}")

    print(f"\n{'=' * 50}")
    print("S&P 500 成分股列表更新成功")
    print(f"  总股票数: {total}")
    print(f"  字段: ticker, name, sector, industry")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
