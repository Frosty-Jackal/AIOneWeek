"""Spec3 §10.3 / §10.8 —— 两封信的报文契约。

打桩打在 `smtplib.SMTP_SSL` 上，用 `email.message_from_string()` 解析**真实组装
出来**的报文，断言主题 / 收件人 / 正文三个字段 —— 而不是断言「我们调用了一个
函数」。§10.3 把 SMTP 连接那 8 行从 `send_code()` 里抽出来共用，`send_code` 是
Spec1 §6.1 已交付的契约（`auth.py` 在用），所以这里同时守它的两项不变。
"""

from __future__ import annotations

import os
import unittest
from email import message_from_string
from email.header import decode_header, make_header
from pathlib import Path
from unittest.mock import patch

from app import mailer
from app.config import BASE_DIR, Settings, settings

USER_EMAIL = "newuser@example.com"
OTHER = "somebody-else@example.com"


class _FakeSMTP:
    """记下每一次发信。上下文管理器 + login + sendmail，就是 mailer 用到的那三样。"""

    instances: list["_FakeSMTP"] = []
    # 类属性：mailer 每发一封信都新建一个实例，设成实例属性只能影响已建出来的那个
    fail: Exception | None = None

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.sent: list[tuple[str, list[str], str]] = []
        self.login_args: tuple[str, str] | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, auth_code):
        self.login_args = (user, auth_code)

    def sendmail(self, from_addr, to_addrs, raw):
        if self.fail is not None:
            raise self.fail
        self.sent.append((from_addr, list(to_addrs), raw))


def _text(value: str | None) -> str:
    """把 `Header(…, 'utf-8')` 编出来的 `=?utf-8?b?…?=` 解回原始字符串。"""
    return str(make_header(decode_header(value or "")))


class _MailerTest(unittest.TestCase):
    def setUp(self):
        _FakeSMTP.instances = []
        patcher = patch.object(mailer.smtplib, "SMTP_SSL", _FakeSMTP)
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def server(self) -> _FakeSMTP:
        return _FakeSMTP.instances[-1]

    def _message(self):
        """返回 (解析后的报文, 信封发件人, 信封收件人)。

        「信封发件人」是 `sendmail()` 的第一个参数（裸地址），≠ 报文里的 `From`
        头（带显示名）。要断显示名得读 `msg["From"]`。
        """
        envelope_from, to_addrs, raw = self.server.sent[-1]
        return message_from_string(raw), envelope_from, to_addrs

    def _fail_next_sends(self, exc: Exception) -> None:
        self.addCleanup(setattr, _FakeSMTP, "fail", None)
        _FakeSMTP.fail = exc


class SendCodeContractTest(_MailerTest):
    """`send_code()` 的对外签名、主题、正文一字不变（§10.3 的重构没改坏它）。"""

    def test_subject_recipient_and_body_are_unchanged(self):
        mailer.send_code("u@example.com", "8421")

        msg, sender, to_addrs = self._message()
        self.assertEqual(_text(msg["Subject"]), "AIOneWeek验证码")
        self.assertEqual(_text(msg["To"]), "u@example.com")
        self.assertEqual(to_addrs, ["u@example.com"])
        self.assertEqual(msg.get_payload(decode=True).decode("utf-8"), "您的验证码为：8421")

    def test_from_header_keeps_the_display_name(self):
        """显示名走 `Header(...).encode()` —— 直接改 From 头会把中文名发成乱码。"""
        mailer.send_code("u@example.com", "8421")

        msg, envelope_from, _to = self._message()
        self.assertEqual(_text(msg["From"]), f"{settings.smtp_from_name} <{settings.smtp_user}>")
        self.assertEqual(envelope_from, settings.smtp_user)

    def test_smtp_failure_becomes_mail_error(self):
        """接口层靠这个异常回 502 —— 别的异常类型会漏成 500。"""
        self._fail_next_sends(OSError("连不上"))
        with self.assertRaises(mailer.MailError):
            mailer.send_code("u@example.com", "8421")


