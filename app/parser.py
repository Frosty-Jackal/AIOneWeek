"""【】结构化解析（Spec1 §5.3）。

纯函数，不碰数据库、不碰网络 —— 便于单测覆盖全部四态。
"""

from __future__ import annotations

import re

NAME_MARKER = "【技术名】"
FIELD_MARKERS = (
    "【技术内容】",
    "【技术创新】",
    "【应用场景】",
    "【发布时间】",
    "【参考链接】",
)
REQUIRED_FIELDS = ("tech_name", "tech_content", "innovation")
SCENARIO_SEP_RE = re.compile(r"[、，,]")
EMPTY_WORDS = ("无", "none", "没有")
# 去掉空白与标点后，正文长于此值就不再考虑「无」分支
MAX_EMPTY_LEN = 20
NOISE_RE = re.compile(r"[\s。.，,！!？?~～、；;：:\"'“”‘’（）()\[\]【】\-—*#]")

# daily_run.status 的四个取值集中在此定义，避免散落字符串字面量。
# 前三个是解析结果；STATUS_FAILED 是调用层面的失败（网络/超时/未联网），
# 由 collector 写入，不经过 parser。
STATUS_SUCCESS = "success"
STATUS_EMPTY = "empty"
STATUS_PARSE_FAILED = "parse_failed"
STATUS_FAILED = "failed"


def _extract(segment: str, marker: str) -> str:
    """取标记之后、下一个「【」之前的文本，strip 首尾空白与换行（§5.3 步骤 3）。"""
    pos = segment.find(marker)
    if pos < 0:
        return ""
    rest = segment[pos + len(marker) :]
    nxt = rest.find("【")
    if nxt >= 0:
        rest = rest[:nxt]
    return rest.strip()


def _split_scenarios(raw: str) -> list[str]:
    """按 、，, 切分；不足 3 个用原文整体作 1 个元素；多于 3 个截前 3（§5.3 步骤 3）。"""
    parts = [p.strip() for p in SCENARIO_SEP_RE.split(raw) if p.strip()]
    if len(parts) >= 3:
        return parts[:3]
    whole = raw.strip()
    return [whole] if whole else []


def is_empty_reply(text: str) -> bool:
    """§5.3 步骤 1：整段回复本身就是在说「无」，且不含任何【技术名】。

    判据是「去掉空白与标点后以 无/没有/none 开头，且长度不超过
    MAX_EMPTY_LEN」。不能用子串包含来判断 —— 正常回复或纯乱码里
    恰好出现「没有」二字（如「…没有标记的文字…」）会被误判成
    「这日无前沿 AI 技术」，掩盖真正的 parse_failed。
    """
    stripped = (text or "").strip()
    if not stripped or NAME_MARKER in stripped:
        return False
    core = NOISE_RE.sub("", stripped).lower()
    if not core or len(core) > MAX_EMPTY_LEN:
        return False
    return any(core.startswith(word) for word in EMPTY_WORDS)


def parse(raw_text: str, max_items: int = 5) -> tuple[str, list[dict]]:
    """解析模型返回的正文。

    返回 (status, items)。status ∈ success / empty / parse_failed。
    """
    text = (raw_text or "").strip()

    if is_empty_reply(text):
        return STATUS_EMPTY, []

    segments = text.split(NAME_MARKER)[1:]  # 丢弃首个【技术名】之前的杂讯
    if not segments:
        # 有返回但一条都解析不出（含纯乱码）→ parse_failed
        return STATUS_PARSE_FAILED, []

    items: list[dict] = []
    dropped = 0

    for segment in segments:
        # 段内以【技术名】开头，故技术名同样按「到下一个【为止」取值
        item = {"tech_name": _extract(NAME_MARKER + segment, NAME_MARKER)}
        for marker in FIELD_MARKERS:
            key = {
                "【技术内容】": "tech_content",
                "【技术创新】": "innovation",
                "【应用场景】": "scenarios",
                "【发布时间】": "publish_date",
                "【参考链接】": "ref_link",
            }[marker]
            item[key] = _extract(segment, marker)

        if any(not item.get(f) for f in REQUIRED_FIELDS):
            dropped += 1
            continue

        item["scenarios"] = _split_scenarios(item["scenarios"])
        item["publish_date"] = item["publish_date"] or None
        item["ref_link"] = item["ref_link"] or None
        items.append(item)

    if not items:
        # 覆盖 §5.3 步骤 5，并兼容「零段落 + 零丢弃」的纯乱码输入（§11 #18）
        return STATUS_PARSE_FAILED, []

    return STATUS_SUCCESS, items[:max_items]
