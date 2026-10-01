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

from app.config import settings
from app.db import Base, get_db, now_iso
from app.main import app
from app.mailer import MailError
from app.models import User, VerifyCode
from app.security import encrypt_password

STAMP = "%Y-%m-%d %H:%M:%S"
A = "a@example.com"
B = "b@example.com"


def _stamp(delta_seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=delta_seconds)).strftime(STAMP)


class _FakeNotify:
    """假注册通知。记下每次调用，并**另开一个会话**确认那个用户此刻已提交。

    后者是「必须在 `db.commit()` 之后发信」的直接证据（Spec3 §10.4）：先发信后提交，
    一旦提交失败（并发下 `UNIQUE(email)` 撞车），管理员会收到一封指向**不存在的用户**
    的假通知 —— 一个凭空造出来的「新用户」比漏掉一封通知糟得多。
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.calls: list[str] = []
        self.user_was_committed: list[bool] = []
        self.fail: Exception | None = None

    def __call__(self, user_email: str) -> None:
        self.calls.append(user_email)
        with self.session_factory() as db:
            self.user_was_committed.append(
                db.scalar(select(User).where(User.email == user_email)) is not None
            )
        if self.fail is not None:
            raise self.fail


class _FakeMail:
    """记录发信调用的假 SMTP：验证码从这里读，别去猜 `generate_code()`。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, to_email: str, code: str) -> None:
        self.calls.append((to_email, code))

    def code_for(self, email: str) -> str:
        return [code for to, code in self.calls if to == email][-1]


# 故意**不**继承 TestCase：unittest 会把模块里每个 TestCase 子类都收集一遍，
# 基类自己也继承的话，它的 6 条用例会在两个子类里各跑一遍。
class _AuthCase:
    """`/api/auth/*` 的夹具。全部打在临时库上，绝不碰 `./data/aioneek.db`。"""

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
        # 注册通知（Spec3 §10）。同样打在 `app.routers.auth` 上 —— 也是值导入。
        # 这个 fake 另开一个会话来查那个新用户，用来证「先 commit 后发信」。
        self.notify = _FakeNotify(self.Session)
        notify_patcher = patch("app.routers.auth.send_register_notice", self.notify)
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

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

class AuthRulesTest(_AuthCase, unittest.TestCase):
    """验证码与邮箱的绑定 —— 回归护栏（§9.5）。"""

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

    def test_already_used_code_is_rejected(self):
        """`used == 0` 本身就是查询条件之一 —— 直接落一行用过的码来钉住它。

        只靠「同邮箱重注册撞 409」是证不到这条的：那种写法第二次会换一个邮箱，
        于是拦下它的是 `email` 绑定，`used` 从查询里删掉也照样绿。
        """
        self._add_code(A, "1357", used=1)

        resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._user_count(), 0)

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


class RegisterNoticeTest(_AuthCase, unittest.TestCase):
    """Spec3 §10.8 —— 新用户注册成功的通知邮件。"""

    def test_success_notifies_once_with_the_new_email(self):
        self._add_code(A, "1357")

        resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(self.notify.calls, [A])

    def test_notification_is_sent_after_the_commit(self):
        """发信时那个用户必须已经提交 —— 否则通知会指向一个不存在的用户。"""
        self._add_code(A, "1357")

        self._register(A, "1357")

        self.assertEqual(self.notify.user_was_committed, [True])

    def test_failed_notification_does_not_block_registration(self):
        """§10.5：这封信是旁路信息，用户**根本不知道有它**。

        为它报错，只会让注册成功的人以为自己没注册上 —— 所以状态码与响应体
        必须与成功时完全一致。
        """
        self._add_code(A, "1357")
        self.notify.fail = MailError("SMTP 挂了")

        resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertTrue(self.notify.calls, "通知确实被尝试过，只是失败了")
        self.assertEqual(self._user_count(), 1, "注册必须照常落库")

        # 与不失败时逐字一致（邮箱本身当然不同，那是唯一允许的区别）
        self._add_code(B, "2468")
        self.notify.fail = None
        ok = self._register(B, "2468")
        self.assertEqual(ok.status_code, 201, ok.text)
        mask = lambda body: {**body, "email": "同一个"}  # noqa: E731
        self.assertEqual(
            mask(resp.json()), mask(ok.json()), "响应体必须与成功时逐字一致"
        )

    def test_non_mail_error_does_not_block_registration(self):
        """§10.5 的规则是「发信失败只记日志」，不是「只对 MailError 网开一面」。

        `_send()` 把 SMTP 异常统一转成 MailError，但 try 之外还有一段 MIME 组装
        （`Header` / `MIMEText`），那里的异常会原样逃出来。只 catch MailError 的话，
        这种异常会让**已经提交**的注册返回 500 —— 用户以为自己没注册上，重试又撞
        409「该邮箱已注册」，从此卡死在一个他确实拥有的账号外面。
        """
        self._add_code(A, "1357")
        self.notify.fail = ValueError("MIME 组装炸了")

        # 默认的 TestClient 把服务端异常原样抛出来，看到的是 traceback，不是
        # 「用户实际收到什么」。这里要断的正是后者。
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        resp = client.post(
            "/api/auth/register", json={"email": A, "code": "1357", "password": "1234"}
        )

        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(self._user_count(), 1, "注册必须照常落库")

    def test_empty_recipient_turns_the_notification_off(self):
        """`REGISTER_NOTIFY_EMAIL=` → 连函数都不调用（§10.4）。"""
        self._add_code(A, "1357")

        with patch.object(settings, "register_notify_email", ""):
            resp = self._register(A, "1357")

        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(self.notify.calls, [], "空收件人时不该调用发信函数")
        self.assertEqual(self._user_count(), 1)

    def test_failure_paths_send_nothing(self):
        """400（码不对）与 409（邮箱已存在）都不是「新用户注册成功」。"""
        wrong = self._register(A, "0000")
        self.assertEqual(wrong.status_code, 400, wrong.text)

        self._add_user(B)
        duplicate = self._register(B, "0000")
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        self.assertEqual(self.notify.calls, [])

    def test_login_paths_send_nothing(self):
        """触发点是「注册成功」，不是登录（§10.1）。"""
        self._add_user(A)
        self._add_code(A, "1357", purpose="login")

        by_password = self.client.post(
            "/api/auth/login", json={"email": A, "password": "1234"}
        )
        by_code = self.client.post("/api/auth/login-code", json={"email": A, "code": "1357"})

        self.assertEqual(by_password.status_code, 200, by_password.text)
        self.assertEqual(by_code.status_code, 200, by_code.text)
        self.assertEqual(self.notify.calls, [])


if __name__ == "__main__":
    unittest.main()
