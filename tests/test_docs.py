"""文档与产品行为的一致性（Spec2 §6.1）。

Spec2 §6.1 点名一处自相矛盾：PRD §6 写着「本产品无人工客服」，而 Spec2 又在
登录界面加了客服邮箱 —— 文档说没有入口，产品上就摆着一个。这类矛盾靠人眼
复查不可靠，写成断言。

这里只断言**跨文件的一致性**，不锁散文措辞：客服地址改了就两边一起改，
改了产品没改文档就红。
"""

from __future__ import annotations

import re
import unittest
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

from app.collector import week_dates

ROOT = Path(__file__).resolve().parent.parent
PRD = (ROOT / "Docs" / "PRD.md").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")
REQS = (ROOT / "requirements.txt").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "一键运行.cmd").read_text(encoding="utf-8")
SCHEDULER = ROOT / "app" / "scheduler.py"

MAILTO_RE = re.compile(r'href="mailto:([^"?]+)"')


def support_emails(html: str) -> set[str]:
    return set(MAILTO_RE.findall(html))


class SupportChannelTest(unittest.TestCase):
    def test_prd_does_not_deny_a_support_channel(self):
        """PRD 不得再声称「无人工客服」—— 登录界面已经挂了客服邮箱。"""
        # 不用 assertNotIn：它会把整篇 PRD 打进失败输出
        self.assertFalse(
            "无人工客服" in PRD,
            "PRD 与产品行为打脸：界面有客服邮箱，文档说没有人工客服入口",
        )

    def test_prd_still_scopes_the_channel(self):
        """删掉那句不等于取消边界：仍须写明不承诺响应时限，避免用户当工单系统用。"""
        for phrase in ("不提供在线人工客服", "不承诺响应时限"):
            # 同上去掉 assertIn：失败时它会把整篇 PRD 打出来，淹掉真正的信息
            with self.subTest(phrase=phrase):
                self.assertFalse(phrase not in PRD, f"PRD 缺少边界说明：{phrase}")

    def test_support_address_is_consistent_across_artifacts(self):
        """PRD 里写的客服邮箱必须就是界面 mailto 的那个地址，反之亦然。"""
        shown = support_emails(INDEX) | support_emails(ADMIN)
        self.assertEqual(len(shown), 1, f"两个页面的客服邮箱不一致：{shown}")
        address = next(iter(shown))
        self.assertIn(address, PRD, f"PRD 未提及界面上的客服邮箱 {address}")
        self.assertIn(address, ADMIN)

    def test_support_email_sits_in_the_shared_dialog_area(self):
        """三个视图（登录 / 验证码登录 / 注册）之外的公共区域才有常驻效果。"""
        for name, html in (("index.html", INDEX), ("admin.html", ADMIN)):
            with self.subTest(file=name):
                dialog = html[html.index('<dialog id="auth-dialog"') :]
                self.assertLess(
                    dialog.index('id="auth-msg"'),
                    dialog.index('class="dialog-foot"'),
                    "客服邮箱必须在 #auth-msg 之后",
                )


class WeeklyWindowConsistencyTest(unittest.TestCase):
    """Spec3 §3.5 A 组 —— PRD 的窗口定义必须与 `week_dates()` 是同一件事。

    「谁先改谁红」：改了代码没改文档会红，改了文档没改代码也会红。
    """

    def test_prd_drops_the_old_window_definition(self):
        self.assertFalse(
            "当天 + 前 6 天" in PRD,
            "PRD 仍写着旧窗口定义（Spec3 §3.5 A 组）",
        )

    def test_prd_says_the_window_excludes_today(self):
        self.assertFalse(
            "不含今天" not in PRD,
            "PRD 未写明展示窗口不含今天",
        )

    def test_prd_window_matches_week_dates(self):
        today = date_cls.today()
        days = week_dates(today.isoformat())
        self.assertEqual(len(days), 7, "窗口长度变了，PRD 与 §3 都会对不上")
        self.assertNotIn(today.isoformat(), days, "PRD 说不含今天，week_dates 却含有今天")
        self.assertEqual(days[0], (today - timedelta(days=1)).isoformat())


class ScheduledCollectionRemovalTest(unittest.TestCase):
    """Spec3 §3.4 / §3.5 B 组 —— 定时采集已删除，文档与依赖都不得再提。"""

    def test_prd_drops_the_scheduled_entry(self):
        for stale in ("8:50", "定时任务"):
            with self.subTest(stale=stale):
                self.assertFalse(stale in PRD, f"PRD 仍写着已删除的定时采集：{stale}")

    def test_prd_describes_the_on_demand_entry(self):
        self.assertFalse(
            "当场串行补采" not in PRD,
            "PRD 未写明新的按需补采入口（Spec3 §3.5 B 组）",
        )

    def test_scheduler_module_is_gone(self):
        self.assertFalse(SCHEDULER.exists(), "app/scheduler.py 应已删除（Spec3 §3.4.1）")

    def test_no_module_mentions_apscheduler(self):
        hits = [
            str(p.relative_to(ROOT))
            for p in (ROOT / "app").rglob("*.py")
            if "apscheduler" in p.read_text(encoding="utf-8").lower()
        ]
        self.assertEqual(hits, [], "app/ 下仍有文件提到 apscheduler")

    def test_requirements_drop_apscheduler(self):
        self.assertFalse(
            "apscheduler" in REQS.lower(), "apscheduler 应退出依赖（Spec3 §3.4.1）"
        )

    def test_launcher_selfcheck_drops_apscheduler(self):
        """§3.4.1 点名易漏：漏了这处，装完依赖仍会报 Dependencies still missing。"""
        self.assertFalse(
            "apscheduler" in LAUNCHER.lower(),
            "一键运行.cmd 的依赖自检仍要求 apscheduler",
        )


if __name__ == "__main__":
    unittest.main()
