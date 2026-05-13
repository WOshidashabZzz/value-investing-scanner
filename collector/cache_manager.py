"""
美股缓存管理工具类。

职责：
1. 管理 data/us_stocks/ 下的目录结构
2. 提供 staging/latest/backup/raw 的读写接口
3. 支持增量更新（只更新有变化的股票）
4. 自动清理过期缓存
5. 兼容现有 staging.json / latest.json / backup.json 文件

目录结构：
    data/us_stocks/
    ├── latest.json          # 当前最新数据（供 API 读取）
    ├── staging.json         # 暂存数据（更新中）
    ├── backup.json          # 上一次成功的数据备份
    ├── raw/                 # 各数据源原始数据缓存
    │   ├── spot_latest.json
    │   ├── baidu_latest.json
    │   └── yfinance_latest.json
    └── cache/               # 旧缓存目录（只读，兼容保留）
        ├── daily_cache.json
        └── financial_cache.json
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("us_stocks.cache")

# ===== 目录定义 =====
DATA_DIR = Path("data/us_stocks")
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"  # 旧缓存目录，只读保留

# ===== 文件路径 =====
LATEST_FILE = DATA_DIR / "latest.json"
STAGING_FILE = DATA_DIR / "staging.json"
BACKUP_FILE = DATA_DIR / "backup.json"

# 原始数据缓存文件
RAW_SPOT_FILE = RAW_DIR / "spot_latest.json"
RAW_BAIDU_FILE = RAW_DIR / "baidu_latest.json"
RAW_YFINANCE_FILE = RAW_DIR / "yfinance_latest.json"

# 旧缓存文件（只读）
OLD_DAILY_CACHE = CACHE_DIR / "daily_cache.json"
OLD_FINANCIAL_CACHE = CACHE_DIR / "financial_cache.json"


# ============================================================
# 1. 目录初始化
# ============================================================


def ensure_dirs() -> None:
    """确保所有缓存目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # CACHE_DIR 已存在，不需要创建
    logger.info(f"缓存目录已就绪: {DATA_DIR}")


# ============================================================
# 2. JSON 读写工具
# ============================================================


def _read_json(path: Path) -> Any | None:
    """安全读取 JSON 文件。"""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"读取 {path} 失败: {e}")
        return None


def _write_json(path: Path, data: Any) -> bool:
    """安全写入 JSON 文件。"""
    try:
        # 先写入临时文件，再原子替换
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        tmp.replace(path)
        return True
    except (OSError, TypeError) as e:
        logger.error(f"写入 {path} 失败: {e}")
        return False


# ============================================================
# 3. 最新数据读写
# ============================================================


def read_latest() -> list[dict] | None:
    """读取 latest.json。"""
    return _read_json(LATEST_FILE)


def write_latest(records: list[dict]) -> bool:
    """写入 latest.json。"""
    return _write_json(LATEST_FILE, records)


def read_latest_df() -> pd.DataFrame | None:
    """读取 latest.json 并返回 DataFrame。"""
    data = read_latest()
    if data is None:
        return None
    return pd.DataFrame(data)


# ============================================================
# 4. 暂存数据读写
# ============================================================


def read_staging() -> list[dict] | None:
    """读取 staging.json。"""
    return _read_json(STAGING_FILE)


def write_staging(records: list[dict]) -> bool:
    """写入 staging.json。"""
    return _write_json(STAGING_FILE, records)


# ============================================================
# 5. 备份数据读写
# ============================================================


def read_backup() -> list[dict] | None:
    """读取 backup.json。"""
    return _read_json(BACKUP_FILE)


def write_backup(records: list[dict]) -> bool:
    """写入 backup.json。"""
    return _write_json(BACKUP_FILE, records)


# ============================================================
# 6. 原始数据缓存读写
# ============================================================


def read_raw_spot() -> list[dict] | None:
    """读取原始 spot 数据缓存。"""
    return _read_json(RAW_SPOT_FILE)


def write_raw_spot(records: list[dict]) -> bool:
    """写入原始 spot 数据缓存。"""
    return _write_json(RAW_SPOT_FILE, records)


def read_raw_baidu() -> dict[str, dict] | None:
    """读取原始百度估值数据缓存。"""
    return _read_json(RAW_BAIDU_FILE)


def write_raw_baidu(data: dict[str, dict]) -> bool:
    """写入原始百度估值数据缓存。"""
    return _write_json(RAW_BAIDU_FILE, data)


def read_raw_yfinance() -> dict[str, dict] | None:
    """读取原始 yfinance 数据缓存。"""
    return _read_json(RAW_YFINANCE_FILE)


def write_raw_yfinance(data: dict[str, dict]) -> bool:
    """写入原始 yfinance 数据缓存。"""
    return _write_json(RAW_YFINANCE_FILE, data)


# ============================================================
# 7. 安全更新机制
# ============================================================


