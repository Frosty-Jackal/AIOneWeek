"""Spec2 §9.4 —— 参考链接清洗的单测。

用例取自 §9.1 的四种脏形态，外加来源站回填、空值与用户追加裁决
（聚合页 / 裸域名一并判无效，见 §9.2 裁决 1 与本次执行的 R3）。
"""

from __future__ import annotations

import unittest

from app import parser

SITES = ("https://huggingface.co/papers/trending",)


class NormalizeRefLinkTest(unittest.TestCase):
    """§9.3 第 2 层：从模型返回的原文里提取唯一规范 URL。"""

    # --- §9.1 的四种脏形态 ---

    def test_url_with_parenthetical_note(self):
        """形态一：URL + 括号注释 → 只留 URL。"""
        raw = (
            "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash "
            "（论文聚合页 https://paperswithcode.co/）"
        )
        self.assertEqual(
            parser.normalize_ref_link(raw, SITES),
            "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash",
        )

    def test_multiple_urls_takes_first(self):
        """形态二：多个 URL 用「；」并列 → 取第一条。"""
        raw = (
            "https://arxiv.org/abs/2609.28256 ；项目页 "
            "https://declare-lab.github.io/MemBodied/"
        )
        self.assertEqual(
            parser.normalize_ref_link(raw, SITES), "https://arxiv.org/abs/2609.28256"
        )

    def test_url_followed_by_multiline_note(self):
        """形态三：URL + 换行说明 → 只留 URL。"""
        raw = (
            "https://huggingface.co/zai-org/GLM-5.3\n\n"
            "补充：若你需要严格锁定「2026年9月29日」当天的论文…"
        )
        self.assertEqual(
            parser.normalize_ref_link(raw, SITES),
            "https://huggingface.co/zai-org/GLM-5.3",
        )

    def test_trailing_sentence_punctuation_is_stripped(self):
        """紧贴 URL 的句末标点必须剥离（正则允许 . , ; : ! ? 出现在 URL 内）。"""
        self.assertEqual(
            parser.normalize_ref_link("见 https://arxiv.org/abs/2609.29808。", SITES),
            "https://arxiv.org/abs/2609.29808",
        )
        self.assertEqual(
            parser.normalize_ref_link("见 https://arxiv.org/abs/2609.29808.", SITES),
            "https://arxiv.org/abs/2609.29808",
        )

    # --- 无值 / 空值 ---

    def test_no_url_returns_none(self):
        self.assertIsNone(parser.normalize_ref_link("暂无链接", SITES))
        self.assertIsNone(parser.normalize_ref_link("无", SITES))

    def test_empty_values_return_none(self):
        for empty in (None, "", "   ", "\n"):
            with self.subTest(raw=empty):
                self.assertIsNone(parser.normalize_ref_link(empty, SITES))

    def test_row_with_null_ref_link_stays_null(self):
        """实库 2026-09-26 seq 4（BiCFlow-MER）的 ref_link = None。"""
        self.assertIsNone(parser.normalize_ref_link(None, SITES))

    # --- 来源站回填（§9.2 裁决 1 的反例）---

    def test_source_site_backfill_returns_none(self):
        self.assertIsNone(
            parser.normalize_ref_link("https://huggingface.co/papers/trending", SITES)
        )

    def test_source_site_backfill_with_note_returns_none(self):
        """实库 2026-09-27 的行：回填来源站并附「在榜」说明与第二个链接。"""
        raw = (
            "https://huggingface.co/papers/trending （2026-09-27 在榜）；"
            "https://www.02ship.com/news/2026-09-27"
        )
        self.assertIsNone(parser.normalize_ref_link(raw, SITES))

    def test_source_site_match_ignores_query_fragment_and_case(self):
        self.assertIsNone(
            parser.normalize_ref_link(
                "https://HuggingFace.co/papers/trending?tab=all#top", SITES
            )
        )

    # --- 用户追加裁决：聚合页 / 裸域名一并判无效 ---

    def test_bare_origin_returns_none(self):
        """实库 2026-09-29 seq 3：https://paperswithcode.co/ （StepAudio 3…）。"""
        raw = "https://paperswithcode.co/ （StepAudio 3 Realtime Technical Report）"
        self.assertIsNone(parser.normalize_ref_link(raw, SITES))

    def test_source_site_parent_path_returns_none(self):
        """实库 2026-09-24 五行：带日期参数的榜单页。"""
        for raw in (
            "https://huggingface.co/papers?date=2026-09-24",
            "https://huggingface.co/papers/ （HF Papers 当日趋势榜；arXiv 版本随榜展示）",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(parser.normalize_ref_link(raw, SITES))

    # --- 正常值必须原样保留 ---

    def test_normal_urls_are_kept_verbatim(self):
        cases = (
            "http://arxiv.org/abs/2609.29808v1",  # 协议不改写
            "https://huggingface.co/zai-org/GLM-5.3",
            "https://huggingface.co/papers/2609.02886",
            "https://www.aib.vote/en/news/jitmem-task-adaptive-memory-llm-agents",
            "https://aiweekly.co/alerts/jev-as-a-judge-paper-adds-confidence-gated-escalation-to-typed-decision-models",
            "https://academy.dair.ai/papers/agent-editing-world-model-rethinking-world-modeling-for-llm-agents-2609.28416",
            "https://idw-online.de/en/news877978",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parser.normalize_ref_link(raw, SITES), raw)

    def test_real_db_row_keeps_first_url(self):
        """实库 2026-09-02 seq 0 的原始取值。"""
        raw = (
            "https://huggingface.co/papers/2609.02886 ；"
            "https://arxiv.org/abs/2609.02886\n\n---"
        )
        self.assertEqual(
            parser.normalize_ref_link(raw, SITES),
            "https://huggingface.co/papers/2609.02886",
        )

    def test_no_sites_configured_still_cleans_format(self):
        """来源站列表为空时，格式清洗照常生效，只是不做回填判定。"""
        self.assertEqual(
            parser.normalize_ref_link("https://arxiv.org/abs/1 ；https://x/y", ()),
            "https://arxiv.org/abs/1",
        )


class HelpersTest(unittest.TestCase):
    """§9.3 第 2 层的两个判定函数。"""

    def test_is_source_site_is_exact_match_only(self):
        self.assertTrue(
            parser.is_source_site("https://huggingface.co/papers/trending/", SITES)
        )
        self.assertFalse(
            parser.is_source_site("https://huggingface.co/papers/2609.02886", SITES)
        )

    def test_is_aggregation_page_covers_bare_origin_and_ancestors(self):
        self.assertTrue(parser.is_aggregation_page("https://paperswithcode.co/", SITES))
        self.assertTrue(
            parser.is_aggregation_page("https://huggingface.co/papers", SITES)
        )
        self.assertFalse(
            parser.is_aggregation_page("https://huggingface.co/papers/2609.02886", SITES)
        )

    # --- ASCII 标点：括号要留、分隔符要断 ---

    def test_ascii_parentheses_inside_url_are_preserved(self):
        """维基百科式路径的圆括号是 URL 本体，截断后链接直接 404。"""
        for url in (
            "https://en.wikipedia.org/wiki/Attention_(machine_learning)",
            "https://en.wikipedia.org/wiki/A_(b)",
        ):
            with self.subTest(url=url):
                self.assertEqual(parser.normalize_ref_link(url, SITES), url)

    def test_unbalanced_trailing_ascii_parenthesis_is_stripped(self):
        """模型把链接括进括号写作「见 https://… )」时，那个右括号不属于 URL。"""
        self.assertEqual(
            parser.normalize_ref_link("见 (https://arxiv.org/abs/2609.29808v1)", SITES),
            "https://arxiv.org/abs/2609.29808v1",
        )
        self.assertEqual(
            parser.normalize_ref_link("https://arxiv.org/abs/2609.29808v1).", SITES),
            "https://arxiv.org/abs/2609.29808v1",
        )

    def test_ascii_separated_second_url_is_not_swallowed(self):
        """§9.3 承诺「多条只取第一条」—— ASCII 的 , ; 与中文 ；、同等对待。"""
        for raw in (
            "https://arxiv.org/abs/2609.29808v1, https://arxiv.org/abs/2609.02886",
            "https://arxiv.org/abs/2609.29808v1; https://arxiv.org/abs/2609.02886",
            "https://arxiv.org/abs/2609.29808v1,https://arxiv.org/abs/2609.02886",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parser.normalize_ref_link(raw, SITES),
                    "https://arxiv.org/abs/2609.29808v1",
                )

    def test_norm_for_compare_does_not_touch_stored_value(self):
        """规范化只用于比对：带 query 的合法 URL 入库时不得被改写。"""
        raw = "https://example.com/paper?id=7#sec2"
        self.assertEqual(parser.normalize_ref_link(raw, SITES), raw)


class ParseWithSitesTest(unittest.TestCase):
    """`parse()` 接收来源站后，条目的 ref_link 被就地清洗。"""

    RAW = (
        "【技术名】GLM-5.3\n"
        "【技术内容】输入文本，输出补全\n"
        "【技术创新】推理性能明显提升\n"
        "【应用场景】对话、写作、代码\n"
        "【发布时间】2026年9月29日\n"
        "【参考链接】https://huggingface.co/papers/trending （当日榜单）\n"
        "【技术名】BiCFlow-MER\n"
        "【技术内容】多模态情感识别\n"
        "【技术创新】显著提升识别率\n"
        "【应用场景】客服质检、教育、医疗\n"
        "【发布时间】2026年9月26日\n"
        "【参考链接】无\n"
    )

    def test_parse_cleans_ref_link_and_keeps_item(self):
        status, items = parser.parse(self.RAW, 5, SITES)
        self.assertEqual(status, parser.STATUS_SUCCESS)
        # 清洗后为 None 的条目照样保留（§9.2 裁决 2）
        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0]["ref_link"])
        self.assertIsNone(items[1]["ref_link"])

    def test_parse_keeps_valid_ref_link(self):
        raw = self.RAW.replace(
            "【参考链接】无", "【参考链接】https://arxiv.org/abs/2609.29808v1"
        )
        _, items = parser.parse(raw, 5, SITES)
        self.assertEqual(items[1]["ref_link"], "https://arxiv.org/abs/2609.29808v1")

    def test_parse_sites_defaults_to_empty(self):
        """向后兼容：不传 sites 时签名与行为与 Spec1 一致。"""
        status, items = parser.parse(self.RAW, 5)
        self.assertEqual(status, parser.STATUS_SUCCESS)
        self.assertEqual(len(items), 2)

    def test_max_items_still_applies(self):
        _, items = parser.parse(self.RAW, 1, SITES)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tech_name"], "GLM-5.3")


