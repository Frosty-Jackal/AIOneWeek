"""§6.4 管理端。全部接口前置校验 role='admin'。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..collector import collect, write_audit
from ..db import get_db, now_iso
from ..models import DailyRun, EvalSet, Rating, SourceSite, User
from ..schemas import CollectIn, CollectOut, SiteIn, SiteOut, SiteUpdateIn, UserOut
from ..security import decrypt_password
from . import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

PASSWORD_MASK = "●●●●●●"


# --- 网站列表管理（P0-2）---


@router.get("/sites", response_model=list[SiteOut])
def list_sites(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[SiteOut]:
    rows = db.scalars(select(SourceSite).order_by(SourceSite.id)).all()
    return [SiteOut(**{c: getattr(r, c) for c in ("id", "url", "enabled", "created_at")}) for r in rows]


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: SiteIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SiteOut:
    url = payload.url.strip()
    if db.scalar(select(SourceSite).where(SourceSite.url == url)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该 URL 已存在")
    site = SourceSite(url=url, enabled=1, created_at=now_iso())
    db.add(site)
    write_audit(db, admin.id, "site_create", url)
    db.commit()
    db.refresh(site)
    return SiteOut(id=site.id, url=site.url, enabled=site.enabled, created_at=site.created_at)


@router.put("/sites/{site_id}", response_model=SiteOut)
def update_site(
    site_id: int,
    payload: SiteUpdateIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SiteOut:
    site = db.get(SourceSite, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站不存在")

    if payload.url is not None:
        url = payload.url.strip()
        clash = db.scalar(select(SourceSite).where(SourceSite.url == url))
        if clash is not None and clash.id != site_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该 URL 已存在")
        site.url = url
    if payload.enabled is not None:
        site.enabled = payload.enabled

    write_audit(db, admin.id, "site_update", f"{site.id}:{site.url}")
    db.commit()
    db.refresh(site)
    return SiteOut(id=site.id, url=site.url, enabled=site.enabled, created_at=site.created_at)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(
    site_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    site = db.get(SourceSite, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站不存在")
    write_audit(db, admin.id, "site_delete", site.url)
    db.delete(site)
    db.commit()


# --- 采集与日表 ---


@router.post("/collect", response_model=CollectOut)
def trigger_collect(
    payload: CollectIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CollectOut:
    run = collect(payload.date, force=payload.force, db=db, admin_id=admin.id)
    write_audit(
        db, admin.id, "force_refresh" if payload.force else "collect", payload.date
    )
    db.commit()
    return CollectOut(
        date=run.date, status=run.status, item_count=run.item_count, cost_cny=run.cost_cny
    )


@router.get("/daily")
def list_daily(
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(DailyRun)
    if date_from:
        query = query.where(DailyRun.date >= date_from)
    if date_to:
        query = query.where(DailyRun.date <= date_to)
    rows = db.scalars(query.order_by(DailyRun.date.desc())).all()
    return [
        {
            "date": r.date,
            "status": r.status,
            "item_count": r.item_count,
            "cost_cny": r.cost_cny,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


# --- 用户数据 ---


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[UserOut]:
    stats = {
        user_id: (avg, count)
        for user_id, avg, count in db.execute(
            select(Rating.user_id, func.avg(Rating.score), func.count(Rating.id)).group_by(
                Rating.user_id
            )
        ).all()
    }

    out: list[UserOut] = []
    for user in db.scalars(select(User).order_by(User.id)).all():
        avg, count = stats.get(user.id, (None, 0))
        out.append(
            UserOut(
                id=user.id,
                email=user.email,
                role=user.role,
                password_masked=PASSWORD_MASK,  # 列表只给掩码（§6.4）
                call_count=user.call_count,
                avg_score=round(float(avg), 2) if avg is not None else None,
                rating_count=int(count),
                created_at=user.created_at,
            )
        )
    return out


@router.get("/users/{user_id}/password")
def reveal_password(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    plain = decrypt_password(target.password_enc)
    write_audit(db, admin.id, "decrypt_password", target.email)  # 每次解密留痕
    db.commit()
    return {"id": target.id, "email": target.email, "password": plain}


@router.get("/eval-set")
def list_eval_set(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(select(EvalSet).order_by(EvalSet.date.desc())).all()
    return [
        {"id": r.id, "date": r.date, "prompt": r.prompt, "created_at": r.created_at}
        for r in rows
    ]