def safe_update(
    new_records: list[dict],
    min_count: int = 450,
) -> tuple[bool, str]:
    """
    安全更新 latest.json。

    流程：
    1. 验证新数据合法性
    2. 备份当前 latest.json → backup.json
    3. 写入新数据到 staging.json
    4. staging.json → latest.json（原子替换）

    Args:
        new_records: 新数据记录列表
        min_count: 最小有效记录数，低于此值拒绝更新

    Returns:
        (成功, 消息)
    """
    # 1. 验证数量
    if len(new_records) < min_count:
        return False, f"记录数不足: {len(new_records)} < {min_count}"

    # 2. 验证必填字段
    valid_count = sum(
        1 for r in new_records if r.get("code") and r.get("name")
    )
    if valid_count < min_count:
        return False, f"有效记录数不足: {valid_count} < {min_count}"

    # 3. 备份当前 latest.json
    current = read_latest()
    if current is not None:
        write_backup(current)
        logger.info(f"已备份 latest.json ({len(current)} 条) → backup.json")

    # 4. 写入 staging.json
    write_staging(new_records)
    logger.info(f"已写入 staging.json ({len(new_records)} 条)")

    # 5. 原子替换 latest.json
    if write_latest(new_records):
        logger.info(f"已更新 latest.json ({len(new_records)} 条)")
        return True, f"更新成功: {len(new_records)} 条记录"
    else:
        return False, "写入 latest.json 失败"


def rollback() -> tuple[bool, str]:
    """
    回滚到 backup.json。

    从 backup.json 恢复 latest.json。

    Returns:
        (成功, 消息)
    """
    backup = read_backup()
    if backup is None:
        return False, "backup.json 不存在，无法回滚"

    if write_latest(backup):
        logger.info(f"已回滚 latest.json ({len(backup)} 条) ← backup.json")
        return True, f"回滚成功: {len(backup)} 条记录"
    else:
        return False, "回滚失败：写入 latest.json 失败"


# ============================================================
# 8. 增量更新支持
# ============================================================


def get_changed_tickers(
    new_data: dict[str, dict],
    old_data: dict[str, dict] | None = None,
    threshold: float = 0.01,
) -> set[str]:
    """
    获取有变化的股票 ticker 集合。

    比较新旧数据中每个 ticker 的字段值，变化超过 threshold 的视为有变化。

    Args:
        new_data: 新数据 {ticker: {field: value}}
        old_data: 旧数据 {ticker: {field: value}}，None 表示全部有变化
        threshold: 变化阈值（百分比），默认 1%

    Returns:
        有变化的 ticker 集合
    """
    if old_data is None:
        return set(new_data.keys())

    changed: set[str] = set()

    for ticker, new_fields in new_data.items():
        if ticker not in old_data:
            changed.add(ticker)
            continue

        old_fields = old_data[ticker]
        for key, new_val in new_fields.items():
            old_val = old_fields.get(key)
            if new_val == old_val:
                continue
            # 数值型字段比较变化幅度
            if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
                if old_val != 0:
                    change_ratio = abs(new_val - old_val) / abs(old_val)
                    if change_ratio > threshold:
                        changed.add(ticker)
                        break
                else:
                    if abs(new_val) > threshold:
                        changed.add(ticker)
                        break
            else:
                changed.add(ticker)
                break

    return changed


# ============================================================
# 9. 缓存统计
# ============================================================


def get_cache_stats() -> dict[str, Any]:
    """
    获取缓存统计信息。

    Returns:
        {
            "latest_count": int,
            "backup_exists": bool,
            "staging_exists": bool,
            "raw_spot_exists": bool,
            "raw_baidu_exists": bool,
            "raw_yfinance_exists": bool,
            "latest_size_kb": float,
            "last_updated": str | None,
        }
    """
    stats: dict[str, Any] = {
        "latest_count": 0,
        "backup_exists": BACKUP_FILE.exists(),
        "staging_exists": STAGING_FILE.exists(),
        "raw_spot_exists": RAW_SPOT_FILE.exists(),
        "raw_baidu_exists": RAW_BAIDU_FILE.exists(),
        "raw_yfinance_exists": RAW_YFINANCE_FILE.exists(),
        "latest_size_kb": 0,
        "last_updated": None,
    }

    # latest 统计
    latest = read_latest()
    if latest:
        stats["latest_count"] = len(latest)
        stats["latest_size_kb"] = round(LATEST_FILE.stat().st_size / 1024, 1)
        stats["last_updated"] = datetime.fromtimestamp(
            LATEST_FILE.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")

    return stats


def print_cache_stats() -> None:
    """打印缓存统计信息。"""
    stats = get_cache_stats()
    print(f"📊 缓存统计:")
    print(f"  latest.json: {stats['latest_count']} 条 ({stats['latest_size_kb']} KB)")
    print(f"  最后更新: {stats['last_updated'] or 'N/A'}")
    print(f"  backup.json: {'✅' if stats['backup_exists'] else '❌'}")
    print(f"  staging.json: {'✅' if stats['staging_exists'] else '❌'}")
    print(f"  raw/spot: {'✅' if stats['raw_spot_exists'] else '❌'}")
    print(f"  raw/baidu: {'✅' if stats['raw_baidu_exists'] else '❌'}")
    print(f"  raw/yfinance: {'✅' if stats['raw_yfinance_exists'] else '❌'}")


# ============================================================
# 10. 兼容层：旧缓存读取
# ============================================================


def read_old_daily_cache() -> dict[str, dict] | None:
    """读取旧的 daily_cache.json（只读兼容）。"""
    return _read_json(OLD_DAILY_CACHE)


def read_old_financial_cache() -> dict[str, dict] | None:
    """读取旧的 financial_cache.json（只读兼容）。"""
    return _read_json(OLD_FINANCIAL_CACHE)
