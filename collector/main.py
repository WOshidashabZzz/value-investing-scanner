import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from api.validate_staging import validate_staging_data

from collector.fetch_a_stock import fetch_stock_pool, fetch_stock_valuation
from collector.fetch_financial import fetch_stock_financial
from collector.save_to_mysql import (
    save_stock_basic_to_mysql,
    save_stock_financial_to_mysql,
    save_stock_valuation_to_mysql,
)
from collector.update_dividend_akshare import main as update_dividend_yield


BOARD_LABELS = {
    "main_board": "沪深主板",
    "gem": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "unknown": "未知",
}


# ── update_log 操作 ──────────────────────────────────────────────


def insert_update_log(update_type: str, trade_date: str) -> int:
    """插入一条更新日志，返回 log_id。"""
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO update_log (update_type, status, staging_trade_date)
                VALUES (:update_type, 'running', :trade_date)
            """),
            {"update_type": update_type, "trade_date": trade_date},
        )
        return result.lastrowid


def update_log_status(
    log_id: int,
    status: str,
    stock_count: int | None = None,
    validation_errors: str | None = None,
    error_message: str | None = None,
):
    """更新日志状态和完成时间。"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE update_log
                SET status = :status,
                    stock_count = COALESCE(:stock_count, stock_count),
                    validation_errors = COALESCE(:validation_errors, validation_errors),
                    error_message = COALESCE(:error_message, error_message),
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = :log_id
            """),
            {
                "log_id": log_id,
                "status": status,
                "stock_count": stock_count,
                "validation_errors": validation_errors,
                "error_message": error_message,
            },
        )


# ── staging 版本管理 ────────────────────────────────────────────


def promote_staging(trade_date: str):
    """
    将 staging 数据提升为 latest，原 latest 降级为 backup。

    在单个事务中原子执行：
    1. 原 latest → backup
    2. staging → latest
    """
    engine = get_engine()
    with engine.begin() as conn:
        # 将当前的 latest 标记为 backup
        result = conn.execute(
            text("""
                UPDATE stock_valuation
                SET data_version = 'backup'
                WHERE data_version = 'latest'
            """),
        )
        backup_count = result.rowcount

        # 将 staging 标记为 latest
        result = conn.execute(
            text("""
                UPDATE stock_valuation
                SET data_version = 'latest'
                WHERE data_version = 'staging'
                  AND trade_date = :trade_date
            """),
            {"trade_date": trade_date},
        )
        latest_count = result.rowcount

    print(f"版本切换完成: backup {backup_count} 条, latest {latest_count} 条")


def rollback_staging(trade_date: str):
    """删除 staging 数据，保留 latest/backup 不变。"""
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                DELETE FROM stock_valuation
                WHERE data_version = 'staging'
                  AND trade_date = :trade_date
            """),
            {"trade_date": trade_date},
        )
        deleted_count = result.rowcount
    print(f"已回滚 staging 数据: 删除 {deleted_count} 条")


# ── 主流程 ───────────────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(description="采集股票池估值、财务和股息率数据。")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理 stock_pool.csv 前 N 只股票；不传则处理全部股票池。",
    )
    parser.add_argument(
        "--trade-date",
        type=str,
        default=None,
        help="指定交易日（YYYY-MM-DD）；不传则使用当天日期。",
    )
    return parser.parse_args()


def main(limit: int | None = None, trade_date: str | None = None):
    if limit is not None and limit <= 0:
        raise SystemExit("--limit 必须是正整数")

    # 使用指定日期或当天日期
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    print(f"=" * 50)
    print(f"数据更新任务启动")
    print(f"交易日期: {trade_date}")
    print(f"=" * 50)

    # 打印全量股票池统计
    if Path("data/full_stock_pool.csv").exists():
        full_pool = pd.read_csv(
            "data/full_stock_pool.csv",
            dtype={"symbol": str, "bs_code": str, "market": str},
        )
        print("全量识别股票数量：", len(full_pool))
        if "board" in full_pool.columns:
            for board, label in BOARD_LABELS.items():
                print(f"  {label}数量：", int((full_pool["board"] == board).sum()))

    # 插入更新日志
    log_id = insert_update_log(update_type="full", trade_date=trade_date)
    print(f"更新日志 ID: {log_id}")

    try:
        # ── 阶段 1: 股票池更新 ──
        print(f"\n{'─' * 40}")
        print("阶段 1/5: 股票池更新")
        stock_pool_df = fetch_stock_pool(limit=limit)
        pool_count = len(
            pd.read_csv("data/stock_pool.csv", dtype={"symbol": str})
        )
        print("本次使用股票池数量：", pool_count)
        print("本次实际处理数量：", len(stock_pool_df))
        print("当前股票池范围：沪深主板")
        save_stock_basic_to_mysql(stock_pool_df)

        # ── 阶段 2: 估值数据（写入 staging） ──
        print(f"\n{'─' * 40}")
        print("阶段 2/5: 估值数据采集（写入 staging）")
        valuation_df = fetch_stock_valuation(trade_date, stock_pool=stock_pool_df)
        staging_count = 0
        if not valuation_df.empty:
            staging_count = len(valuation_df)
        save_stock_valuation_to_mysql(valuation_df, data_version="staging")
        print(f"staging 估值数据: {staging_count} 条")

        # ── 阶段 3: 财务数据 ──
        print(f"\n{'─' * 40}")
        print("阶段 3/5: 财务数据采集")
        financial_df = fetch_stock_financial(stock_pool=stock_pool_df)
        save_stock_financial_to_mysql(financial_df)

        # ── 阶段 4: 股息率更新 ──
        print(f"\n{'─' * 40}")
        print("阶段 4/5: 股息率更新")
        update_dividend_yield(stock_pool=stock_pool_df)

        # ── 阶段 5: 校验与切换 ──
        print(f"\n{'─' * 40}")
        print("阶段 5/5: 数据校验与版本切换")
        passed, errors = validate_staging_data(trade_date)

        if passed:
            promote_staging(trade_date)
            update_log_status(
                log_id=log_id,
                status="success",
                stock_count=staging_count,
            )
            print(f"\n{'=' * 50}")
            print(f"✅ 数据更新成功完成")
            print(f"   交易日: {trade_date}")
            print(f"   股票数: {staging_count}")
            print(f"{'=' * 50}")
        else:
            rollback_staging(trade_date)
            error_text = "; ".join(errors)
            update_log_status(
                log_id=log_id,
                status="failed",
                stock_count=staging_count,
                validation_errors=error_text,
            )
            print(f"\n{'=' * 50}")
            print(f"❌ 数据校验失败，已回滚 staging")
            for err in errors:
                print(f"   - {err}")
            print(f"当前 latest 数据未受影响")
            print(f"{'=' * 50}")

    except Exception as exc:
        # 异常回滚
        try:
            rollback_staging(trade_date)
        except Exception:
            pass
        update_log_status(
            log_id=log_id,
            status="failed",
            error_message=str(exc),
        )
        print(f"\n{'=' * 50}")
        print(f"❌ 采集异常: {exc}")
        print(f"已回滚 staging 数据，当前 latest 未受影响")
        print(f"{'=' * 50}")
        raise


if __name__ == "__main__":
    args = parse_args()
    main(limit=args.limit, trade_date=args.trade_date)
