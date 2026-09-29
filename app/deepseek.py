"""DeepSeek Anthropic 兼容端点调用封装（Spec1 §5.2）。

联网搜索只有该端点可用：/responses 的内置工具被官方标注「忽略」且不报错，
实测返回 200 但 output 中无任何搜索项。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import settings

logger = logging.getLogger(__name__)

RETRY_INTERVAL_SECONDS = 2.0

# 峰时窗口（UTC，周一至周五）：01:00-04:00 与 06:00-10:00，价格翻倍
PEAK_WINDOWS_MINUTES = ((60, 240), (360, 600))


class DeepSeekError(RuntimeError):
    """调用失败：网络/超时/HTTP 错误/未联网/正文为空。

    raw 保留最后一次拿到的原始响应（如果有），供 daily_run.raw_response 存档 ——
    否则失败日只剩一句笼统描述，事后无法判断模型到底返回了什么。
    """

    def __init__(self, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


@dataclass
class CallResult:
    text: str  # 拼接后的正文，交给 parser
    raw: str  # 原始响应全文，写入 daily_run.raw_response
    cost_cny: float
    search_requests: int = 0


def is_peak(now: datetime | None = None) -> bool:
    """当前是否处于峰时（Spec1 §5.2）。"""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # 周六、周日全为闲时
        return False
    minutes = now.hour * 60 + now.minute
    return any(start <= minutes < end for start, end in PEAK_WINDOWS_MINUTES)


def _cost_cny(usage: dict, peak: bool) -> float:
    """按 token 计费，无按次搜索费（Spec1 §5.2）。"""
    in_tokens = int(usage.get("input_tokens") or 0)
    out_tokens = int(usage.get("output_tokens") or 0)
    multiplier = 2.0 if peak else 1.0
    usd = (
        (in_tokens * settings.in_price_usd_per_1m)
        + (out_tokens * settings.out_price_usd_per_1m)
    ) / 1_000_000 * multiplier
    return round(usd * settings.usd_cny, 6)


def _build_body(prompt: str, use_search: bool) -> dict:
    body: dict = {
        "model": settings.deepseek_model,
        "max_tokens": settings.deepseek_max_tokens,  # Anthropic 格式必填
        "messages": [{"role": "user", "content": prompt}],
    }
    if use_search:
        body["tools"] = [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": settings.deepseek_search_max_uses,
            }
        ]
    return body


def _extract(data: dict, require_search: bool) -> tuple[CallResult | None, str]:
    """从 content 数组提取正文，并做联网成功判定（Spec1 §5.2）。

    返回 (结果, 失败原因)；结果为 None 时原因用于日志与错误信息。
    """
    content = data.get("content")
    if not isinstance(content, list):
        return None, "响应缺少 content 数组"

    texts: list[str] = []
    has_tool_use = False
    has_tool_result = False
    searches = 0

    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            piece = item.get("text")
            if isinstance(piece, str) and piece.strip():
                texts.append(piece.strip())
        elif item_type == "server_tool_use" and item.get("name") == "web_search":
            has_tool_use = True
            searches += 1
        elif item_type == "web_search_tool_result":
            has_tool_result = True

    text = "\n".join(texts).strip()
    if not text:
        return None, f"正文为空（content 类型：{[i.get('type') for i in content if isinstance(i, dict)]}）"

    # 仅取到文本而无联网痕迹 → 视为未联网，按失败处理并重试
    if require_search and not (has_tool_use and has_tool_result):
        return None, (
            "模型未触发联网搜索（无 server_tool_use/web_search_tool_result，"
            f"正文 {len(text)} 字）"
        )

    usage = data.get("usage") or {}
    server_use = usage.get("server_tool_use")
    if isinstance(server_use, dict):
        searches = int(server_use.get("web_search_requests") or searches)

    return (
        CallResult(
            text=text,
            raw=json.dumps(data, ensure_ascii=False, indent=2),
            cost_cny=_cost_cny(usage, is_peak()),
            search_requests=searches,
        ),
        "",
    )


def call_deepseek(prompt: str, use_search: bool = True) -> CallResult:
    """调用模型。失败重试 settings.deepseek_max_retry 次，间隔 2 秒。"""
    url = f"{settings.deepseek_base_url}/anthropic/v1/messages"
    headers = {
        "x-api-key": settings.deepseek_api_key,  # 不是 Authorization: Bearer
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = _build_body(prompt, use_search)

    last_error = "未知错误"
    last_raw: str | None = None

    for attempt in range(settings.deepseek_max_retry + 1):
        if attempt:
            time.sleep(RETRY_INTERVAL_SECONDS)
        try:
            with httpx.Client(timeout=settings.deepseek_timeout) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            last_error = f"网络错误：{exc}"
            logger.warning("采集第 %d 次失败：%s", attempt + 1, last_error)
            continue

        if response.status_code >= 400:
            last_error = f"HTTP {response.status_code}：{response.text[:300]}"
            last_raw = response.text[:20000]
            logger.warning("采集第 %d 次失败：%s", attempt + 1, last_error)
            continue

        try:
            data = response.json()
        except ValueError:
            last_error = "响应不是合法 JSON"
            last_raw = response.text[:20000]
            logger.warning("采集第 %d 次失败：%s", attempt + 1, last_error)
            continue

        result, reason = _extract(data, require_search=use_search)
        if result is None:
            last_error = reason
            # 关键：失败也要把原始返回带出去，否则失败日无从追查
            last_raw = json.dumps(data, ensure_ascii=False, indent=2)
            logger.warning("采集第 %d 次失败：%s", attempt + 1, last_error)
            continue
        return result

    raise DeepSeekError(last_error, raw=last_raw)
