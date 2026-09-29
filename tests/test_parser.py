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


if __name__ == "__main__":
    unittest.main()
