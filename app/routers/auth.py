"""§6.1 鉴权。"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, now_iso
from ..mailer import MailError, send_code as send_code_mail
from ..models import User, VerifyCode
from ..schemas import LoginCodeIn, LoginIn, MeOut, RegisterIn, SendCodeIn
from ..security import (
    decrypt_password,
    encrypt_password,
    generate_code,
    password_ok,
)
from . import clear_session, get_current_user, issue_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

STAMP = "%Y-%m-%d %H:%M:%S"


def _stamp(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).strftime(STAMP)


def _find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def _recently_sent(db: Session, email: str) -> bool:
    cutoff = _stamp(datetime.now() - timedelta(seconds=settings.code_resend_interval))
    row = db.scalar(
        select(VerifyCode)
        .where(VerifyCode.email == email, VerifyCode.created_at > cutoff)
        .order_by(VerifyCode.id.desc())
    )
    return row is not None


def _consume_code(db: Session, email: str, purpose: str, code: str) -> bool:
    """取最新一条未用且未过期的验证码校验，通过则置 used=1。"""
    row = db.scalar(
        select(VerifyCode)
        .where(
            VerifyCode.email == email,
            VerifyCode.purpose == purpose,
            VerifyCode.used == 0,
            VerifyCode.expire_at > _stamp(),
        )
        .order_by(VerifyCode.id.desc())
    )
    if row is None or not hmac.compare_digest(row.code, code):
        return False
    row.used = 1
    return True


@router.post("/send-code", status_code=status.HTTP_204_NO_CONTENT)
def send_code(payload: SendCodeIn, db: Session = Depends(get_db)) -> Response:
    email = payload.email.strip()

    if payload.purpose == "register" and _find_user(db, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")
    if payload.purpose == "login" and _find_user(db, email) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱未注册")

    if _recently_sent(db, email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"发送过于频繁，请 {settings.code_resend_interval} 秒后再试",
        )

    code = generate_code()
    expire_at = _stamp(datetime.now() + timedelta(seconds=settings.code_ttl_seconds))

    # 先发信，成功后才落库；SMTP 失败 → 502 且不落库（§6.1）
    try:
        send_code_mail(email, code)
    except MailError as exc:
        logger.warning("验证码发送失败：%s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="验证码发送失败，请稍后重试"
        ) from exc

    db.add(
        VerifyCode(
            email=email,
            code=code,
            purpose=payload.purpose,
            expire_at=expire_at,
            used=0,
            created_at=now_iso(),
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=MeOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> MeOut:
    email = payload.email.strip()

    if not password_ok(payload.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码须为 2-8 位数字或英文",
        )
    if _find_user(db, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")
    if not _consume_code(db, email, "register", payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期"
        )

    db.add(
        User(
            email=email,
            password_enc=encrypt_password(payload.password),
            role="user",
            call_count=0,
            created_at=now_iso(),
        )
    )
    db.commit()
    # 注册成功不自动登录（§6.1 步骤 5）
    return MeOut(email=email, role="user")


@router.post("/login", response_model=MeOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    email = payload.email.strip()
    user = _find_user(db, email)
    if user is None or not hmac.compare_digest(
        decrypt_password(user.password_enc), payload.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误"
        )
    issue_session(response, user.id)
    return MeOut(email=user.email, role=user.role)


@router.post("/login-code", response_model=MeOut)
def login_code(
    payload: LoginCodeIn, response: Response, db: Session = Depends(get_db)
) -> MeOut:
    email = payload.email.strip()
    user = _find_user(db, email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱未注册")
    if not _consume_code(db, email, "login", payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期"
        )
    db.commit()
    issue_session(response, user.id)
    return MeOut(email=user.email, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    # 必须把 cookie 删在「实际返回的那个」Response 上：直接返回 Response 时
    # FastAPI 不会合并注入对象上设置的头，借用注入的 response 会静默失效。
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(response)
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(email=user.email, role=user.role)
