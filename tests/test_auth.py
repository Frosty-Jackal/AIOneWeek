"""Spec3 §9.5 —— 「验证码与邮箱一一对应」的回归护栏。

**先说清楚这不是在修一个已存在的漏洞**（Spec3 §9.1）：`_consume_code()` 的查询条件
里本来就带 `VerifyCode.email == email` 与 `purpose`，拿 A 的码配 B 的邮箱调
`/register` 现在就会 400。这六条用例守的是**明天**：那条绑定是三行 SQL 的副作用，
日后若有人把查询放宽成「按最新一条未用验证码校验」，越权注册会静默出现，而现有
测试一条都不会红。

「看着它失败」这一步由 §9.6 的自检兑现（删掉 `auth.py` 里那行
`VerifyCode.email == email`，用例 1 必须变红），而不是靠先写一个假的红 —— 护栏
只会因为**被守的东西被破坏**而红，写的时候本就该是绿的。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, now_iso
from app.main import app
from app.models import User, VerifyCode
from app.security import encrypt_password

STAMP = "%Y-%m-%d %H:%M:%S"
A = "a@example.com"
B = "b@example.com"


def _stamp(delta_seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=delta_seconds)).strftime(STAMP)


class _FakeMail:
    """记录发信调用的假 SMTP：验证码从这里读，别去猜 `generate_code()`。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, to_email: str, code: str) -> None:
        self.calls.append((to_email, code))

    def code_for(self, email: str) -> str:
        return [code for to, code in self.calls if to == email][-1]


class AuthRulesTest(unittest.TestCase):
    """`/api/auth/*` 的判据。全部打在临时库上，绝不碰 `./data/aioneek.db`。"""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aioneek-auth-")) / "t.db"
        self.engine = create_engine(f"sqlite:///{tmp}", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

        def override():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        self.addCleanup(app.dependency_overrides.clear)

        # 补丁必须打在 `app.routers.auth` 命名空间上：auth.py 用的是值导入，
        # 打 `app.mailer.send_code` 对它毫无影响（Spec3 §9.5）。
        self.mail = _FakeMail()
        patcher = patch("app.routers.auth.send_code_mail", self.mail)
        patcher.start()
        self.addCleanup(patcher.stop)

        # **不要** `with TestClient(app) as client:` —— 那会跑 lifespan 里的
        # `init_db()`，把建表与播种打到真实的 `./data/aioneek.db` 上。
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    # --- 夹具 ---

    def _add_code(self, email: str, code: str, purpose: str = "register",
                  expire_seconds: int = 600, used: int = 0) -> None:
        with self.Session() as db:
            db.add(
                VerifyCode(
                    email=email,
                    code=code,
                    purpose=purpose,
                    expire_at=_stamp(expire_seconds),
                    used=used,
                    created_at=now_iso(),
                )
            )
            db.commit()

    def _add_user(self, email: str) -> None:
        with self.Session() as db:
            db.add(
                User(
                    email=email,
                    password_enc=encrypt_password("1234"),
                    role="user",
                    call_count=0,
                    created_at=now_iso(),
                )
            )
            db.commit()

    def _user_count(self) -> int:
        with self.Session() as db:
            return len(db.scalars(select(User.id)).all())

    def _register(self, email: str, code: str, password: str = "1234"):
        return self.client.post(
            "/api/auth/register", json={"email": email, "code": code, "password": password}
        )

    # --- 用例 1（本次核心）---

    def test_code_cannot_be_used_with_a_different_email(self):
        """A 邮箱发码 → B 邮箱 + A 的 code 调 /register → 400，且不建用户。"""
        sent = self.client.post(
            "/api/auth/send-code", json={"email": A, "purpose": "register"}
        )
        self.assertEqual(sent.status_code, 204, sent.text)
        code = self.mail.code_for(A)
        self.assertTrue(code, "发码成功却没有可用的验证码")

        before = self._user_count()
        resp = self._register(B, code)

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._user_count(), before, "跨邮箱换码不得建出任何用户")

    # --- 用例 2 ---

    def test_login_purpose_code_cannot_register(self):
        """purpose 也在查询条件里 —— 防「只按 code 查最新一条」这类放宽。

        这里不走走码接口：`/send-code` 的 login 分支要求邮箱已注册（否则 404），
        会把用例变成在测另一件事。直接落一行 purpose='login' 的码，要证的正是
        `/register` 的判据含 purpose。
        """
        self._add_code(A, "2468", purpose="login")

        resp = self._register(A, "2468")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._user_count(), 0)

    # --- 用例 3 ---

    def test_same_email_registers_and_marks_code_used(self):
        self._add_code(A, "1357")

        resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(self._user_count(), 1)
        with self.Session() as db:
            row = db.scalars(select(VerifyCode).where(VerifyCode.email == A)).one()
            self.assertEqual(row.used, 1, "用过的码必须置 used=1")

    # --- 用例 4 ---

    def test_code_cannot_be_used_twice(self):
        self._add_code(A, "1357")
        self.assertEqual(self._register(A, "1357").status_code, 201)

        # 第二次换成 B 邮箱：同邮箱重注册会先撞 409「该邮箱已注册」，
        # 那样证到的是查重，不是 used 这条判据。
        resp = self._register(B, "1357")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._user_count(), 1)

    # --- 用例 5 ---

    def test_expired_code_is_rejected(self):
        self._add_code(A, "1357", expire_seconds=-1)

        resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._user_count(), 0)

    # --- 用例 6 ---

    def test_existing_email_conflicts_before_code_check(self):
        """查重先于验证码校验 —— 保持现有顺序，别在重构里被调换。"""
        self._add_user(A)

        resp = self._register(A, "0000")  # 码压根不对，也不该走到验证码那一步

        self.assertEqual(resp.status_code, 409, resp.text)


if __name__ == "__main__":
    unittest.main()
