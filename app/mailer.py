"""QQ SMTP 发送验证码（Spec1 §6.1）。"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText

from .config import settings

logger = logging.getLogger(__name__)

SUBJECT = "AIOneWeek验证码"


class MailError(RuntimeError):
    """SMTP 发送失败。接口层据此返回 502，且不落库该验证码。"""


NOTIFY_SUBJECT = "新用户注册"


def _send(to_email: str, subject: str, body: str) -> None:
    """发一封纯文本邮件。失败统一抛 MailError，由调用方决定怎么处理。

    两封信共用同一段 SMTP 连接代码（Spec3 §10.3）—— 各写一遍早晚会漂移，
    而「连不上要转成 MailError」这类细节漂移起来是静默的。
    """
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = f"{Header(settings.smtp_from_name, 'utf-8').encode()} <{settings.smtp_user}>"
    message["To"] = to_email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=context, timeout=20
        ) as server:
            server.login(settings.smtp_user, settings.smtp_auth_code)
            server.sendmail(settings.smtp_user, [to_email], message.as_string())
    except Exception as exc:  # noqa: BLE001 —— SMTP 异常种类繁多，统一转 MailError
        logger.warning("发送邮件到 %s 失败：%s", to_email, exc)
        raise MailError(str(exc)) from exc


def send_code(to_email: str, code: str) -> None:
    """发验证码。对外签名、主题、正文一字不变 —— 这是 Spec1 §6.1 已交付的契约。"""
    _send(to_email, SUBJECT, f"您的验证码为：{code}")


def send_register_notice(user_email: str) -> None:
    """通知管理员有新用户注册（Spec3 §10）。正文逐字：新用户<邮箱>已注册！

    「用户名」= 该新用户的邮箱（系统里 `users` 表只有 email，没有用户名字段）。
    正文里的邮箱两侧不加空格 —— 「拉丁字符两侧留空格」是页面排版规则，邮件正文
    是另一套场景，上面那句验证码正文同样不补空格。

    收件人从 settings 现读、不做参数：调用点因此不必知道收件人是谁，换地址
    只动 .env。空值由调用方判（§10.4）—— 这里不替它决定。
    """
    _send(settings.register_notify_email, NOTIFY_SUBJECT, f"新用户{user_email}已注册！")
