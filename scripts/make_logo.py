"""从母版生成顶栏 logo（Spec2 §5.5，一次性构建动作）。

    .venv/Scripts/python.exe -m scripts.make_logo

母版 `Docs/logotransparent.png` 是 1536×1024 RGBA，四周有大量透明留白
（垂直方向占 27%），且文件 1.7 MB —— 直接拿去当顶栏图会显得偏小、不居中，
而且每次页面加载都要拉 1.7 MB。这里按内容包围盒裁掉留白，等比缩到高 128px。

**纯 stdlib 实现**（zlib + struct），不引入 Pillow —— Spec2 §12 明确要求
不把图片处理库加进运行时依赖；这只是一次性构建动作，运行时用不到。

Docs/ 下的母版保持不动。
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

if __package__ in (None, ""):  # 支持直跑
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PNG_SIG = b"\x89PNG\r\n\x1a\n"
BPP = 4  # RGBA

# 裁剪透明边的 alpha 容差。母版有意做了一圈极淡的辉光，alpha 从 1 一路爬到
# 边缘；按 alpha>0 裁等于没裁，按 alpha>255 裁又会啃掉辉光本体。16/255 ≈ 6.3%
# 是「肉眼已不可见」的量级，也正是 Spec2 §5.5 实测 bbox(49,125,1508,871) 对应
# 的阈值 —— 两边独立量到同一个数，说明这就是当初量的口径。
CONTENT_THRESHOLD = 16

DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "Docs" / "logotransparent.png"
DEFAULT_TARGET = Path(__file__).resolve().parent.parent / "static" / "logo.png"


class Png:
    """解码后的 RGBA 位图。pixels 为 row-major 的 4 字节/像素。"""

    def __init__(self, width: int, height: int, pixels: bytearray) -> None:
        self.width = width
        self.height = height
        self.pixels = pixels

    def content_bbox(self, threshold: int = 0) -> tuple[int, int, int, int] | None:
        """alpha > threshold 的包围盒，半开区间 (x0, y0, x1, y1)；整幅透明返回 None。

        threshold 不是可有可无的：母版里 alpha=1（0.4% 不透明度）的像素一直铺到
        画布边缘，按 alpha>0 裁剪等于没裁。用 translate 把 <=threshold 的 alpha
        直接打成 0，再按行 lstrip/rstrip 找首末非零 —— 两步都在 C 层，
        不必在 150 万像素上跑 Python 循环。
        """
        table = bytes(0 if value <= threshold else value for value in range(256))
        alpha = bytes(self.pixels[3::4]).translate(table)
        stride = self.width
        x0, y0, x1, y1 = self.width, self.height, 0, 0
        for y in range(self.height):
            row = alpha[y * stride : (y + 1) * stride]
            if not row.strip(b"\x00"):
                continue
            first = stride - len(row.lstrip(b"\x00"))
            last = stride - 1 - (stride - len(row.rstrip(b"\x00")))
            x0 = min(x0, first)
            x1 = max(x1, last + 1)
            y0 = min(y0, y)
            y1 = y + 1
        if x1 == 0:
            return None
        return (x0, y0, x1, y1)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, width: int, height: int) -> bytearray:
    """撤销 PNG 的行过滤器，还原成原始 RGBA。"""
    stride = width * BPP
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        if ftype == 1:
            for i in range(BPP, stride):
                line[i] = (line[i] + line[i - BPP]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - BPP] if i >= BPP else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - BPP] if i >= BPP else 0
                up = prev[i]
                upleft = prev[i - BPP] if i >= BPP else 0
                line[i] = (line[i] + _paeth(left, up, upleft)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"未知的 PNG 行过滤器类型 {ftype}")
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return out


def load_png(path: Path) -> Png:
    """解码 8 位 RGBA 非隔行 PNG。母版正是这种格式。"""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIG):
        raise ValueError(f"{path} 不是 PNG 文件")

    pos = len(PNG_SIG)
    idat = bytearray()
    width = height = None
    bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 4 长度 + 4 类型 + 数据 + 4 CRC
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif ctype == b"IDAT":
            idat += payload
        elif ctype == b"IEND":
            break

    if width is None:
        raise ValueError(f"{path} 缺少 IHDR")
    if (bit_depth, color_type, interlace) != (8, 6, 0):
        raise ValueError(
            "只支持 8 位 RGBA 非隔行 PNG，"
            f"实际 bit_depth={bit_depth} color_type={color_type} interlace={interlace}"
        )
    return Png(width, height, _unfilter(zlib.decompress(bytes(idat)), width, height))


def resize_area(img: Png, box: tuple[int, int, int, int], out_w: int, out_h: int) -> bytearray:
    """按面积平均缩放（盒式重采样）。

    先乘 alpha 再平均、最后除回去（预乘/反预乘）—— 母版里 alpha=0 的位置
    带着未清零的垃圾 RGB，直接平均会把边缘染灰。alpha 归零处 RGB 一并写 0。
    """
    x0, y0, x1, y1 = box
    src_w = x1 - x0
    src_h = y1 - y0
    src = img.pixels
    src_stride = img.width * BPP
    out = bytearray(out_w * out_h * BPP)

    for oy in range(out_h):
        sy0 = y0 + (oy * src_h) // out_h
        sy1 = max(sy0 + 1, y0 + ((oy + 1) * src_h) // out_h)
        for ox in range(out_w):
            sx0 = x0 + (ox * src_w) // out_w
            sx1 = max(sx0 + 1, x0 + ((ox + 1) * src_w) // out_w)

            r = g = b = a = 0
            count = 0
            for sy in range(sy0, sy1):
                row = sy * src_stride
                for sx in range(sx0, sx1):
                    i = row + sx * BPP
                    alpha = src[i + 3]
                    r += src[i] * alpha
                    g += src[i + 1] * alpha
                    b += src[i + 2] * alpha
                    a += alpha
                    count += 1

            o = (oy * out_w + ox) * BPP
            # 先定 alpha：a/count 可能小到四舍五入成 0，而 RGB 是按 a 反预乘算出来的
            # 有限值。若先写 RGB 再发现 alpha 为 0，就会留下 alpha=0 却带颜色的像素 ——
            # 正是这个函数要防的「边缘发灰」。
            out_alpha = _u8(a / count)
            if out_alpha == 0:
                continue  # 保持 0,0,0,0
            out[o] = _u8(r / a)
            out[o + 1] = _u8(g / a)
            out[o + 2] = _u8(b / a)
            out[o + 3] = out_alpha
    return out


def _u8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _filter_line(ftype: int, line: bytes, prev: bytes) -> bytearray:
    out = bytearray(len(line))
    for i, value in enumerate(line):
        left = line[i - BPP] if i >= BPP else 0
        up = prev[i]
        if ftype == 0:
            pred = 0
        elif ftype == 1:
            pred = left
        elif ftype == 2:
            pred = up
        elif ftype == 3:
            pred = (left + up) >> 1
        else:
            pred = _paeth(left, up, prev[i - BPP] if i >= BPP else 0)
        out[i] = (value - pred) & 0xFF
    return out


def encode_png(width: int, height: int, pixels: bytes) -> bytes:
    """编码为 RGBA PNG。逐行在 5 种过滤器里挑 MSAD 最小的那个，再 zlib 最高压缩。"""
    stride = width * BPP
    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        line = pixels[y * stride : (y + 1) * stride]
        best_type = 0
        best = None
        best_score = -1
        for ftype in range(5):
            candidate = _filter_line(ftype, line, prev)
            score = sum(min(v, 256 - v) for v in candidate)
            if best is None or score < best_score:
                best, best_type, best_score = candidate, ftype, score
        raw.append(best_type)
        raw += best
        prev = line

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _chunk(ctype: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", crc)


def build_logo(src: Path, dst: Path, target_height: int = 128) -> dict:
    """裁掉透明留白、等比缩放到 target_height，写出 dst。返回统计信息。"""
    img = load_png(src)
    box = img.content_bbox(CONTENT_THRESHOLD)
    if box is None:
        raise ValueError(f"{src} 整幅透明，没有可裁剪的内容")

    x0, y0, x1, y1 = box
    src_w, src_h = x1 - x0, y1 - y0
    out_w = max(1, round(src_w * target_height / src_h))
    pixels = resize_area(img, box, out_w, target_height)
    payload = encode_png(out_w, target_height, pixels)

    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(payload)

    return {
        "src_bbox": box,
        "src_width": src_w,
        "src_height": src_h,
        "width": out_w,
        "height": target_height,
        "bytes": len(payload),
    }


def build_favicon(src: Path, dst: Path, size: int = 64, padding: int = 4) -> dict:
    """把横版字标等比装进 size×size 的方形透明画布，居中，不拉伸（Spec3 §7）。

    直接引用横版 logo.png 当图标时，浏览器各家处理不一 —— 有的拉伸填满方格
    （字标被压扁），有的留白（图形偏小且不居中）。先做成正方形是唯一稳定的做法。

    `resize_area` 只能把源矩形铺满整个输出，故在其上补一层「等比缩放 + 居中贴图」。
    """
    img = load_png(src)
    box = img.content_bbox(CONTENT_THRESHOLD)
    if box is None:
        raise ValueError(f"{src} 整幅透明，没有内容")

    x0, y0, x1, y1 = box
    inner = size - padding * 2
    scale = min(inner / (x1 - x0), inner / (y1 - y0))
    out_w = max(1, round((x1 - x0) * scale))
    out_h = max(1, round((y1 - y0) * scale))
    stamp = resize_area(img, box, out_w, out_h)

    canvas = bytearray(size * size * BPP)  # 全透明
    ox, oy = (size - out_w) // 2, (size - out_h) // 2
    for y in range(out_h):
        start = ((oy + y) * size + ox) * BPP
        canvas[start : start + out_w * BPP] = stamp[y * out_w * BPP : (y + 1) * out_w * BPP]

    payload = encode_png(size, size, bytes(canvas))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(payload)
    return {"size": size, "content": (out_w, out_h), "bytes": len(payload)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成顶栏 logo 与标签页图标（Spec2 §5.5 / Spec3 §7）")
    ap.add_argument("--src", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--dst", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--height", type=int, default=128)
    ap.add_argument(
        "--favicon",
        action="store_true",
        help="生成方形标签页图标：读 static/logo.png，写 static/favicon.png（64×64）",
    )
    args = ap.parse_args(argv)

    if args.favicon:
        # 源字标固定是 static/logo.png（要先跑一次不带 --favicon 的既有路径拿到它）
        src = DEFAULT_TARGET
        dst = (args.dst if args.dst != DEFAULT_TARGET else src.with_name("favicon.png"))
        stats = build_favicon(src, dst)
        w, h = stats["content"]
        print(f"源字标：{src}")
        print(f"产物：{dst}")
        print(f"  {stats['size']}×{stats['size']}，内容 {w}×{h} 居中，"
              f"{stats['bytes'] / 1024:.1f} KB")
        return 0

    stats = build_logo(args.src, args.dst, args.height)
    print(f"母版：{args.src}")
    print(f"  内容包围盒：x {stats['src_bbox'][0]}..{stats['src_bbox'][2] - 1}, "
          f"y {stats['src_bbox'][1]}..{stats['src_bbox'][3] - 1}"
          f"（{stats['src_width']}×{stats['src_height']}）")
    print(f"产物：{args.dst}")
    print(f"  {stats['width']}×{stats['height']}，{stats['bytes'] / 1024:.1f} KB"
          f"（母版 {args.src.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
