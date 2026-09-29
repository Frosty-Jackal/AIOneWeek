"""Spec2 §9.3 第 4 层 —— 历史数据清洗脚本的契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DailyTech, SourceSite
from scripts.clean_ref_links import clean

ENABLED_SITE = "https://huggingface.co/papers/trending"
DISABLED_SITE = "https://old.example.com/list"

ROWS = (
    # (seq, 原值, 期望清洗结果)
    (0, f"{ENABLED_SITE} （2026-09-27 在榜）；https://www.02ship.com/news/2026-09-27", None),
    (1, "https://arxiv.org/abs/2609.28256 ；项目页 https://declare-lab.github.io/MemBodied/", "https://arxiv.org/abs/2609.28256"),
    (2, DISABLED_SITE, None),  # 已停用站点也必须参与判定（契约 1）
    (3, "https://old.example.com?date=2026-09-01", None),  # 停用站点的祖先路径
    (4, None, None),
    (5, "https://huggingface.co/convaiinnovations/laya", "https://huggingface.co/convaiinnovations/laya"),
)

EXPECTED = {"scanned": 6, "changed": 4, "nulled": 3}


class CleanTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aioneek-clean-")) / "t.db"
        engine = create_engine(f"sqlite:///{tmp}", future=True)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        self.db.add_all(
            [
                SourceSite(url=ENABLED_SITE, enabled=1, created_at="2026-09-01 00:00:00"),
                SourceSite(url=DISABLED_SITE, enabled=0, created_at="2026-09-01 00:00:00"),
            ]
        )
        for seq, raw, _ in ROWS:
            self.db.add(
                DailyTech(
                    date="2026-09-27",
                    seq=seq,
                    tech_name=f"技术{seq}",
                    tech_content="内容",
                    innovation="创新",
                    scenarios='["a", "b", "c"]',
                    publish_date=None,
                    ref_link=raw,
                )
            )
        self.db.commit()
        self.lines: list[str] = []

    def tearDown(self):
        self.db.close()

    def _stored(self) -> list[str | None]:
        return list(
            self.db.scalars(
                select(DailyTech.ref_link).order_by(DailyTech.seq)
            ).all()
        )

    def _log(self, line: str) -> None:
        self.lines.append(line)

    def test_dry_run_reports_but_writes_nothing(self):
        before = self._stored()
        stats = clean(self.db, [ENABLED_SITE, DISABLED_SITE], dry_run=True, log=self._log)
        self.assertEqual(stats, EXPECTED)
        self.assertEqual(self._stored(), before, "dry-run 不得写库")
        self.assertIn("扫描 6 行，清洗 4 行，其中置空 3 行", self.lines)

    def test_dry_run_and_real_run_report_the_same_counts(self):
        stats_dry = clean(self.db, [ENABLED_SITE, DISABLED_SITE], dry_run=True, log=self._log)
        stats_real = clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        self.assertEqual(stats_dry, stats_real)

    def test_real_run_applies_expected_values(self):
        stats = clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        self.assertEqual(stats, EXPECTED)
        self.assertEqual(self._stored(), [expect for _, _, expect in ROWS])

    def test_second_run_changes_nothing(self):
        clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        stats = clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        self.assertEqual(stats, {"scanned": 6, "changed": 0, "nulled": 0})

    def test_rows_are_never_deleted(self):
        clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        count = len(self.db.scalars(select(DailyTech.id)).all())
        self.assertEqual(count, len(ROWS))

    def test_each_change_is_printed_with_old_and_new(self):
        """契约 3：每行变更都要能看到旧值与新值（置空时新值显式为 NULL）。"""
        clean(self.db, [ENABLED_SITE, DISABLED_SITE], log=self._log)
        joined = "\n".join(self.lines)
        self.assertEqual(joined.count("旧："), 4)
        self.assertEqual(joined.count("新："), 4)
        self.assertEqual(joined.count("新：NULL"), 3)
        self.assertIn("新：https://arxiv.org/abs/2609.28256", joined)
        # 未变更的行不打印
        self.assertNotIn("convaiinnovations/laya", joined)


if __name__ == "__main__":
    unittest.main()