class SendRegisterNoticeTest(_MailerTest):
    """新用户注册通知（§10.1 的落地口径）。"""

    def test_subject_and_body_match_the_request_verbatim(self):
        mailer.send_register_notice(USER_EMAIL)

        msg, _sender, _to = self._message()
        self.assertEqual(_text(msg["Subject"]), "新用户注册")
        self.assertEqual(
            msg.get_payload(decode=True).decode("utf-8"),
            f"新用户{USER_EMAIL}已注册！",
        )

    def test_body_has_no_padding_spaces_around_the_address(self):
        """§10.1：拉丁字符两侧留空格是**页面排版**规则，邮件正文是另一套场景。

        模板逐字替换即可，与 `mailer.py` 的「您的验证码为：{code}」同一处理。
        """
        mailer.send_register_notice(USER_EMAIL)

        body = self._message()[0].get_payload(decode=True).decode("utf-8")
        self.assertNotIn(" ", body)

    def test_recipient_is_read_from_settings_at_call_time(self):
        """收件人从 settings 现读、不做参数 —— 换地址只动 .env，调用点不必知道。"""
        with patch.object(settings, "register_notify_email", OTHER):
            mailer.send_register_notice(USER_EMAIL)

        _msg, _from, to_addrs = self._message()
        self.assertEqual(to_addrs, [OTHER])

    def test_default_recipient_is_the_requested_address(self):
        """`REGISTER_NOTIFY_EMAIL` 没配时用默认值 —— 用户要的就是这个地址。

        `Settings.__init__` 每次现读 `os.environ`，故构造一个新实例即可观测默认值；
        不去 reload 模块 —— 那会让别处持有的 settings 对象失联。
        """
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REGISTER_NOTIFY_EMAIL", None)
            fresh = Settings()
        self.assertEqual(fresh.register_notify_email, "frostyj@qq.com")

    def test_smtp_failure_becomes_mail_error(self):
        """与 `send_code` 同一套失败语义：抛 `MailError`，由调用方决定怎么处理。

        `auth.py` 对这两封信的处理**刻意相反**（一个回 502，一个只记日志）——
        差异来自「这封信对谁重要」，不是不一致（§10.5）。
        """
        self._fail_next_sends(OSError("连不上"))
        with self.assertRaises(mailer.MailError):
            mailer.send_register_notice(USER_EMAIL)


class AddressLivesInConfigOnlyTest(unittest.TestCase):
    """§10.8 —— 地址只从配置读，不得出现在任何逻辑分支里。"""

    def _app_files(self) -> list[Path]:
        return sorted((BASE_DIR / "app").rglob("*.py"))

    def test_literal_address_appears_only_as_the_config_default(self):
        hits = [
            (p.name, i, line.strip())
            for p in self._app_files()
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "frostyj@qq.com" in line
        ]
        self.assertEqual(
            len(hits), 1, f"字面地址应只作为 config.py 的默认值出现一次，实际：{hits}"
        )
        self.assertEqual(hits[0][0], "config.py", f"字面地址跑到了别处：{hits[0]}")

    def test_settings_name_is_referenced_in_exactly_three_files(self):
        """config.py（定义默认值）/ mailer.py（取收件人）/ auth.py（判空）。"""
        files = {
            p.name
            for p in self._app_files()
            if "register_notify_email" in p.read_text(encoding="utf-8")
        }
        self.assertEqual(files, {"config.py", "mailer.py", "auth.py"})

    def test_dotenv_example_names_the_same_variable(self):
        """PRD 里写的是环境变量名 `REGISTER_NOTIFY_EMAIL`，代码里读的是
        `settings.register_notify_email` —— 同一件事的两端，两个名字都要在。"""
        example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertIn("REGISTER_NOTIFY_EMAIL=", example)


if __name__ == "__main__":
    unittest.main()
