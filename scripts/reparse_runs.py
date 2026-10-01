"""用新判据重判存量 `parse_failed` 行（Spec3 §8.5）。

用法：

    .venv/Scripts/python.exe -m scripts.reparse_runs --dry-run
    .venv/Scripts/python.exe -m scripts.reparse_runs

**为什么需要它**：Spec3 §8.4 修掉了「无」被误判成解析异常的判据缺陷，但已经写进库
的 `parse_failed` 行不会自己变好 —— `weekly.py` 的 `needs_collect()` 对
`parse_failed` 永远返回 False（Spec1 §6.2 的有意设计），于是那次误判被永久固化，
用户每次点按钮都看到「管理员可修正」。

**为什么不必重采**：`daily_run.raw_response` 存着当时的完整响应 JSON，用新判据重解析
一遍即可 —— **零 API 调用、零成本**。

契约（与 `clean_ref_links.py` 同一套路）：

1. 只处理 `daily_run.status == 'parse_failed'` 的行；success / empty / failed 一律不动
2. 逐行 `json.loads(raw_response)` → `deepseek._extract(data, require_search=False)`
   取正文 → `parser.parse(text, max_items, sites)`
   - `raw_response` 不是合法 JSON（例如 failed 行的 `[调用失败] …`）→ 跳过并计数
   - 新状态 `empty` → 置 `status='empty', item_count=0`，并清掉该日旧残条
   - 新状态 `success` → 写入 `daily_tech`（`seq` 从 0 递增），置 `status='success'`
   - 新状态仍是 `parse_failed` → 不动
3. **值有变化才 `UPDATE`**；逐行打印 `日期 旧状态 → 新状态（N 条）`
4. `--dry-run` 只打印不写库
5. 结束打印统计：`扫描 N 行，重判 M 行（其中 empty K 行、success J 行），跳过 I 行`
6. **幂等**：重复执行结果一致，第二次变更行数为 0
7. **不改 `cost_cny`**（没有产生新调用）；`created_at` 不变，`updated_at` 置为执行时刻
8. **不调用任何网络接口**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 支持 `python scripts/reparse_runs.py` 直跑（`-m` 方式不需要，留着无害）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import collector, deepseek, parser  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, now_iso  # noqa: E402
from app.models import DailyRun  # noqa: E402


def body_of(raw_response: str | None) -> str | None:
    """从存下来的原始返回里取正文；取不到返回 None。

    `require_search=False`：存量行是当初**联网成功**才走到 parser 的，这里只取正文，
    不重新判定联网痕迹 —— 该判定属于调用层，重判不该把它重做一遍。
    """
    if not raw_response:
        return None
    try:
        data = json.loads(raw_response)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    result, _reason = deepseek._extract(data, require_search=False)
    return result.text if result else None


def reparse(db: Session, sites: list[str], dry_run: bool = False, log=print) -> dict:
    """逐行重判并返回统计。`dry_run` 时只打印、不写库。"""
    rows = db.scalars(
        select(DailyRun)
        .where(DailyRun.status == parser.STATUS_PARSE_FAILED)
        .order_by(DailyRun.date)
    ).all()

    rescanned = empty = success = skipped = 0
    for run in rows:
        text = body_of(run.raw_response)
        if text is None:
            skipped += 1
            log(f"{run.date} 跳过：raw_response 不是可解析的响应 JSON")
            continue

        status, items = parser.parse(text, settings.max_items_per_day, sites)
        if status == parser.STATUS_PARSE_FAILED:
            continue  # 确实不可解析，交管理员（§8.6 明确不做自动重采）

        rescanned += 1
        empty += status == parser.STATUS_EMPTY
        success += status == parser.STATUS_SUCCESS
        log(f"{run.date} {run.status} → {status}（{len(items)} 条）")

        if dry_run:
            continue

        run.status = status
        run.item_count = len(items)
        run.updated_at = now_iso()  # created_at 与 cost_cny 不动：没有产生新调用
        collector._write_items(db, run.date, items)

    if not dry_run:
        db.commit()

    stats = {
        "scanned": len(rows),
        "rescanned": rescanned,
        "empty": empty,
        "success": success,
        "skipped": skipped,
    }
    log(
        f"扫描 {stats['scanned']} 行，重判 {rescanned} 行"
        f"（其中 empty {empty} 行、success {success} 行），跳过 {skipped} 行"
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用新判据重判存量 parse_failed 行（Spec3 §8.5）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = ap.parse_args(argv)

    with SessionLocal() as db:
        # 来源站只查一次：parse() 需要它剔除「回填来源站」的参考链接（§8.5 实现提示）
        sites = collector.enabled_sites(db)
        print(f"来源站 {len(sites)} 条（已启用）")
        if args.dry_run:
            print("--- DRY RUN：不写库 ---")
        reparse(db, sites, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
