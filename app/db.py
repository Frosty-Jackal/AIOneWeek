"""数据库引擎、会话工厂、建表与播种。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def now_iso() -> str:
    """统一时间戳格式（Spec1 §4：日期字段统一 TEXT 存 ISO8601）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SEED_SITE = "https://huggingface.co/papers/trending"


def init_db() -> None:
    """建表 + 播种站点 + 播种管理员（Spec1 §4.2 / §7.2）。"""
    from . import models  # noqa: F401  导入以注册全部模型

    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        _seed_site(db)
        _seed_admin(db)
        db.commit()


def _seed_site(db: Session) -> None:
    from .models import SourceSite

    exists = db.scalar(select(SourceSite).where(SourceSite.url == SEED_SITE))
    if exists is None:
        db.add(
            SourceSite(url=SEED_SITE, enabled=1, created_at=now_iso())
        )


def _seed_admin(db: Session) -> None:
    """按 ADMIN_EMAIL 播种管理员；已存在则不动（不覆盖改过的密码）。"""
    from .models import User
    from .security import encrypt_password

    if not settings.admin_email or not settings.admin_init_password:
        return

    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing is None:
        db.add(
            User(
                email=settings.admin_email,
                password_enc=encrypt_password(settings.admin_init_password),
                role="admin",
                call_count=0,
                created_at=now_iso(),
            )
        )
        return

    # 已存在则确保 admin 角色（防止手工改库把权限弄丢）
    if existing.role != "admin":
        existing.role = "admin"
