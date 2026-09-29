"""【】结构化解析（Spec1 §5.3）。

纯函数，不碰数据库、不碰网络 —— 便于单测覆盖全部四态。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

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

# 参考链接里的 URL。刻意排除空白与中英文括号、方括号、尖括号、引号、中文标点 ——
# 模型爱在 URL 后面接「（注释）」「；第二条链接」「换行说明」，这些一律截断
# （Spec2 §9.1 的四种脏形态）。
URL_RE = re.compile(r"https?://[^\s（）()【】\[\]<>\"'，。；、]+")
# 紧贴 URL 的句末标点：正则允许它们出现在 URL 内，故捕获后需从尾部剥离
URL_TRAILING_JUNK = ".,;:!?、。；：！？"

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


# --- 参考链接清洗（Spec2 §9.3 第 2 层）---
#
# 模型的原始返回从未被清洗过，实库里点开即 404 的脏值有四种形态（§9.1）。
# 这里不信任模型，一律按「取第一条 URL」收口。


def _norm_for_compare(u: str) -> str:
    """比较用规范化：去 fragment/query、去尾斜杠、转小写。

    只用于比对，**不得**拿它覆盖入库的原始 URL —— 路径大小写可能是有意义的。
    """
    return u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def is_source_site(url: str, sites: Iterable[str]) -> bool:
    """URL 是否就是把来源站原样回填（Spec2 §9.3）。"""
    return any(_norm_for_compare(url) == _norm_for_compare(s) for s in sites)


def is_aggregation_page(url: str, sites: Iterable[str]) -> bool:
    """URL 是否是聚合/列表页，而非该技术的具体来源页（§9.2 裁决 1）。

    两条判据：

    - **只有域名没有路径**（`https://paperswithcode.co/`）—— 具体来源页不可能长这样
    - **来源站的祖先路径**（`https://huggingface.co/papers` 之于
      `https://huggingface.co/papers/trending`）—— 模型找不到具体页面时，
      会把榜单页裁掉尾巴再填回来，比原样回填更难发现
    """
    if urlsplit(url).path in ("", "/"):
        return True
    norm = _norm_for_compare(url)
    return any(_norm_for_compare(s).startswith(norm + "/") for s in sites)


def normalize_ref_link(raw: str | None, sites: Iterable[str] = ()) -> str | None:
    """从模型返回的【参考链接】原文里提取唯一规范 URL。

    模型常见四种脏写法，全部在这里收口：

      - "https://a/b （注释文字）"      → https://a/b
      - "https://a/b ；https://c/d"     → https://a/b（取第一条）
      - "https://a/b\\n\\n补充说明…"     → https://a/b
      - 无 URL / 空值                    → None

    另外拒掉「把来源站原样回填」的偷懒写法：与 source_sites 任一条相同时
    返回 None —— 聚合榜页不是这项技术的具体来源页。同理见
    `is_aggregation_page`。

    None 不是丢弃信号：条目照常保留，由前端显示「暂无链接，建议上网搜索」。
    """
    if not raw:
        return None
    match = URL_RE.search(raw)
    if not match:
        return None
    url = match.group(0).rstrip(URL_TRAILING_JUNK)  # 剥离紧贴 URL 的句末标点
    if not url or is_source_site(url, sites) or is_aggregation_page(url, sites):
        return None
    return url


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


def parse(
    raw_text: str, max_items: int = 5, sites: Iterable[str] = ()
) -> tuple[str, list[dict]]:
    """解析模型返回的正文。

    返回 (status, items)。status ∈ success / empty / parse_failed。

    `sites` 是来源站 URL 列表，仅用于剔除「把来源站原样回填」的参考链接
    （Spec2 §9.3）。清洗后为 None 的条目照样保留。
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
        item["ref_link"] = normalize_ref_link(item.get("ref_link"), sites)
        items.append(item)

    if not items:
        # 覆盖 §5.3 步骤 5，并兼容「零段落 + 零丢弃」的纯乱码输入（§11 #18）
        return STATUS_PARSE_FAILED, []

    return STATUS_SUCCESS, items[:max_items]
