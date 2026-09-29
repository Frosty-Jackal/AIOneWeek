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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRD = (ROOT / "Docs" / "PRD.md").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
