"""Spec2 §5.5 —— 顶栏 logo 一次性构建动作的验证。

母版 `Docs/logotransparent.png` 必须保持不动；产物是 `static/logo.png`。
纯 stdlib 实现（zlib + struct），不引入 Pillow（§12）。
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import make_logo

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "Docs" / "logotransparent.png"

# Spec2 §5.5 实测给出的内容包围盒（含端点）：x 49..1507, y 125..870
SPEC_BBOX = (49, 125, 1508, 871)


class DecodeTest(unittest.TestCase):
    def test_source_is_rgba_1536x1024(self):
        img = make_logo.load_png(SOURCE)
        self.assertEqual((img.width, img.height), (1536, 1024))
        self.assertEqual(len(img.pixels), 1536 * 1024 * 4)

    def test_bounding_box_matches_spec_measurement(self):
        """解码器必须与 §5.5 的实测数字一致，否则裁剪会错。"""
        img = make_logo.load_png(SOURCE)
        self.assertEqual(img.content_bbox(make_logo.CONTENT_THRESHOLD), SPEC_BBOX)

    def test_threshold_is_honoured(self):
        """母版边缘有一圈 alpha=1 的极淡辉光，按 alpha>0 裁等于没裁。

        回归：content_bbox 曾经收下 threshold 却完全不用它，于是任何阈值都返回
        整幅画布，裁剪静默失效。
        """
        img = make_logo.load_png(SOURCE)
        self.assertEqual(img.content_bbox(0), (0, 7, 1536, 1024), "alpha>0 竟被裁掉，说明有像素被误判")
        self.assertNotEqual(
            img.content_bbox(make_logo.CONTENT_THRESHOLD),
            img.content_bbox(0),
            "不同阈值给出了同一结果 —— threshold 没有被使用",
        )
        # 阈值越高，包围盒只会收缩，不会反向变大
        widths = [img.content_bbox(t)[2] - img.content_bbox(t)[0] for t in range(0, 64, 8)]
        self.assertEqual(widths, sorted(widths, reverse=True), f"包围盒随阈值非单调：{widths}")

    def test_corners_are_fully_transparent(self):
        img = make_logo.load_png(SOURCE)
        corners = (
            0,
            (img.width - 1) * 4,
            (img.height - 1) * img.width * 4,
            ((img.height - 1) * img.width + img.width - 1) * 4,
        )
        for offset in corners:
            with self.subTest(offset=offset):
                self.assertEqual(img.pixels[offset + 3], 0)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aioneek-logo-")) / "logo.png"
        self.src_hash = _sha256(SOURCE)
        self.stats = make_logo.build_logo(SOURCE, self.tmp)

    def test_output_height_is_128(self):
        self.assertEqual(self.stats["height"], 128)

    def test_aspect_ratio_preserved(self):
        """裁剪后内容比例约 1.96:1 → 约 250×128（§5.5）。"""
        self.assertEqual(self.stats["width"], round(self.stats["src_width"] * 128 / self.stats["src_height"]))
        self.assertAlmostEqual(self.stats["width"] / 128, 1.956, places=2)
        self.assertEqual(self.stats["width"], 250)

    def test_no_transparent_padding_left(self):
        """裁剪 + 缩放后内容应贴边，否则顶栏里图形会显小且不居中。"""
        img = make_logo.load_png(self.tmp)
        x0, y0, x1, y1 = img.content_bbox()
        self.assertLessEqual(x0, 1)
        self.assertLessEqual(y0, 1)
        self.assertGreaterEqual(x1, img.width - 1)
        self.assertGreaterEqual(y1, img.height - 1)

    def test_fully_transparent_areas_have_clean_rgb(self):
        """alpha=0 处的非零 RGB 是垃圾值，重采样后必须清零（避免边缘发灰）。"""
        img = make_logo.load_png(self.tmp)
        dirty = 0
        for i in range(0, len(img.pixels), 4):
            if img.pixels[i + 3] == 0 and (img.pixels[i] or img.pixels[i + 1] or img.pixels[i + 2]):
                dirty += 1
        self.assertEqual(dirty, 0)

    def test_file_is_dramatically_smaller_than_source(self):
        """§5.5：母版 1.7 MB，每次页面加载拉它不合理。"""
        self.assertLess(self.tmp.stat().st_size, 64 * 1024)
        self.assertLess(self.tmp.stat().st_size, SOURCE.stat().st_size / 20)

    def test_source_master_is_untouched(self):
        self.assertEqual(_sha256(SOURCE), self.src_hash)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
