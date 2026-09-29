"""SQLAlchemy ORM 模型（Spec1 §4）。日期一律 TEXT 存 ISO8601。"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    """§4.1"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user"
    )
    call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class SourceSite(Base):
    """§4.2"""

    __tablename__ = "source_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class DailyRun(Base):
    """§4.3 每日采集批次。

    与 daily_tech 分开，使「没爬过」与「爬了但没有」可区分：
    daily_run 存在该日期记录（无论 status）即视为当日已有数据。
    """

    __tablename__ = "daily_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # SQLAlchemy 2.1 起顶层不再导出 Real；Float 在 SQLite 下即 REAL 亲和
    cost_cny: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class DailyTech(Base):
    """§4.4"""

    __tablename__ = "daily_tech"
    __table_args__ = (UniqueConstraint("date", "seq", name="uq_daily_tech_date_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tech_name: Mapped[str] = mapped_column(Text, nullable=False)
    tech_content: Mapped[str] = mapped_column(Text, nullable=False)
    innovation: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON 数组字符串，固定 3 元素
    scenarios: Mapped[str] = mapped_column(Text, nullable=False)
    publish_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_link: Mapped[str | None] = mapped_column(Text, nullable=True)


class Rating(Base):
    """§4.5 UNIQUE(user_id, date)：同日重复评分执行 UPDATE，不新增行。"""

    __tablename__ = "rating"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_rating_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    date: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class VerifyCode(Base):
    """§4.6"""

    __tablename__ = "verify_code"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    expire_at: Mapped[str] = mapped_column(Text, nullable=False)
    used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class EvalSet(Base):
    """§4.7 同一 date 只回填一次（写入前查重）。"""

    __tablename__ = "eval_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AdminAudit(Base):
    """§4.8 动作取值见 Spec1 §10。"""

    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
