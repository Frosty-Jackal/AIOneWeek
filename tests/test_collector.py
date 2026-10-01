"""Spec2 §2 / §9.3 第 1 层 —— prompt 追加与来源站接线。

不调网络：`deepseek.call_deepseek` 被替换成返回固定正文的假实现，
整条「prompt 拼装 → 解析 → 落库」链路照常走真实代码。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import collector, parser
from app.db import Base, now_iso
from app.models import DailyRun, DailyTech, SourceSite

# Spec2 §2.1 —— 用户原文，逐字追加，不得改写
USER_SENTENCE = (
    "仅能为今天日期发布的，若不是，请不要返回给我！"
    "而且只要技术/模型，不要学术方法，参考链接格式需规范url"
)
# Spec2 §9.3 第 1 层 —— 追加在用户原句之后的格式规约
FORMAT_HEAD = "其中【参考链接】必须满足："
FORMAT_TAIL = "4. 找不到该技术的具体页面时，【参考链接】直接写：无"

SEED_SITE = "https://huggingface.co/papers/trending"


class PromptTest(unittest.TestCase):
    """`build_prompt` 的文本与签名（§2.1 / §9.3 第 1 层）。"""

    def setUp(self):
        self.db = _make_session()

    def tearDown(self):
        self.db.close()

    def test_user_sentence_appended_verbatim(self):
        prompt = collector.build_prompt(self.db, "2026-09-29", [SEED_SITE])
        self.assertIn(USER_SENTENCE, prompt)

    def test_format_rules_appended_after_user_sentence(self):
        """R1：§9.3 要求格式规约「在其后再补一段」，故 prompt 以规约结尾。"""
        prompt = collector.build_prompt(self.db, "2026-09-29", [SEED_SITE])
        self.assertIn(FORMAT_HEAD, prompt)
        self.assertTrue(prompt.rstrip().endswith("【参考链接】直接写：无"))
        self.assertLess(prompt.index(USER_SENTENCE), prompt.index(FORMAT_HEAD))
        self.assertIn(FORMAT_TAIL, prompt)

    def test_sites_come_from_argument_not_db(self):
        """`build_prompt` 接受 sites，不再自己查库（§9.3 的「只查一次」前提）。"""
        prompt = collector.build_prompt(self.db, "2026-09-29", ["https://example.com/a"])
        self.assertIn("https://example.com/a", prompt)
        self.assertNotIn(SEED_SITE, prompt)

    def test_date_and_max_items_still_rendered(self):
        prompt = collector.build_prompt(self.db, "2026-09-29", [])
        self.assertIn("2026年9月29日", prompt)
        self.assertIn("最多不超过 5 个", prompt)

    def test_empty_sites_falls_back_to_placeholder(self):
        prompt = collector.build_prompt(self.db, "2026-09-29", [])
        self.assertIn("（未配置参考网站，请凭已有知识回答）", prompt)


class WeekDatesTest(unittest.TestCase):
    """Spec3 §3 —— 展示窗口是「不含今天的前 7 天」。

    窗口右端是**昨天**而非今天：今天的采集结果只可能在今天部分完成，
    把它摆进展示窗口等于展示一份残缺快照。
    """

    def test_window_is_the_seven_days_before_today(self):
        self.assertEqual(
            collector.week_dates("2026-09-30"),
            [
                "2026-09-29",
                "2026-09-28",
                "2026-09-27",
                "2026-09-26",
                "2026-09-25",
                "2026-09-24",
                "2026-09-23",
            ],
        )

    def test_today_is_excluded_and_order_is_descending(self):
        days = collector.week_dates("2026-09-30")
        self.assertEqual(len(days), 7)
        self.assertNotIn("2026-09-30", days, "今天不得进入展示窗口")
        self.assertEqual(days, sorted(days, reverse=True), "窗口必须倒序（昨天在前）")

    def test_window_covers_a_month_boundary(self):
        """跨月不能靠字符串减法，必须走 date 运算。"""
        self.assertEqual(
            collector.week_dates("2026-10-03"),
            ["2026-10-02", "2026-10-01", "2026-09-30", "2026-09-29",
             "2026-09-28", "2026-09-27", "2026-09-26"],
        )

    def test_window_length_still_follows_the_config(self):
        """§3.2：WEEK_WINDOW_DAYS 配置项不改，取 1 时窗口 = [today-1]。"""
        with mock.patch.object(collector.settings, "week_window_days", 1):
            self.assertEqual(collector.week_dates("2026-09-30"), ["2026-09-29"])
        with mock.patch.object(collector.settings, "week_window_days", 3):
            self.assertEqual(
                collector.week_dates("2026-09-30"),
                ["2026-09-29", "2026-09-28", "2026-09-27"],
            )

    def test_defaults_to_real_today(self):
        today = date_cls.today()
        expected = [(today - timedelta(days=i)).isoformat() for i in range(1, 8)]
        self.assertEqual(collector.week_dates(), expected)


class CollectFlowTest(unittest.TestCase):
    """整条采集链路：来源站只查一次，脏链接就地清洗。"""

    def setUp(self):
        self.db = _make_session()
        self.db.add(SourceSite(url=SEED_SITE, enabled=1, created_at=now_iso()))
        self.db.commit()
        self.engine = self.db.get_bind()
        self.site_queries = 0

        def count_site_selects(conn, cursor, statement, params, context, executemany):
            if "FROM source_sites" in statement:
                self.site_queries += 1

        self._listener = count_site_selects
        event.listen(self.engine, "before_cursor_execute", self._listener)

    def tearDown(self):
        event.remove(self.engine, "before_cursor_execute", self._listener)
        self.db.close()

    def _run(self, text: str, day: str = "2026-09-29") -> DailyRun:
        result = collector.deepseek.CallResult(text=text, raw=text, cost_cny=0.01)
        with mock.patch.object(collector.deepseek, "call_deepseek", return_value=result):
            return collector.collect(day, db=self.db)

    def _items(self, day: str) -> list[DailyTech]:
        return list(
            self.db.scalars(
                select(DailyTech).where(DailyTech.date == day).order_by(DailyTech.seq)
            ).all()
        )

    def test_source_sites_queried_once(self):
        self._run(_dirty_reply())
        self.assertEqual(self.site_queries, 1, "来源站被查了不止一次")

    def test_source_site_backfill_is_cleaned_on_write(self):
        run = self._run(_dirty_reply())
        self.assertEqual(run.status, parser.STATUS_SUCCESS)
        # 条目保留（不清空），但回填来源站的链接被置空
        items = self._items(run.date)
        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0].ref_link)
        # 协议不改写：实库 2026-09-28 那行本身就是 http://
        self.assertEqual(items[1].ref_link, "http://arxiv.org/abs/2609.29808v1")

    def test_prompt_gets_sites_from_db(self):
        run = self._run(_dirty_reply())
        self.assertIn(SEED_SITE, run.prompt)
        self.assertIn(USER_SENTENCE, run.prompt)

    # --- Spec1 #10 / #18 回归：新 prompt 不得改变状态判定（Spec2 §10）---

    def test_empty_reply_still_maps_to_empty(self):
        run = self._run("无")
        self.assertEqual(run.status, parser.STATUS_EMPTY)
        self.assertEqual(run.item_count, 0)
        self.assertEqual(self._items(run.date), [])

    def test_natural_language_empty_reply_still_maps_to_empty(self):
        """§10 #10：模型整句说「无」也算 empty。

        后果落在这一层最重：parse_failed 是终态，needs_collect() 不会重试它，
        用户端只会看到「该日数据解析异常」。新 prompt 更严 → 空手而归更常见，
        这条路径必须仍然归 empty。
        """
        run = self._run("今日无符合条件的技术或模型。")
        self.assertEqual(run.status, parser.STATUS_EMPTY)
        self.assertEqual(run.item_count, 0)
        self.assertEqual(self._items(run.date), [])

    def test_garbled_reply_still_maps_to_parse_failed(self):
        run = self._run("▲▲▲ 乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码乱码")
        self.assertEqual(run.status, parser.STATUS_PARSE_FAILED)
        self.assertTrue(run.raw_response)

    def test_failed_call_still_records_status(self):
        with mock.patch.object(
            collector.deepseek,
            "call_deepseek",
            side_effect=collector.deepseek.DeepSeekError("boom", raw="RAW"),
        ):
            run = collector.collect("2026-09-29", db=self.db)
        self.assertEqual(run.status, parser.STATUS_FAILED)
        self.assertIn("boom", run.raw_response)
        self.assertIn("RAW", run.raw_response)


def _dirty_reply() -> str:
    """两条：第一条回填来源站（应被置空），第二条是合法 arXiv 链接（应保留）。"""
    return (
        "【技术名】Jev-Mem\n"
        "【技术内容】面向高效 Agent 的系统一控制记忆\n"
        "【技术创新】记忆读写开销显著下降\n"
        "【应用场景】长对话、检索、Agent 编排\n"
        "【发布时间】2026年9月29日\n"
        f"【参考链接】{SEED_SITE} （2026-09-29 在榜）\n"
        "【技术名】Hard Stop\n"
        "【技术内容】内核级抢占与隔离\n"
        "【技术创新】首次在内核层拦停失控 Agent\n"
        "【应用场景】安全审计、沙箱、云平台\n"
        "【发布时间】2026年9月28日\n"
        "【参考链接】http://arxiv.org/abs/2609.29808v1\n"
    )


def _make_session():
    """每个用例一个独立的临时库，不碰 data/aioneek.db。"""
    tmp = Path(tempfile.mkdtemp(prefix="aioneek-test-")) / "t.db"
    engine = create_engine(f"sqlite:///{tmp}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


if __name__ == "__main__":
    unittest.main()
