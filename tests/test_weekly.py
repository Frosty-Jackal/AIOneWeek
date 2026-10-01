"""Spec3 §3 —— `/api/weekly` 的窗口语义（HTTP 层）。

窗口改成「不含今天的前 7 天」后，最容易被改坏的正是这一层：日期数组、
`range.from/to`、以及「今天绝不进缺口判定、因而绝不产生 daily_run 行」。

模型调用被替换成固定返回「无」的假实现，整条「缺口判定 → 串行补采 →
落库 → 组装响应」链路照常走真实代码。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import collector
from app.db import Base, get_db, now_iso
from app.main import app
from app.models import DailyRun, SourceSite, User
from app.routers import get_current_user

SEED_SITE = "https://huggingface.co/papers/trending"


class WeeklyWindowTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aioneek-weekly-")) / "t.db"
        engine = create_engine(f"sqlite:///{tmp}", future=True)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(
            email="u@example.com",
            password_enc="x",
            role="user",
            call_count=0,
            created_at=now_iso(),
        )
        self.db.add_all(
            [SourceSite(url=SEED_SITE, enabled=1, created_at=now_iso()), self.user]
        )
        self.db.commit()

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        # 不用 `with TestClient(app)`：那会跑 lifespan 的 init_db()，把播种打到真实库上
        self.client = TestClient(app)
        self.model_calls: list[str] = []

        def fake_call(prompt, use_search=True):  # noqa: ARG001
            self.model_calls.append(prompt)
            return collector.deepseek.CallResult(text="无", raw="无", cost_cny=0.01)

        self._patcher = mock.patch.object(
            collector.deepseek, "call_deepseek", side_effect=fake_call
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        app.dependency_overrides.clear()
        self.db.close()

    def _weekly(self) -> dict:
        response = self.client.get("/api/weekly")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _run_dates(self) -> set[str]:
        return set(self.db.scalars(select(DailyRun.date)).all())

    # --- 窗口本身 ---

    def test_range_is_yesterday_back_seven_days(self):
        data = self._weekly()
        today = date_cls.today()
        self.assertEqual(
            data["range"],
            {
                "from": (today - timedelta(days=7)).isoformat(),
                "to": (today - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(len(data["days"]), 7)
        self.assertEqual(data["days"][0]["date"], (today - timedelta(days=1)).isoformat())
        self.assertEqual(data["days"][-1]["date"], (today - timedelta(days=7)).isoformat())

    def test_today_never_enters_the_window_or_the_gap_check(self):
        """今天不在 days 里，也就不可能被用户点击触发补采。"""
        before = self._run_dates()
        data = self._weekly()
        today = date_cls.today().isoformat()

        self.assertNotIn(today, [d["date"] for d in data["days"]])
        self.assertNotIn(today, data["collected_now"])
        self.assertNotIn(today, self._run_dates() - before, "今天不得产生新的 daily_run 行")
        self.assertNotIn(today, self._run_dates())

    # --- 缺口补采仍按窗口走 ---

    def test_yesterday_gap_is_filled_and_shown_first(self):
        data = self._weekly()
        yesterday = (date_cls.today() - timedelta(days=1)).isoformat()

        self.assertIn(yesterday, data["collected_now"], "昨天的缺口应被补采")
        self.assertEqual(len(data["collected_now"]), 7, "空库冷启动应补齐 7 天")
        self.assertEqual(len(self.model_calls), 7, "严格串行：一天一次调用")

        first = data["days"][0]
        self.assertEqual(first["date"], yesterday)
        self.assertEqual(first["status"], "empty", "模型说「无」→ empty 是终态")

    def test_no_model_call_after_the_week_turns_terminal(self):
        self._weekly()
        calls_after_first = len(self.model_calls)
        data = self._weekly()
        self.assertEqual(calls_after_first, 7)
        self.assertEqual(len(self.model_calls), calls_after_first, "命中库后不得再调 API")
        self.assertEqual(data["collected_now"], [])


if __name__ == "__main__":
    unittest.main()
