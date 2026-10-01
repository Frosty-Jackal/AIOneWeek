"""配置读取。

Spec1 §3 硬性要求 3：缺失 DEEPSEEK_API_KEY / FERNET_KEY / SESSION_SECRET 时
启动即报错退出，不允许静默降级。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """配置缺失或非法。启动阶段抛出，直接终止进程。"""


def _req(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ConfigError(
            f"缺少必需配置 {name}。请复制 .env.example 为 .env 并填写后重启。"
        )
    return value


def _opt(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _num(name: str, default, cast):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"配置 {name}={raw!r} 不是合法数值") from exc


class Settings:
    """全部运行期配置。代码中不得出现任何密钥字面量，一律经此读取。"""

    def __init__(self) -> None:
        # --- 必需项：缺失即启动失败 ---
        self.deepseek_api_key: str = _req("DEEPSEEK_API_KEY")
        self.fernet_key: str = _req("FERNET_KEY")
        self.session_secret: str = _req("SESSION_SECRET")

        # --- DeepSeek（走 Anthropic 兼容端点，Spec1 §5.2）---
        self.deepseek_base_url: str = _opt(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/")
        self.deepseek_model: str = _opt("DEEPSEEK_MODEL", "deepseek-flash")
        self.deepseek_timeout: float = _num("DEEPSEEK_TIMEOUT", 30.0, float)
        # 模型偶尔不触发联网搜索，多试一次能明显降低整日失败率
        self.deepseek_max_retry: int = _num("DEEPSEEK_MAX_RETRY", 2, int)
        self.deepseek_max_tokens: int = _num("DEEPSEEK_MAX_TOKENS", 4096, int)
        self.deepseek_search_max_uses: int = _num("DEEPSEEK_SEARCH_MAX_USES", 3, int)

        # --- 邮件 ---
        self.smtp_host: str = _opt("SMTP_HOST", "smtp.qq.com")
        self.smtp_port: int = _num("SMTP_PORT", 465, int)
        self.smtp_user: str = _opt("SMTP_USER", "")
        self.smtp_auth_code: str = _opt("SMTP_AUTH_CODE", "")
        self.smtp_from_name: str = _opt("SMTP_FROM_NAME", "AIOneWeek")
        # 新用户注册通知的收件地址（Spec3 §10）。留空 = 关闭该通知，
        # 便于本地开发与自动化测试不发信。与 admin_email 同一原则：
        # 地址进 .env，不进代码逻辑 —— 这里的字面量只是「没配时的默认值」。
        self.register_notify_email: str = _opt("REGISTER_NOTIFY_EMAIL", "frostyj@qq.com")

        # --- 业务 ---
        raw_db = _opt("DB_PATH", "./data/aioneek.db")
        db_path = Path(raw_db)
        self.db_path: str = str(
            db_path if db_path.is_absolute() else (BASE_DIR / db_path).resolve()
        )
        self.admin_email: str = _opt("ADMIN_EMAIL", "")
        self.admin_init_password: str = _opt("ADMIN_INIT_PASSWORD", "")
        self.cost_daily_limit_cny: float = _num("COST_DAILY_LIMIT_CNY", 2.0, float)
        self.usd_cny: float = _num("USD_CNY", 7.1, float)
        self.week_window_days: int = _num("WEEK_WINDOW_DAYS", 7, int)
        self.max_items_per_day: int = _num("MAX_ITEMS_PER_DAY", 5, int)
        self.code_ttl_seconds: int = _num("CODE_TTL_SECONDS", 600, int)
        self.code_resend_interval: int = _num("CODE_RESEND_INTERVAL", 120, int)

        # --- 计价常量：deepseek-flash 闲时价，峰时翻倍（Spec1 §5.2）---
        self.in_price_usd_per_1m: float = 0.15
        self.out_price_usd_per_1m: float = 0.6

        # --- 会话 ---
        self.session_ttl_seconds: int = 7 * 24 * 3600


settings = Settings()
