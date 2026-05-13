"""
更新 stock_basic 表中已有股票的 sector（一级板块）字段。
基于股票名称关键词映射到 8 个一级板块。
"""
import pandas as pd
from sqlalchemy import text

from api.db import get_engine
from api.stock_utils import map_sector_by_name


def update_all_sectors():
    """遍历 stock_basic 表中所有股票，根据名称更新 sector 字段。"""
    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT id, bs_code, name, sector
                FROM stock_basic
                ORDER BY id
            """)
        ).fetchall()

        updated_count = 0
        skipped_count = 0
        no_match_count = 0

        for row in rows:
            stock_id = row[0]
            bs_code = row[1]
            name = row[2]
            current_sector = row[3]

            new_sector = map_sector_by_name(name)

            if new_sector == current_sector:
                skipped_count += 1
                continue

            conn.execute(
                text("""
                    UPDATE stock_basic
                    SET sector = :sector,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {"sector": new_sector, "id": stock_id},
            )

            if new_sector:
                updated_count += 1
                print(f"更新 {bs_code} {name}: {current_sector or '无'} -> {new_sector}")
            else:
                no_match_count += 1
                if current_sector:
                    print(f"清空 {bs_code} {name}: {current_sector} -> 无匹配")

        print(f"\n更新完成：更新 {updated_count} 条，无变化跳过 {skipped_count} 条，无匹配 {no_match_count} 条")


if __name__ == "__main__":
    update_all_sectors()
