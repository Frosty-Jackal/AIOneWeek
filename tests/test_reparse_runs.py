"""Spec3 §8.5 —— 存量 `parse_failed` 行的零成本重判脚本。

判据修好后，**已经写进库的 `parse_failed` 行不会自己变好**：`weekly.py` 的
`needs_collect()` 对 `parse_failed` 永远返回 False（Spec1 §6.2 的有意设计），
于是那次误判被永久固化，用户每次点按钮都看到「管理员可修正」。

但它们不必重采 —— `daily_run.raw_response` 存着当时的完整响应 JSON，
用新判据重解析一遍即可，零 API 调用。

这里只喂构造好的 raw_response，不打桩网络：一旦脚本真去调模型，测试会因为
没有 API key 而炸，正好当成「不许联网」的护栏（契约 8）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import parser
from app.db import Base, now_iso
from app.models import DailyRun, DailyTech, SourceSite
from scripts.reparse_runs import reparse

SITE = "https://huggingface.co/papers/trending"

# 旧判据把它判成了 parse_failed；新判据（§8.4 强信号）应改判 empty
APOLOGY_REPLY = "很抱歉，经过联网检索，2026年9月29日未检索到符合条件的AI前沿技术或模型。"

# 一条真能解析出的技术（旧判据也判得对，脚本必须**不动**它）
GOOD_REPLY = """【技术名】GLM-5.3
【技术内容】输入文本，输出更长的上下文理解
【技术创新】上下文窗口翻倍
【应用场景】长文档问答、代码库理解、多轮客服
【发布时间】2026年9月29日
【参考链接】https://huggingface.co/zai-org/GLM-5.3
"""

# 仍然不可解析：脚本必须原样留着，交管理员
STILL_BROKEN_REPLY = "今天有一些新技术发布，详情请见官网。"


def envelope(text: str, searches: int = 3, cost: float = 0.024) -> str:
    """按 Anthropic 兼容端点的响应形状包一封原始返回。

    带 server_tool_use + web_search_tool_result —— `_extract(require_search=False)`
    虽然不查这个，但真实库里存的就是带联网痕迹的响应，照抄更接近实况。
    """
    return json.dumps(
        {
            "content": [
                {"type": "server_tool_use", "name": "web_search", "id": "s1"},
                {"type": "web_search_tool_result", "tool_use_id": "s1"},
                {"type": "text", "text": text},
            ],
            "usage": {"server_tool_use": {"web_search_requests": searches}},
            "_cost_cny": cost,
        },
        ensure_ascii=False,
    )


class ReparseTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aioneek-reparse-")) / "t.db"
        engine = create_engine(f"sqlite:///{tmp}", future=True)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        self.db.add(SourceSite(url=SITE, enabled=1, created_at=now_iso()))
        self.db.commit()
        self.sites = [SITE]
        self.logs: list[str] = []

    def tearDown(self):
        self.db.close()

    def _run(self, day: str, raw: str, status: str = parser.STATUS_PARSE_FAILED,
             item_count: int = 0, cost: float = 0.024) -> DailyRun:
        run = DailyRun(
            date=day,
            status=status,
            prompt="p",
            raw_response=raw,
            item_count=item_count,
            cost_cny=cost,
            created_at="2026-09-29 08:50:00",
            updated_at="2026-09-29 08:50:00",
        )
        self.db.add(run)
        self.db.commit()
        return run

    def _items(self, day: str) -> list[DailyTech]:
        return list(
            self.db.scalars(
                select(DailyTech).where(DailyTech.date == day).order_by(DailyTech.seq)
            ).all()
        )

    def _reparse(self, dry_run: bool = False) -> dict:
        stats = reparse(self.db, self.sites, dry_run=dry_run, log=self.logs.append)
        if not dry_run:
            self.db.expire_all()
        return stats

    # --- 改判 ---

    def test_apology_reply_becomes_empty(self):
        """本次要修的正是这一类：旧判据被「抱歉」一票否决，白白落成解析异常。"""
        run = self._run("2026-09-29", envelope(APOLOGY_REPLY))
        before = run.updated_at

        stats = self._reparse()

        run = self.db.get(DailyRun, run.id)
        self.assertEqual(run.status, parser.STATUS_EMPTY)
        self.assertEqual(run.item_count, 0)
        self.assertEqual(stats["rescanned"], 1)
        self.assertEqual(stats["empty"], 1)
        self.assertNotEqual(run.updated_at, before, "updated_at 应置为执行时刻")

    def test_parseable_reply_becomes_success_and_writes_items(self):
        run = self._run("2026-09-28", envelope(GOOD_REPLY))

        stats = self._reparse()

        run = self.db.get(DailyRun, run.id)
        self.assertEqual(run.status, parser.STATUS_SUCCESS)
        self.assertEqual(run.item_count, 1)
        self.assertEqual(stats["success"], 1)

        items = self._items("2026-09-28")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].seq, 0, "seq 必须从 0 起连续")
        self.assertEqual(items[0].tech_name, "GLM-5.3")
        self.assertEqual(json.loads(items[0].scenarios), ["长文档问答", "代码库理解", "多轮客服"])

    def test_still_broken_row_is_left_alone(self):
        run = self._run("2026-09-27", envelope(STILL_BROKEN_REPLY))
        before = run.updated_at

        stats = self._reparse()

        run = self.db.get(DailyRun, run.id)
        self.assertEqual(run.status, parser.STATUS_PARSE_FAILED)
        self.assertEqual(run.updated_at, before, "仍不可解析的行不该被碰")
        self.assertEqual(stats["rescanned"], 0)

    def test_non_json_raw_response_is_skipped_and_counted(self):
        """failed 行的 raw_response 是 `[调用失败] …` 加原始返回，不是 JSON。"""
        run = self._run(
            "2026-09-26", "[调用失败] 上游超时\n\n--- 原始返回 ---\n<html>503</html>",
            status=parser.STATUS_FAILED,
        )
        # 先把它改成 parse_failed，模拟「状态列被写错但正文不是 JSON」的脏行
        run.status = parser.STATUS_PARSE_FAILED
        self.db.commit()

        stats = self._reparse()

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["rescanned"], 0)
        self.assertEqual(self.db.get(DailyRun, run.id).status, parser.STATUS_PARSE_FAILED)

    # --- 契约 1：只碰 parse_failed ---

    def test_terminal_and_failed_rows_are_never_touched(self):
        """success / empty / failed 一律不动 —— 免得把已计费的正确结果重判坏。

        注意这三行的 raw_response 喂的是**会被改判成 empty** 的那句话：若脚本
        图省事扫了全表，它们当场就会被改掉，测试因此真的有鉴别力。
        """
        cases = (
            (parser.STATUS_SUCCESS, "2026-09-07", 0),
            (parser.STATUS_EMPTY, "2026-09-05", 0),
            (parser.STATUS_FAILED, "2026-09-06", 0),
        )
        for status, day, count in cases:
            self._run(day, envelope(APOLOGY_REPLY), status=status, item_count=count)
        before = {
            day: (r.status, r.item_count, r.updated_at)
            for day, r in ((day, self.db.get(DailyRun, self._by_date(day).id)) for _, day, _ in cases)
        }

        stats = self._reparse()

        self.assertEqual(stats["scanned"], 0, "只该扫 parse_failed 行")
        self.assertEqual(stats["rescanned"], 0)
        for _, day, _ in cases:
            run = self._by_date(day)
            self.assertEqual((run.status, run.item_count, run.updated_at), before[day])

    def _by_date(self, day: str) -> DailyRun:
        return self.db.scalars(select(DailyRun).where(DailyRun.date == day)).one()

    # --- 契约 2：改判 empty 时清掉旧残条 ---

    def test_becoming_empty_deletes_stale_items(self):
        """旧行被误判成 parse_failed 时可能仍留着半截条目，改判 empty 必须清掉。"""
        self._run("2026-09-25", envelope(APOLOGY_REPLY))
        self.db.add(
            DailyTech(
                date="2026-09-25",
                seq=0,
                tech_name="残条",
                tech_content="c",
                innovation="i",
                scenarios="[]",
            )
        )
        self.db.commit()

        self._reparse()

        self.assertEqual(self._items("2026-09-25"), [], "改判 empty 后不得残留旧条目")

    def test_success_rewrites_items_without_duplicating_seq(self):
        """重判 success 走的是与采集同一条写入路径：先清旧，seq 不重复。"""
        self._run("2026-09-24", envelope(GOOD_REPLY))
        self.db.add_all(
            [
                DailyTech(date="2026-09-24", seq=i, tech_name=f"旧{i}", tech_content="c",
                          innovation="i", scenarios="[]")
                for i in (0, 1)
            ]
        )
        self.db.commit()

        self._reparse()

        items = self._items("2026-09-24")
        self.assertEqual([i.seq for i in items], [0])
        self.assertEqual(items[0].tech_name, "GLM-5.3")

    # --- 契约 7：不改 cost_cny / created_at ---

    def test_cost_and_created_at_are_preserved(self):
        """没有产生新调用，就不该动费用；created_at 记的是当初那次采集。"""
        run = self._run("2026-09-23", envelope(APOLOGY_REPLY, cost=0.048), cost=0.048)
        created = run.created_at

        self._reparse()

        run = self.db.get(DailyRun, run.id)
        self.assertEqual(run.cost_cny, 0.048)
        self.assertEqual(run.created_at, created)

    # --- 契约 4 / 6 / 5：dry-run、幂等、统计 ---

    def test_dry_run_reports_but_writes_nothing(self):
        run = self._run("2026-09-29", envelope(APOLOGY_REPLY))

        stats = self._reparse(dry_run=True)

        self.assertEqual(stats["rescanned"], 1, "dry-run 也要如实报告会改几行")
        self.assertEqual(self.db.get(DailyRun, run.id).status, parser.STATUS_PARSE_FAILED)
        self.assertEqual(run.updated_at, "2026-09-29 08:50:00")

    def test_dry_run_and_real_run_report_the_same_counts(self):
        self._run("2026-09-29", envelope(APOLOGY_REPLY))
        self._run("2026-09-28", envelope(GOOD_REPLY))

        dry = self._reparse(dry_run=True)
        real = self._reparse()

        self.assertEqual(
            {k: dry[k] for k in ("scanned", "rescanned", "empty", "success", "skipped")},
            {k: real[k] for k in ("scanned", "rescanned", "empty", "success", "skipped")},
        )

    def test_second_run_changes_nothing(self):
        """幂等：重判过的行不再是 parse_failed，第二次自然扫不动。"""
        self._run("2026-09-29", envelope(APOLOGY_REPLY))
        self._run("2026-09-28", envelope(GOOD_REPLY))

        first = self._reparse()
        second = self._reparse()

        self.assertEqual(first["rescanned"], 2)
        self.assertEqual(second["rescanned"], 0)
        self.assertEqual(second["scanned"], 0, "重判过的行不再是 parse_failed，第二次扫不到")

    def test_summary_counts_add_up(self):
        self._run("2026-09-29", envelope(APOLOGY_REPLY))
        self._run("2026-09-28", envelope(GOOD_REPLY))
        self._run("2026-09-27", envelope(STILL_BROKEN_REPLY))
        self._run("2026-09-26", "[调用失败] 上游超时")

        stats = self._reparse()

        self.assertEqual(stats["scanned"], 4)
        self.assertEqual(stats["rescanned"], 2)
        self.assertEqual(stats["empty"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["skipped"], 1)

    def test_each_change_is_printed_with_old_and_new(self):
        self._run("2026-09-29", envelope(APOLOGY_REPLY))
        self._reparse()
        joined = "\n".join(self.logs)
        self.assertIn("2026-09-29", joined)
        self.assertIn(parser.STATUS_PARSE_FAILED, joined)
        self.assertIn(parser.STATUS_EMPTY, joined)

    def test_parse_failed_count_only_goes_down(self):
        """§8.7 验收：跑完后 parse_failed 行数「只降不升」。"""
        self._run("2026-09-29", envelope(APOLOGY_REPLY))
        self._run("2026-09-27", envelope(STILL_BROKEN_REPLY))
        before = self._count_parse_failed()

        self._reparse()

        after = self._count_parse_failed()
        self.assertLessEqual(after, before)
        self.assertEqual((before, after), (2, 1))

    def _count_parse_failed(self) -> int:
        return len(
            self.db.scalars(
                select(DailyRun.id).where(DailyRun.status == parser.STATUS_PARSE_FAILED)
            ).all()
        )


if __name__ == "__main__":
    unittest.main()
