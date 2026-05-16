"""
港股数据自动更新入口。

支持：
1. 定时自动更新（通过 systemd timer 或 cron 触发）
2. 自动回滚（更新失败时恢复 backup）
3. 日志记录和通知
4. 更新频率控制（防止过于频繁的更新）

用法：
    python -m collector.auto_update_hk                    # 执行更新
    python -m collector.auto_update_hk --force            # 强制更新（忽略缓存）
    python -m collector.auto_update_hk --check            # 仅检查是否需要更新
    python -m collector.auto_update_hk --rollback         # 手动回滚到 backup
    python -m collector.auto_update_hk --status           # 查看更新状态
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# ===== 港股数据目录 =====
HK_DATA_DIR = project_root / "data" / "hk_stock"
LATEST_FILE = HK_DATA_DIR / "latest.json"
BACKUP_FILE = HK_DATA_DIR / "backup.json"

# ===== 日志配置 =====
LOG_DIR = project_root / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "auto_update_hk.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("hk_stocks.auto_update")

# ===== 更新配置 =====
# 最小更新间隔（小时）
MIN_UPDATE_INTERVAL_HOURS = 4

# 交易日（港股交易日：周一至周五）
TRADING_DAYS = [0, 1, 2, 3, 4]  # Monday=0, Sunday=6

# 默认更新时段（港股交易时间：北京时间 9:30~16:00）
# 建议在港股收盘后更新（北京时间 16:30~20:00）
DEFAULT_UPDATE_HOURS = list(range(16, 21))  # 16:00~20:59


# ============================================================
# 1. 缓存管理
# ============================================================


def read_latest() -> list[dict] | None:
    """读取 latest.json。"""
    if not LATEST_FILE.exists():
        return None
    try:
        with open(LATEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"读取 latest.json 失败: {e}")
        return None


def read_backup() -> list[dict] | None:
    """读取 backup.json。"""
    if not BACKUP_FILE.exists():
        return None
    try:
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"读取 backup.json 失败: {e}")
        return None


def save_backup(data: list[dict]) -> bool:
    """保存 backup.json。"""
    try:
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        logger.error(f"保存 backup.json 失败: {e}")
        return False


def rollback() -> tuple[bool, str]:
    """回滚到 backup.json。"""
    backup = read_backup()
    if backup is None:
        return False, "backup.json 不存在或无效"

    try:
        with open(LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
        count = len(backup)
        logger.info(f"回滚成功: {count} 条记录")
        return True, f"已回滚到 backup.json ({count} 条)"
    except OSError as e:
        return False, f"回滚失败: {e}"


def get_cache_stats() -> dict:
    """获取缓存统计信息。"""
    stats = {
        "latest_count": 0,
        "latest_size_kb": 0,
        "backup_exists": BACKUP_FILE.exists(),
        "last_updated": None,
    }

    latest = read_latest()
    if latest:
        stats["latest_count"] = len(latest)
        stats["latest_size_kb"] = round(LATEST_FILE.stat().st_size / 1024, 1)
        # 从第一条记录的 update_time 获取最后更新时间
        if latest and len(latest) > 0:
            ut = latest[0].get("update_time", "")
            if ut:
                stats["last_updated"] = ut

    return stats


# ============================================================
# 2. 更新状态检查
# ============================================================


def get_last_update_time() -> datetime | None:
    """获取上次成功更新的时间（基于 latest.json 的 mtime）。"""
    if not LATEST_FILE.exists():
        return None
    mtime = LATEST_FILE.stat().st_mtime
    return datetime.fromtimestamp(mtime)


def should_update(force: bool = False) -> tuple[bool, str]:
    """
    判断是否需要执行更新。

    Args:
        force: 是否强制更新

    Returns:
        (是否需要更新, 原因)
    """
    if force:
        return True, "强制更新"

    # 检查上次更新时间
    last_time = get_last_update_time()
    if last_time is None:
        return True, "首次更新"

    # 检查更新间隔
    elapsed = datetime.now() - last_time
    if elapsed < timedelta(hours=MIN_UPDATE_INTERVAL_HOURS):
        remaining = timedelta(hours=MIN_UPDATE_INTERVAL_HOURS) - elapsed
        return (
            False,
            f"更新间隔过短: 距上次更新 {elapsed.total_seconds() / 3600:.1f} 小时，"
            f"还需 {remaining.total_seconds() / 3600:.1f} 小时",
        )

    # 检查是否为交易日
    weekday = datetime.now().weekday()
    if weekday not in TRADING_DAYS:
        return False, f"非交易日 (weekday={weekday})"

    return True, "需要更新"


# ============================================================
# 3. 更新执行
# ============================================================


def run_update(force: bool = False) -> tuple[bool, str]:
    """
    执行港股数据更新。

    Args:
        force: 是否强制更新

    Returns:
        (成功, 消息)
    """
    start_time = time.time()
    logger.info("=" * 50)
    logger.info("港股数据自动更新开始")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"强制模式: {force}")
    logger.info("=" * 50)

    try:
        # 先备份当前数据
        current = read_latest()
        if current:
            save_backup(current)
            logger.info(f"已备份当前数据 ({len(current)} 条)")

        # 执行更新脚本
        cmd = [
            sys.executable,
            str(project_root / "collector" / "update_hk_stocks.py"),
        ]

        logger.info(f"执行命令: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=600,  # 10 分钟超时
        )

        elapsed = time.time() - start_time

        # 输出日志
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"  {line}")

        if result.returncode == 0:
            logger.info(f"✅ 港股更新成功 (耗时 {elapsed:.1f} 秒)")
            return True, f"更新成功 (耗时 {elapsed:.1f} 秒)"
        else:
            logger.error(f"❌ 港股更新失败 (returncode={result.returncode})")
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    logger.error(f"  {line}")

            # 自动回滚
            logger.warning("尝试自动回滚...")
            rollback_ok, rollback_msg = rollback()
            if rollback_ok:
                logger.info(f"✅ 自动回滚成功: {rollback_msg}")
                return False, f"更新失败，已自动回滚: {rollback_msg}"
            else:
                logger.error(f"❌ 自动回滚失败: {rollback_msg}")
                return False, f"更新失败，回滚也失败: {rollback_msg}"

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"❌ 更新超时 (耗时 {elapsed:.1f} 秒)")
        return False, f"更新超时 (耗时 {elapsed:.1f} 秒)"

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ 更新异常: {e}")
        return False, f"更新异常: {e}"


# ============================================================
# 4. 状态查看
# ============================================================


def print_status() -> None:
    """打印更新状态。"""
    print("=" * 50)
    print("港股数据更新状态")
    print("=" * 50)

    # 缓存统计
    stats = get_cache_stats()
    print(f"\n📊 缓存状态:")
    print(f"  latest.json: {stats['latest_count']} 条 ({stats['latest_size_kb']} KB)")
    print(f"  最后更新: {stats['last_updated'] or 'N/A'}")
    print(f"  backup.json: {'✅ 存在' if stats['backup_exists'] else '❌ 不存在'}")

    # 更新间隔
    last_time = get_last_update_time()
    if last_time:
        elapsed = datetime.now() - last_time
        print(f"\n⏱️  距上次更新: {elapsed.total_seconds() / 3600:.1f} 小时")
        if elapsed.total_seconds() / 3600 < MIN_UPDATE_INTERVAL_HOURS:
            remaining = timedelta(hours=MIN_UPDATE_INTERVAL_HOURS) - elapsed
            print(f"  下次更新还需: {remaining.total_seconds() / 3600:.1f} 小时")
        else:
            print(f"  ✅ 可以更新")
    else:
        print(f"\n⚠️  从未更新过")

    # 是否需要更新
    need, reason = should_update()
    print(f"\n{'🔄' if need else '✅'} 更新判断: {reason}")

    print("\n" + "=" * 50)


# ============================================================
# 5. CLI 入口
# ============================================================


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="港股数据自动更新工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python -m collector.auto_update_hk              # 执行更新
    python -m collector.auto_update_hk --force      # 强制更新
    python -m collector.auto_update_hk --check      # 仅检查
    python -m collector.auto_update_hk --rollback   # 手动回滚
    python -m collector.auto_update_hk --status     # 查看状态
        """,
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="强制更新（忽略缓存和间隔检查）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查是否需要更新，不执行",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="手动回滚到 backup.json",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看更新状态",
    )

    return parser.parse_args()


def main():
    """主入口。"""
    args = parse_args()

    if args.status:
        print_status()
        return

    if args.rollback:
        logger.info("手动回滚...")
        success, msg = rollback()
        if success:
            logger.info(f"✅ {msg}")
        else:
            logger.error(f"❌ {msg}")
        return

    if args.check:
        need, reason = should_update(force=False)
        if need:
            print(f"🔄 {reason}")
        else:
            print(f"✅ {reason}")
        return

    # 执行更新
    need, reason = should_update(force=args.force)
    if not need:
        logger.info(f"跳过更新: {reason}")
        print(f"✅ {reason}")
        return

    success, msg = run_update(force=args.force)
    if success:
        print(f"\n✅ {msg}")
    else:
        print(f"\n❌ {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
