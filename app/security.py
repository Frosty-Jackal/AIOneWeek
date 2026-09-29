"""Fernet 加解密、密码格式校验、会话签名、验证码生成（Spec1 §3 / §6 / §10）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

# Spec1 §6.1：2-8 位，仅数字与英文
PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{2,8}$")

_fernet = Fernet(settings.fernet_key.encode())


def password_ok(password: str) -> bool:
    return bool(PASSWORD_RE.match(password or ""))


def encrypt_password(plain: str) -> str:
    """明文 → Fernet 密文。禁止明文入库（Spec1 §10）。"""
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_password(token: str) -> str:
    """密文 → 明文。仅管理员显式调用，且每次须写审计日志。"""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def generate_code() -> str:
    """4 位数字验证码，补零（Spec1 §6.1）。"""
    return f"{secrets.randbelow(10000):04d}"


# --- 会话：token = base64(user_id.expiry) + HMAC 签名（Spec1 §6）---


def _sign(payload: str) -> str:
    return hmac.new(
        settings.session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def make_session_token(user_id: int) -> str:
    expiry = int(time.time()) + settings.session_ttl_seconds
    payload = base64.urlsafe_b64encode(f"{user_id}.{expiry}".encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session_token(token: str | None) -> int | None:
    """校验签名与有效期；通过则返回 user_id，否则 None。"""
    if not token:
        return None
    payload, sep, signature = token.rpartition(".")
    if not sep or not payload or not signature:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        raw = base64.urlsafe_b64decode(payload.encode()).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    user_id_s, sep2, expiry_s = raw.partition(".")
    if not sep2:
        return None
    try:
        if int(expiry_s) < int(time.time()):
            return None
        return int(user_id_s)
    except ValueError:
        return None
