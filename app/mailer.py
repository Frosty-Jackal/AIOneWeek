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


def send_code(to_email: str, code: str) -> None:
    body = f"您的验证码为：{code}"
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = Header(SUBJECT, "utf-8")
    message["From"] = f"{Header(settings.smtp_from_name, 'utf-8').encode()} <{settings.smtp_user}>"
    message["To"] = to_email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=context, timeout=20
        ) as server:
            server.login(settings.smtp_user, settings.smtp_auth_code)
            server.sendmail(settings.smtp_user, [to_email], message.as_string())
    except Exception as exc:  # noqa: BLE001 —— SMTP 异常种类繁多，统一转 502
        logger.warning("发送验证码到 %s 失败：%s", to_email, exc)
        raise MailError(str(exc)) from exc
