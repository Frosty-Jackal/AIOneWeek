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


class FaviconTest(unittest.TestCase):
    """Spec3 §7 —— 把横版字标等比装进 64×64 方形透明画布。

    直接引用非正方形的 static/logo.png 当图标，各家浏览器处理不一（有的拉伸、
    有的留白），所以必须先做成正方形再引用。
    """

    SIZE = 64
    PADDING = 4

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aioneek-favicon-")) / "favicon.png"
        self.logo = ROOT / "static" / "logo.png"
        self.src_hash = _sha256(self.logo)
        self.stats = make_logo.build_favicon(self.logo, self.tmp, self.SIZE, self.PADDING)

    def test_canvas_is_square(self):
        img = make_logo.load_png(self.tmp)
        self.assertEqual((img.width, img.height), (self.SIZE, self.SIZE))
        self.assertEqual(self.stats["size"], self.SIZE)

    def test_content_is_scaled_proportionally(self):
        """等比：字标不得被压扁（§7.3）。

        宽高都得是整数像素，比值必然带一点取整误差 —— 断言「与理想值相差不超过
        1px」而不是「比值精确相等」，后者把取整误判成拉伸。
        """
        src = make_logo.load_png(self.logo)
        x0, y0, x1, y1 = src.content_bbox(make_logo.CONTENT_THRESHOLD)
        out_w, out_h = self.stats["content"]
        ideal_h = (y1 - y0) * out_w / (x1 - x0)
        self.assertLessEqual(abs(out_h - ideal_h), 1, f"{out_w}×{out_h} 相对理想高 {ideal_h:.2f} 偏离超过 1px")

    def test_content_fits_inside_the_padding(self):
        """等比缩放到 padding 内，两侧留透明边，不得贴边也不得被截断。"""
        img = make_logo.load_png(self.tmp)
        box = img.content_bbox()
        self.assertIsNotNone(box, "整幅透明 —— 内容没画上去")
        cx0, cy0, cx1, cy1 = box
        self.assertGreaterEqual(cx0, self.PADDING)
        self.assertGreaterEqual(cy0, self.PADDING)
        self.assertLessEqual(cx1, self.SIZE - self.PADDING)
        self.assertLessEqual(cy1, self.SIZE - self.PADDING)

    def test_content_is_centred(self):
        """左右（或上下）留白之差最多 1px —— 字标是横版，水平方向居中。"""
        img = make_logo.load_png(self.tmp)
        x0, y0, x1, y1 = img.content_bbox()
        self.assertLessEqual(abs(x0 - (self.SIZE - x1)), 1, "水平未居中")
        self.assertLessEqual(abs(y0 - (self.SIZE - y1)), 1, "垂直未居中")

    def test_has_alpha_channel(self):
        """§7.7：带 alpha 通道 —— 否则浏览器按不透明方块渲染，四角是白块。"""
        img = make_logo.load_png(self.tmp)
        self.assertEqual(img.width * img.height, len(img.pixels) // 4)
        corners = (0, self.SIZE - 1, (self.SIZE - 1) * self.SIZE, self.SIZE * self.SIZE - 1)
        for offset in corners:
            with self.subTest(corner=offset):
                self.assertEqual(img.pixels[offset * 4 + 3], 0, "四角应全透明")

    def test_fully_transparent_areas_have_clean_rgb(self):
        img = make_logo.load_png(self.tmp)
        dirty = sum(
            1
            for i in range(0, len(img.pixels), 4)
            if img.pixels[i + 3] == 0 and (img.pixels[i] or img.pixels[i + 1] or img.pixels[i + 2])
        )
        self.assertEqual(dirty, 0)

    def test_under_twenty_kilobytes(self):
        """§7.7：为标签页图标拉几十 KB 没有道理。"""
        self.assertLess(self.tmp.stat().st_size, 20 * 1024)

    def test_blank_source_is_rejected(self):
        """整幅透明要报错，不能静默写出一张看不见的图标。"""
        blank = Path(tempfile.mkdtemp(prefix="aioneek-blank-")) / "blank.png"
        blank.write_bytes(make_logo.encode_png(8, 8, bytes(8 * 8 * make_logo.BPP)))
        with self.assertRaises(ValueError):
            make_logo.build_favicon(blank, self.tmp)

    def test_stamp_is_copied_whole(self):
        """回归：居中贴图按行切片，行宽算错会画出斜条纹、丢像素或重复像素。

        判据用「不透明像素总数与缩放结果一致」—— 与字画形状无关（字标逐行的左右
        边界本来就不齐，拿边界当判据是错的），但错位必然让计数对不上。
        """
        src = make_logo.load_png(self.logo)
        box = src.content_bbox(make_logo.CONTENT_THRESHOLD)
        out_w, out_h = self.stats["content"]
        stamp = make_logo.resize_area(src, box, out_w, out_h)
        expected = sum(1 for i in range(3, len(stamp), 4) if stamp[i])

        got = make_logo.load_png(self.tmp).pixels
        actual = sum(1 for i in range(3, len(got), 4) if got[i])
        self.assertEqual(actual, expected, "贴图后不透明像素数变了 —— 行切片错位")

    def test_source_logo_is_untouched(self):
        self.assertEqual(_sha256(self.logo), self.src_hash)


class FaviconAssetTest(unittest.TestCase):
    """§7.5 / §7.7 —— 产物已落库，两个页面都引用了它。"""

    FAVICON = ROOT / "static" / "favicon.png"
    LINK = '<link rel="icon" type="image/png" href="/static/favicon.png">'

    def test_favicon_exists_and_is_64x64(self):
        self.assertTrue(self.FAVICON.exists(), "static/favicon.png 尚未生成")
        img = make_logo.load_png(self.FAVICON)
        self.assertEqual((img.width, img.height), (64, 64))

    def test_both_pages_link_it_after_the_title(self):
        for name in ("index.html", "admin.html"):
            with self.subTest(file=name):
                html = (ROOT / "static" / name).read_text(encoding="utf-8")
                self.assertIn(self.LINK, html)
                self.assertLess(html.index("<title>"), html.index(self.LINK), "图标应在 <title> 之后")

    def test_master_files_stay_out_of_runtime(self):
        """§7.7：`git grep "logotransparent" static/` 零命中 —— 母版 1.7 MB 不进运行时。"""
        hits = [
            name
            for name in sorted(p.name for p in (ROOT / "static").iterdir())
            if name.endswith((".html", ".css", ".js"))
            and "logotransparent" in (ROOT / "static" / name).read_text(encoding="utf-8")
        ]
        self.assertEqual(hits, [])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
