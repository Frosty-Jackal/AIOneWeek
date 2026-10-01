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
EMPTY_WORDS = ("无", "没有", "暂无", "未有", "未发现", "未检索到", "none")
# 去掉空白与标点后，正文长于此值就不再考虑「无」分支。取值只作兜底：
# 真正的判别靠下面两条（无【技术名】、整段是散文），长度只用来挡失控长文，
# 故留足一句自然语言的余量。
MAX_EMPTY_LEN = 60
# 书名号与引号类括号也算噪声。原集合只有【】（）—— 漏了「」，于是
# 「符合「有创新或性能明显提升」这一标准的技术」这类回复在 PROSE_RE 一步就被挡掉。
NOISE_RE = re.compile(
    r"[\s。.，,！!？?~～、；;：:\"'“”‘’（）()\[\]【】「」『』《》〈〉…\-—*#]"
)
# 「无」的陈述由汉字、数字、英文字母组成。乱码里的 ▲、模板残片、控制字符
# 在这一步就被挡掉 —— Spec1 #18 要求纯乱码落 parse_failed。
# 写成码点而不是把汉字直接敲进来：U+9FFF 那个字长得像「鿿」，读者看不出范围到哪。
PROSE_RE = re.compile("^[一-鿿0-9a-z]+$")
# 失败语汇。这类回复里同样会出现「无」字（「我无法完成」），但它说的是「做不到」，
# 与「今天没有」语义相反；判成 empty 会让前端显示「这日无前沿 AI 技术」，把一次
# 解析异常伪装成一次正常的空结果。
#
# 只保留「能力 / 系统层面的否认」。原先的 抱歉 / sorry 已移出（Spec3 §8.4）：
# 模型对「确实没有」同样会道歉，把它们当否决词，等于把最常见的一种「无」判成
# 解析异常 —— 正是本次要修的 Bug。泛否定的反向误判改由强信号先判来避免。
FAILURE_WORDS = (
    "无法",
    "不能",
    "失败",
    "错误",
    "报错",
    "超时",
    "异常",
    "timeout",
    "error",
    "failed",
    "unable",
    "cannot",
    "拒绝",
    "不可用",
)

# 「无」的两级判据（Spec3 §8.4）
#
# 强信号：否定词与结果动词**紧邻**。它说的是「检索跑完了，结果为空」，与「我做不到」
# 语义相反，故先于 FAILURE_WORDS 判定 —— 模型说「今天没有」时常先道歉
# （「很抱歉……未检索到……」），礼貌语不该把它打成解析异常。
#
# 调用层失败根本走不到这里：DeepSeekError 在 collector 就落 failed。所以这道豁免
# 防的只是「模型在正文里声称自己做不到」，而那种回复几乎不会出现「否定词 + 结果动词」
# 的紧邻结构 —— 这就是强信号可以跳过否决词的底气。
STRONG_ABSENT_RE = re.compile(
    r"(?:未|没有|暂无|无法|未能|没能|未曾)"
    r"(?:检索到|搜索到|搜到|搜寻到|找到|发现|查到|获取到|检出)"
)
# 强信号是结构化否定式，误判风险低，故放宽长度上限（弱信号路径仍守 MAX_EMPTY_LEN）
STRONG_MAX_LEN = 120

# 参考链接里的 URL。刻意排除空白、方括号、尖括号、引号与中英文标点 ——
# 模型爱在 URL 后面接「（注释）」「；第二条链接」「换行说明」，这些一律截断
# （Spec2 §9.1 的四种脏形态）。
#
# ASCII 圆括号**不在**排除集里：维基百科一类条目的路径本身就带括号
# （/wiki/Attention_(machine_learning)），排除它等于把链接截成 404。
# 代价是「见 (url)」这类写法会把收尾的右括号吃进来，由 _strip_trailing_junk 配对剥掉。
# 同理，`,` `;` 与中文 `，；、` 一起排除，才能兑现 §9.3「多条只取第一条」——
# 只靠尾部剥离的话，「url1,url2」会被整个吞成一个 URL。
URL_RE = re.compile(r"https?://[^\s（）【】\[\]<>\"'，。；、,;]+")
# 紧贴 URL 的句末标点：正则允许它们出现在 URL 内，故捕获后需从尾部剥离
URL_TRAILING_JUNK = ".,;:!?、。；：！？"


def _strip_trailing_junk(url: str) -> str:
    """剥掉紧贴 URL 的句末标点，以及**不成对**的右括号。

    成对的括号一律保留（那是路径的一部分）；多出来的右括号才去掉。
    """
    url = url.rstrip(URL_TRAILING_JUNK)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url.rstrip(URL_TRAILING_JUNK)

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
    url = _strip_trailing_junk(match.group(0))  # 剥离句末标点与不成对的右括号
    if not url or is_source_site(url, sites) or is_aggregation_page(url, sites):
        return None
    return url


def is_empty_reply(text: str) -> bool:
    """§5.3 步骤 1：整段回复本身就是在说「无」，且不含任何【技术名】。

    早先只认「以 无/没有/none 开头」的字面前缀。Spec2 §10 #10 明文禁止新 prompt
    因此把结果变成 parse_failed，而更严的 prompt 恰恰更容易让模型一无所获、
    于是它未必照 prompt 说的只回一个「无」字，而会回一整句
    「今日无符合条件的技术或模型。」—— 前缀是「今」，旧判据直接漏判。

    所以判据改成「短篇散文 + 含否定词」，再用两条护栏挡反向误判：
    整段不含【技术名】（有标记就交给正常解析分支），且不含失败语汇。
    反向误判比漏判更糟：empty 会被前端渲染成「这日无前沿 AI 技术」，
    把解析异常说成一次正常的空结果。

    Spec3 §8.4 把判据分成两级 —— 区分「检索跑完了但结果是空」与「我做不到」：

    - **强信号**（否定词紧贴结果动词）先判，不被礼貌语误伤；
    - **弱信号**（泛否定）语义依赖上下文，保留否决词一票否决。

    一条刻意保留的边界：**「错误：未找到结果」这类混合文本会判 empty**。语义上无从
    区分，若判 parse_failed 就又回到「用户点一次看一次『管理员可修正』」。倒向 empty
    是有意取舍：模型能正常返回时，「无」比「解析异常」更接近事实。
    """
    stripped = (text or "").strip()
    if not stripped or NAME_MARKER in stripped:
        return False
    core = NOISE_RE.sub("", stripped).lower()
    if not core or not PROSE_RE.match(core):  # 乱码、模板残片
        return False

    # 强信号优先：否定词紧贴结果动词 = 「检索跑完了，结果为空」
    if STRONG_ABSENT_RE.search(core) and len(core) <= STRONG_MAX_LEN:
        return True

    if len(core) > MAX_EMPTY_LEN:
        return False
    if any(word in core for word in FAILURE_WORDS):  # 「做不到」≠「没有」
        return False
    return any(word in core for word in EMPTY_WORDS)


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