class EmptyReplyTest(unittest.TestCase):
    """「这日返回了无」的判定（Spec1 §5.3 步骤 1）。

    两个方向都必须守住：

    - **正向**（Spec2 §10 #10）：新 prompt 加了「仅能为今天日期发布的…」等约束，
      模型更容易一无所获。它未必照 prompt 说的只回一个「无」字，而可能回一整句
      「今日无符合条件的技术或模型。」—— 语义相同，**不得**因此落 parse_failed。
    - **反向**（Spec1 #18）：乱码、模板残片、道歉语必须落 parse_failed。empty 会被
      前端渲染成「这日无前沿 AI 技术」，把「模型没答好」说成「今天确实没有」，
      等于替模型圆谎，且掩盖了本该由管理员介入的解析异常。
    """

    ABSENT = (
        "无",
        "无。",
        "没有",
        "暂无",
        "none",
        "今日无符合条件的技术或模型。",
        "今天（2026年9月29日）没有新的 AI 前沿技术发布。",
        "今日暂无符合条件的技术。",
        "本日无。",
        "经检索，9月29日没有创新或性能提升明显的技术。",
        "暂时没有符合条件的技术",
        "本期未发现符合条件的技术，检索 HuggingFace 与 arXiv 的当日更新均为学术方法。",
        # Spec3 §8.4 —— 修「无」被误判成解析异常。模型一无所获时常先解释再道结论，
        # 旧判据把「抱歉」当否决词、词表又漏了「未找到 / 未能找到 / 无法找到」，
        # 整类写法落到 parse_failed；而 parse_failed 永不重采（§8.3），于是一直卡住。
        "很抱歉，经过联网检索，2026年9月29日未检索到符合条件的AI前沿技术或模型。",
        "抱歉，我无法找到今天发布的新AI技术。",
        "很抱歉，今日（2026年9月29日）未发现符合条件的前沿AI技术或模型发布。",
        "未找到符合条件的AI前沿技术。",
        "未能找到今日符合条件的AI技术。",
        "没有找到符合条件的 AI 前沿技术。",
        "经检索，未搜索到今日发布的 AI 前沿技术。",
        "很抱歉，经过联网检索，9月29日未检索到符合条件的技术。",
        # §8.7 NOISE_RE：原集合漏了「」，这类回复在 PROSE_RE 一步就被挡掉
        "经检索，未发现符合「有创新或性能明显提升」这一标准的技术。",
    )

    # 反向用例里每一条都「差点」被误判成 empty，逐条说明它守的是什么
    NOT_ABSENT = (
        ("", "空回复走 parse_failed，由调用层判 failed"),
        ("   ", "纯空白同上"),
        ("▲▲▲ 乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码", "乱码（Spec1 #18）"),
        ("抱歉，我无法完成这个请求。", "道歉语：说的是「做不到」，不是「今天没有」"),
        ("系统错误：无法连接上游服务", "错误语：含「无」但语义相反"),
        ("failed to fetch results", "英文失败语"),
        ("【技术内容】输入条件，输出结果", "模板残片：有字段标记却没有【技术名】"),
        ("无【技术名】", "含【技术名】标记 → 交给正常解析分支，不能在这里短路"),
        # Spec3 §8.4 新增的真·故障：都**没有**长成「否定词紧贴结果动词」的结构，
        # 所以拿不到强信号那条豁免通道，仍由否决词拦下
        ("无法访问该网站", "系统层面做不到，不是「检索完了发现没有」"),
        ("检索过程中出现错误", "故障描述，含「检索」但不是否定式"),
        ("系统异常：上游服务超时", "上游故障"),
        ("no results were found but the request failed", "英文失败语"),
    )

    # 强信号 / 弱信号的分界（Spec3 §8.4）：两句都含「抱歉」，结果必须相反 ——
    # 这正是本次要固化的区别。强信号只认「否定词紧贴结果动词」。
    APOLOGY_PAIRS = (
        ("抱歉，我无法完成这个请求。", False, "泛否定 + 做不到 → 仍是否决"),
        ("很抱歉，经过联网检索，9月29日未检索到符合条件的技术。", True, "未+检索到 → 强信号"),
        ("无法找到该技术的官方页面。", True, "无法+找到 → 强信号，先于否决词判定"),
        ("无法完成今天的检索。", False, "无法 + 完成，不是结果动词 → 不走强信号"),
    )

    def test_natural_language_absence_is_empty(self):
        """§10 #10：更严的 prompt 不得把「整句说无」变成 parse_failed。"""
        for text in self.ABSENT:
            with self.subTest(text=text):
                self.assertTrue(parser.is_empty_reply(text), f"漏判成 parse_failed：{text}")

    def test_garbage_and_apology_are_not_empty(self):
        """Spec1 #18：反向误判比漏判更糟 —— 它会把解析异常伪装成「今天没有」。"""
        for text, why in self.NOT_ABSENT:
            with self.subTest(text=text):
                self.assertFalse(parser.is_empty_reply(text), f"误判成 empty：{why}")

    def test_strong_and_weak_signals_are_separated(self):
        """§8.4：强信号（否定词紧贴结果动词）不被礼貌语误伤，泛否定仍守否决词。"""
        for text, expected, why in self.APOLOGY_PAIRS:
            with self.subTest(text=text):
                self.assertEqual(parser.is_empty_reply(text), expected, why)
                self.assertEqual(
                    parser.parse(text, 5)[0],
                    parser.STATUS_EMPTY if expected else parser.STATUS_PARSE_FAILED,
                    why,
                )

    def test_apology_words_are_no_longer_vetoes(self):
        """回归：把「抱歉 / sorry」当否决词，等于把最常见的一种「无」判成解析异常。"""
        for word in ("抱歉", "sorry"):
            with self.subTest(word=word):
                self.assertNotIn(word, parser.FAILURE_WORDS)

    def test_failure_words_still_cover_real_failures(self):
        """去掉道歉语不等于放宽：能力/系统层面的否认仍须在列。"""
        for word in ("无法", "失败", "错误", "超时", "异常", "timeout", "error", "failed"):
            with self.subTest(word=word):
                self.assertIn(word, parser.FAILURE_WORDS)

    def test_noise_re_strips_chinese_book_quotes(self):
        """§8.7：漏了「」『』《》〈〉，含它们的回复在 PROSE_RE 一步就被挡掉。"""
        for ch in "「」『』《》〈〉":
            with self.subTest(ch=ch):
                self.assertEqual(parser.NOISE_RE.sub("", ch), "")
        core = parser.NOISE_RE.sub("", "经检索，未发现符合「创新」标准的技术。").lower()
        self.assertTrue(parser.PROSE_RE.match(core), f"仍被 PROSE_RE 挡掉：{core}")

    def test_status_mapping_matches_the_predicate(self):
        """判定最终要落到 status 上，这里从 parse() 出口再确认一次。"""
        for text in self.ABSENT:
            with self.subTest(text=text):
                self.assertEqual(parser.parse(text, 5)[0], parser.STATUS_EMPTY)
        for text, why in self.NOT_ABSENT:
            with self.subTest(text=text):
                self.assertEqual(
                    parser.parse(text, 5)[0],
                    parser.STATUS_PARSE_FAILED,
                    f"状态判错：{why}",
                )


if __name__ == "__main__":
    unittest.main()
