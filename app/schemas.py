"""Pydantic 请求/响应模型（Spec1 §6）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


# --- §6.1 鉴权 ---


class SendCodeIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    purpose: Literal["register", "login"]


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=4)
    password: str


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str


class LoginCodeIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=4)


class MeOut(BaseModel):
    email: str
    role: str


# --- §6.3 评分 ---


class RatingIn(BaseModel):
    date: str = Field(pattern=DATE_PATTERN)
    score: int = Field(ge=1, le=5)


# --- §6.4 管理端 ---


class SiteIn(BaseModel):
    url: str = Field(min_length=4, max_length=2048)


class SiteUpdateIn(BaseModel):
    url: str | None = Field(default=None, min_length=4, max_length=2048)
    enabled: int | None = None

    @field_validator("enabled")
    @classmethod
    def _enabled_is_bool_like(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v not in (0, 1):
            raise ValueError("enabled 只能是 0 或 1")
        return v


class CollectIn(BaseModel):
    date: str = Field(pattern=DATE_PATTERN)
    force: bool = False


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    password_masked: str
    call_count: int
    avg_score: float | None
    rating_count: int
    created_at: str


class SiteOut(BaseModel):
    id: int
    url: str
    enabled: int
    created_at: str


class CollectOut(BaseModel):
    date: str
    status: str
    item_count: int
    cost_cny: float
