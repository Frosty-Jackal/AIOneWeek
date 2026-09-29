"""§6.2 当周查询：缺口串行补采。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import parser
from ..collector import collect, week_dates
from ..db import get_db
from ..models import DailyRun, DailyTech, User
from . import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["weekly"])

# 上游限流 / 额度不足 → 停止本轮补采（Spec1 §6）
STOP_MARKERS = ("429", "402", "余额", "insufficient")

# 失败日自动重采的冷却：用户可能反复点「查看当周」，没有冷却会反复失败并长时间等待
FAILED_RETRY_COOLDOWN_SECONDS = 600

STAMP = "%Y-%m-%d %H:%M:%S"
RAW_SEPARATOR = "--- 原始返回 ---"


def needs_collect(run: DailyRun | None) -> bool:
    """该日期是否需要（重新）采集。

    - 无记录 → 需要
    - `success` / `empty` → 不需要，属终态（§6.2）
    - `failed` → 需要，但带冷却。模型偶尔不触发联网搜索，隔一会儿重试通常能成；
      不再重试的话用户会永远卡在「该日采集失败」，只能等管理员手动重采
    - `parse_failed` → 不需要。那是模型输出格式问题，重试大概率照旧失败还白花钱，
      按 §7.2 交管理员修正
    """
    if run is None:
        return True
    if run.status != parser.STATUS_FAILED:
        return False
    try:
        updated = datetime.strptime(run.updated_at, STAMP)
    except (TypeError, ValueError):
        return True
    return datetime.now() - updated >= timedelta(seconds=FAILED_RETRY_COOLDOWN_SECONDS)


def is_upstream_stop(run: DailyRun) -> bool:
    """是否因上游限流/额度不足而失败 → 是则停止本轮补采。

    只看 `[调用失败]` 那一段：失败时 raw_response 后面还附了完整原始返回，
    正文里出现的数字（比如「429 美元」）不该被当成限流信号。
    """
    head = (run.raw_response or "").split(RAW_SEPARATOR, 1)[0]
    return any(marker in head for marker in STOP_MARKERS)


@router.get("/weekly")
def weekly(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    dates = week_dates()  # 倒序：当天在前
    known = {
        r.date: r
        for r in db.scalars(select(DailyRun).where(DailyRun.date.in_(dates))).all()
    }
    missing = [d for d in dates if needs_collect(known.get(d))]

    collected_now: list[str] = []
    for day in missing:  # 严格串行，不可并发
        try:
            run = collect(day, db=db)
        except Exception:  # noqa: BLE001 —— 单日异常不得拖垮整周展示
            logger.exception("补采 %s 异常", day)
            break
        collected_now.append(day)
        if run.status == parser.STATUS_FAILED and is_upstream_stop(run):
            logger.warning("上游限流或额度不足，停止本轮补采")
            break

    runs = {
        r.date: r
        for r in db.scalars(select(DailyRun).where(DailyRun.date.in_(dates))).all()
    }

    techs: dict[str, list[DailyTech]] = {}
    for tech in db.scalars(
        select(DailyTech)
        .where(DailyTech.date.in_(dates))
        .order_by(DailyTech.date.desc(), DailyTech.seq)
    ).all():
        techs.setdefault(tech.date, []).append(tech)

    days = []
    for day in dates:
        run = runs.get(day)
        status = run.status if run else "missing"
        items = []
        if status == parser.STATUS_SUCCESS:
            for tech in techs.get(day, []):
                try:
                    scenarios = json.loads(tech.scenarios)
                except (ValueError, TypeError):
                    scenarios = []
                items.append(
                    {
                        "tech_name": tech.tech_name,
                        "tech_content": tech.tech_content,
                        "innovation": tech.innovation,
                        "scenarios": scenarios,
                        "publish_date": tech.publish_date,
                        "ref_link": tech.ref_link,
                    }
                )
        days.append({"date": day, "status": status, "items": items})

    user.call_count += 1
    db.commit()

    return {
        "range": {"from": dates[-1], "to": dates[0]},
        "days": days,
        "collected_now": collected_now,
    }
