"""§6.3 评分 + 评测集回填（PRD §8）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import get_db, now_iso
from ..models import DailyRun, EvalSet, Rating, User
from ..schemas import RatingIn
from . import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["rating"])

LOW_SCORE_MAX = 2
LOW_SCORE_RATIO = 0.2


@router.post("/rating", status_code=status.HTTP_201_CREATED)
def rate(
    payload: RatingIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(Rating).where(Rating.user_id == user.id, Rating.date == payload.date)
    )
    if existing is not None:
        existing.score = payload.score  # 同日重复评分走 UPDATE，不新增行
    else:
        db.add(
            Rating(
                user_id=user.id,
                date=payload.date,
                score=payload.score,
                created_at=now_iso(),
            )
        )
    db.commit()

    try:
        maybe_backfill_eval_set(db, payload.date)
    except Exception:  # noqa: BLE001 —— 回填失败不得影响评分返回（§6.3）
        logger.exception("评测集回填检查失败 date=%s", payload.date)

    return {"date": payload.date, "score": payload.score}


def maybe_backfill_eval_set(db: Session, day: str) -> bool:
    """低分率 > 20% 时把当日 prompt 写入 eval_set；同一 date 只回填一次。"""
    rows = db.execute(
        select(
            func.count(Rating.id),
            func.sum(case((Rating.score <= LOW_SCORE_MAX, 1), else_=0)),
        ).where(Rating.date == day)
    ).one()
    total, low = int(rows[0] or 0), int(rows[1] or 0)
    if total == 0 or low / total <= LOW_SCORE_RATIO:
        return False

    if db.scalar(select(EvalSet).where(EvalSet.date == day)) is not None:
        return False

    run = db.scalar(select(DailyRun).where(DailyRun.date == day))
    if run is None or not run.prompt:
        return False

    db.add(EvalSet(date=day, prompt=run.prompt, created_at=now_iso()))
    db.commit()
    logger.info("评测集已回填 date=%s（低分率 %.0f%%）", day, low / total * 100)
    return True
