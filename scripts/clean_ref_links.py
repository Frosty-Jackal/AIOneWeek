"""清洗历史数据里脏掉的 `daily_tech.ref_link`（Spec2 §9.3 第 4 层）。

用法：

    .venv/Scripts/python.exe -m scripts.clean_ref_links --dry-run
    .venv/Scripts/python.exe -m scripts.clean_ref_links

契约：

1. 读 `source_sites` **全部** URL（含 `enabled=0` 的 —— 历史条目可能引用了已停用的站点）
2. 逐行调 `parser.normalize_ref_link(ref_link, sites)`
3. **值有变化才 `UPDATE`**，逐行打印 旧值 → 新值（或 旧值 → NULL）
4. `--dry-run` 只打印不写库
5. 结束打印统计：`扫描 N 行，清洗 M 行，其中置空 K 行`
6. **幂等**：重复执行结果一致，第二次变更行数为 0

**不自动删除条目** —— 清洗后为 NULL 的行保留，靠前端「暂无链接，建议上网搜索」兜底。
想拿到真正可用的链接，需在管理端对这些日期勾「强制刷新」重采（走新 prompt）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/clean_ref_links.py` 直跑（`-m` 方式不需要，留着无害）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import parser  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import DailyTech, SourceSite  # noqa: E402


def all_sites(db: Session) -> list[str]:
    """全部来源站，含已停用的（契约 1）。"""
    return list(db.scalars(select(SourceSite.url).order_by(SourceSite.id)).all())


def _fmt(value: str | None) -> str:
    """多行说明压成一行，便于看 diff。"""
    return "NULL" if value is None else " ".join(value.split())


def clean(db: Session, sites: list[str], dry_run: bool = False, log=print) -> dict:
    """逐行清洗并返回统计。`dry_run` 时只打印、不写库。"""
    rows = db.scalars(select(DailyTech).order_by(DailyTech.date, DailyTech.seq)).all()

    changed = 0
    nulled = 0
    for row in rows:
        new_value = parser.normalize_ref_link(row.ref_link, sites)
        if new_value == row.ref_link:
            continue
        changed += 1
        if new_value is None:
            nulled += 1
        log(
            f"{row.date} seq {row.seq} {row.tech_name}\n"
            f"  旧：{_fmt(row.ref_link)}\n"
            f"  新：{_fmt(new_value)}"
        )
        if not dry_run:
            row.ref_link = new_value

    if not dry_run:
        db.commit()

    stats = {"scanned": len(rows), "changed": changed, "nulled": nulled}
    log(f"扫描 {stats['scanned']} 行，清洗 {changed} 行，其中置空 {nulled} 行")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="清洗 daily_tech.ref_link 的脏值（Spec2 §9.3）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = ap.parse_args(argv)

    with SessionLocal() as db:
        sites = all_sites(db)
        print(f"来源站 {len(sites)} 条（含已停用）：")
        for url in sites:
            print(f"  - {url}")
        if args.dry_run:
            print("--- DRY RUN：不写库 ---")
        clean(db, sites, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
