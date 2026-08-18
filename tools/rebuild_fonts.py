#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild_fonts.py — 用 Windows TrueType 繁體字型重建 CK2 中文字形包。

原 zh-hans-*.fnt/.dds 只含簡體字形(繁體字形缺如 → 遊戲內豆腐)。
本工具:
  1. 讀取原 .fnt 的 BMF 文字格式(取其字形集合 + 版面參數)
  2. 合併「轉換後繁體文本」出現的所有字元
  3. 以微軟正黑體(msjh)等 TTF 光柵化全部字形
  4. 藍天(skyline)打包進 atlas
  5. 寫出 DDS(DXT3 8bpp,與原檔相同位元組/像素) + 新 .fnt

覆寫項目:ck2_chinese/gfx/fonts/ 下 zh-hans-*.fnt / zh-hans-*.dds
"""
from __future__ import annotations

import math
import re
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = ROOT / "ck2_chinese" / "gfx" / "fonts"

FACES = {
    "zh-hans-14": "SourceHanSerifTC-Regular.otf",
    "zh-hans-16": "SourceHanSerifTC-Regular.otf",
    "zh-hans-18": "SourceHanSerifTC-Regular.otf",
    "zh-hans-24": "SourceHanSerifTC-Regular.otf",
    "zh-hans-decorative": "SourceHanSerifTC-Bold.otf",
    "zh-hans-map": "SourceHanSerifTC-Bold.otf",
}
WIN_FONT_DIR = Path(r"/mnt/e/Projects/_GameTranslate/OTF/TraditionalChinese")

# CK2 文字解析器對單一 fnt 的字形數有 ~8192 緩衝上限(實錘:52 原廠六檔全部 ≤7461,
# 我們全部 >8192 → 載入越界崩潰)。所有字型鎖 MAX_GLYPH=7000:保證相容。
MAX_GLYPH = 7000


# ---------- BMF 解析 ----------

def parse_bmf(path: Path):
    """回傳 (info dict, common dict, chars {id: dict})"""
    text = path.read_bytes().decode("utf-8", errors="replace")
    info = {}; common = {}; chars = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        kind = parts[0]
        kv = {}
        for p in parts[1:]:
            m = re.match(r'([\wа-я]+)="?([^"]*)"?$', p, re.IGNORECASE)
            if m:
                kv[m.group(1)] = m.group(2)
        if kind == "info":
            info = kv
        elif kind == "common":
            common = kv
        elif kind == "char":
            chars[int(kv["id"])] = {k: int(v) for k, v in kv.items()}
    return info, common, chars


def corpus_chars() -> set[int]:
    """從轉換後的繁體文本收集所有字元。

    與 convert_tw 相同的嗅探順序:escape 格式優先(0x10-0x13 是合法 utf8
    控制字元,直接 utf8 decode 會把中文吞成亂碼),再 utf8 / gb18030。"""
    sys.path.insert(0, str(ROOT / "tools"))
    from convert_tw import decode_escape, sniff
    files = list((ROOT / "ck2_chinese").glob("localisation/*.csv"))
    files += list((ROOT / "ck2_chinese_sup").rglob("*.txt"))
    chars = set()
    for f in files:
        data = f.read_bytes()
        kind = sniff(data)
        if kind is None:
            continue
        if kind == "escape":
            s, _, _ = decode_escape(data)
        else:
            s = data.decode(kind)
        for ch in s:
            chars.add(ord(ch))
    return chars


# ---------- DXT3 / DXT5 writer ----------

def _color_dxt1(block):
    """BC1 色塊:回傳 (c0, c1, idx_words)。與 DXT3 共用。"""
    def to565(p):
        # RGB565:R5 G6 B5 — G 須 >>2(6-bit),誤用 >>3 會讓白色變紫(248,124,248)
        return ((p[0] >> 3) << 11) | ((p[1] >> 2) << 5) | (p[2] >> 3)
    def lum(p):
        return p[0] * 299 + p[1] * 587 + p[2] * 114
    colored = [b for b in block if b[3] > 128]
    if not colored:
        return 0, 0, 0
    lo = min(colored, key=lum)
    hi = max(colored, key=lum)
    c0, c1 = to565(hi), to565(lo)
    r0, g0, b0 = hi[0], hi[1], hi[2]
    r1, g1, b1 = lo[0], lo[1], lo[2]
    if c0 <= c1:
        c0, c1 = c1, c0
        r0, g0, b0, r1, g1, b1 = r1, g1, b1, r0, g0, b0
        pal = [(r1, g1, b1), (r0, g0, b0),
               ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
               ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3)]
    else:
        pal = [(r0, g0, b0), (r1, g1, b1),
               ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
               ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3)]
    words = 0
    for i in range(16):
        p = block[i]
        if p[3] <= 128:
            idx = 0
        else:
            best = min(range(4), key=lambda k: (p[0] - pal[k][0]) ** 2 + (p[1] - pal[k][1]) ** 2 + (p[2] - pal[k][2]) ** 2)
            idx = best
        words |= idx << (2 * i)
    return c0, c1, words


def rgba_to_dxt3(img: Image.Image) -> bytes:
    """DXT3(BC2):alpha 4-bit 量化 + BC1 色塊。"""
    def encode(block):
        abytes = bytearray(8)
        for i in range(16):
            abytes[i // 2] |= (round(block[i][3] / 255 * 15) & 0xF) << (4 * (i % 2))
        c0, c1, words = _color_dxt1(block)
        return bytes(abytes) + struct.pack("<HH", c0, c1) + struct.pack("<I", words)
    return _encode_blocks(img, encode)


def rgba_to_dxt5(img: Image.Image) -> bytes:
    """DXT5(BC3):alpha 8-bit 兩端點 + 3-bit 逐步插值 + BC1 色塊(原廠 decorative/map 格式)。"""
    def encode(block):
        alphas = [b[3] for b in block]
        a0 = max(alphas)
        a1 = min(alphas)
        if a0 > a1:
            pal = [((7 - k) * a0 + k * a1) // 7 for k in range(8)]
        else:
            pal = [a0] + [((5 - k) * a0 + k * a1) // 5 for k in range(1, 6)] + [0, 255]
        aindices = 0
        for i in range(16):
            best = min(range(8), key=lambda k: abs(alphas[i] - pal[k]))
            aindices |= best << (3 * i)
        c0, c1, words = _color_dxt1(block)
        return bytes((a0, a1)) + aindices.to_bytes(6, "little") + struct.pack("<HH", c0, c1) + struct.pack("<I", words)
    return _encode_blocks(img, encode)


def _encode_blocks(img: Image.Image, blockfn):
    """以 4x4 block 對整圖套用 blockfn(回傳 bytes),回傳壓縮資料。"""
    w, h = img.size
    pw, ph = math.ceil(w / 4) * 4, math.ceil(h / 4) * 4
    src = img.convert("RGBA")
    if (pw, ph) != (w, h):
        canvas = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        canvas.paste(src, (0, 0))
        src = canvas
    px = src.load()
    out = bytearray()
    for by in range(0, ph, 4):
        for bx in range(0, pw, 4):
            block = [px[bx + dx, by + dy] for dy in range(4) for dx in range(4)]
            out += blockfn(block)
    return bytes(out)


def write_dds(path: Path, img: Image.Image, fourcc: str = "DXT3"):
    w, h = img.size
    # 原廠 header 同構:decorative/map(DXT5)= flags 0xA1007 + mip=1 + depth=1;
    # 文字(DXT3)= flags 0x81007 + mip=0 + depth=1;linearSize = w*h(DXT3/DXT5 皆 8bpp)
    mips = 1 if fourcc == "DXT5" else 0
    flags = 0xA1007 if mips else 0x81007
    data = rgba_to_dxt5(img) if fourcc == "DXT5" else rgba_to_dxt3(img)
    header = struct.pack(
        "<4s7I11I2I4s5I5I",
        b"DDS ",                     # magic
        124,                          # dwSize
        flags,                        # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE(+MIPMAPCOUNT 若 DXT5)
        h, w,                         # height, width
        w * h,                        # linear size (8bpp DXT)
        1, mips,                      # depth, mipmaps
        *([0] * 11),                  # reserved1
        32, 4,                        # pf size, pf flags (FOURCC)
        fourcc.encode("ascii"),       # fourcc
        0, 0, 0, 0, 0,                # rgba masks
        0x1000, 0, 0, 0, 0,           # caps: TEXTURE
    )
    path.write_bytes(header + data)


# ---------- 打包 ----------

def skyline_pack(rects, size_w, size_h):
    """回傳 {index: (x, y)}"""
    heights = [0] * size_w
    place = {}
    for i, (w, h) in enumerate(rects):
        best_x = None
        best_h = None
        for x in range(size_w - w + 1):
            col_h = max(heights[x:x + w])
            if col_h + h <= size_h:
                if best_h is None or col_h < best_h:
                    best_h = col_h
                    best_x = x
        if best_x is None:
            raise RuntimeError(f"atlas 放不下 char {i} ({w}x{h})")
        for x in range(best_x, best_x + w):
            heights[x] = best_h + h
        place[i] = (best_x, best_h)
    return place


# ---------- 主流程 ----------

def rebuild_one(name: str, extra_chars: set[int], dry: bool = False):
    fnt_path = FONTS_DIR / f"{name}.fnt"
    info, common, chars = parse_bmf(fnt_path)
    base = int(common["base"])
    lh = int(common["lineHeight"])
    size = int(info["size"])
    face = FACES[name]
    font_f = ImageFont.truetype(str(WIN_FONT_DIR / face), size)
    font_f = ImageFont.truetype(str(WIN_FONT_DIR / face), size)
    # ── 字形集漏斗:corpus(繁體文本 100%)全保留;原廠字形按「碼序低=常用」補滿剩餘槽 ──
    # 視覺/相容:總數 ≦ MAX_GLYPH(遊戲 8192 緩衝,留安全餘量),文本 0 缺字。
    corpus_ids = set(extra_chars)
    orig_ids = set(chars)
    if len(corpus_ids) > MAX_GLYPH:
        raise RuntimeError(f"{name}: corpus {len(corpus_ids)} 字已超限")
    refill_pool = sorted(orig_ids - corpus_ids)   # 原廠常用字形(不在文本者)
    refill = refill_pool[: MAX_GLYPH - len(corpus_ids)]
    # 剔除控制字元字形(含 id 9/10/13):52 原廠沒有,渲染含 0-height 的字形
    # 或 \n 方塊字會讓 DX9 CreateVertexBuffer 失敗(gfx_dx9.cpp Error create vertices)
    ids = sorted((corpus_ids | set(refill)) - {c for c in range(0, 32)})
    if len(ids) > MAX_GLYPH:
        raise RuntimeError(f"{name}: 字形集 {len(ids)} 超限")
    print(f"  [{name}] 字形集: 文本 {len(corpus_ids)} 全保 + 原廠常用 {len(refill)} = {len(ids)} (≤{MAX_GLYPH})")

    cands = {
        "zh-hans-14": [(1024, 2048), (2048, 2048), (2048, 4096)],
        "zh-hans-16": [(1024, 2048), (2048, 2048), (2048, 4096)],
        "zh-hans-18": [(1024, 2048), (2048, 2048), (2048, 4096)],
        "zh-hans-24": [(1024, 2048), (2048, 2048), (2048, 4096), (4096, 4096)],
        # 原廠規格:DXT5 + 4096 寬(遊戲 DX9 載入 8192² DXT3 會崩潰,勿放大)
        "zh-hans-decorative": [(4096, 7000), (4096, 8192)],
        "zh-hans-map": [(4096, 7000), (4096, 8192)],
    }
    fmt = "DXT5" if name in ("zh-hans-decorative", "zh-hans-map") else "DXT3"
    # ── 每檔 yoffset 自適應校正:與 52 原廠共同字形的 yoffset 中位差補償 ──
    import subprocess as _sp
    import statistics as _st
    ycomp = 0
    xcomp = 0
    try:
        rawh = _sp.run(["git", "-C", str(ROOT), "show",
                        f"simplified-src:ck2_chinese/gfx/fonts/{name}.fnt"],
                       capture_output=True).stdout.decode("utf-8", "replace")
        need = {}
        for l in rawh.splitlines():
            if l.startswith("char id="):
                kv = dict(re.findall(r"(\w+)=(-?\d+)", l))
                k = int(kv["id"])
                if k in ids:
                    need[k] = (int(kv["yoffset"]), int(kv["xoffset"]))
        if need:
            dy = []
            dx = []
            fhf0 = ImageFont.truetype(str(WIN_FONT_DIR / face), size)
            for cid in ids:
                if cid in need:
                    b = fhf0.getbbox(chr(cid))
                    dy.append(need[cid][0] - (b[1] - 1 - 3))
                    dx.append(need[cid][1] - (b[0] - 1))
            ycomp = round(_st.median(dy))
            xcomp = round(_st.median(dx))
            print(f"  [{name}] 度量補償 y{ycomp:+d} x{xcomp:+d} (對 52 原廠)")
    except Exception:
        pass
    size = int(info["size"])
    orig_size = size
    orig_lh, orig_base = lh, base
    font_f = ImageFont.truetype(str(WIN_FONT_DIR / face), size)
    while True:
        metrics = {}
        rects = []
        for cid in ids:
            ch = chr(cid)
            try:
                bbox = font_f.getbbox(ch)
                adv = font_f.getlength(ch)
            except Exception:
                bbox = (0, 0, 0, 0)
                adv = 0
            w = max(1, bbox[2] - bbox[0] + 2)
            h = max(1, bbox[3] - bbox[1] + 2)
            metrics[cid] = (w, h, bbox, float(adv))
            rects.append((w, h))
        place = None
        for scale_w, scale_h in cands[name]:
            try:
                place = skyline_pack(rects, scale_w, scale_h)
                break
            except RuntimeError:
                continue
        if place is None:
            size -= 6
            if size < 32:
                raise RuntimeError(f"{name}: 畫布尺寸 + 字體點數都不夠 ({orig_size}->{size})")
            scale_lh = size / orig_size
            lh = max(8, round(orig_lh * scale_lh))
            base = max(6, round(orig_base * scale_lh))
            font_f = ImageFont.truetype(str(WIN_FONT_DIR / face), size)
            print(f"  [{name}] 塞不下,降字體 {orig_size}->{size}px (lineHeight {orig_lh}->{lh}, base {orig_base}->{base})")
            continue
        break

    canvas = Image.new("RGBA", (scale_w, scale_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    fnt_lines = []
    fnt_lines.append(f'info face="{face}" size={size} bold=0 italic=0 charset="" stretchH=100 smooth=1 aa=1 padding=0,0,0,0 spacing=1,1')
    fnt_lines.append(f"common lineHeight={lh} base={base} scaleW={scale_w} scaleH={scale_h} pages=1")
    out_metrics = []
    for k, cid in enumerate(ids):
        x, y = place[k]
        w, h, bbox, adv = metrics[cid]
        draw.text((x + 1 - bbox[0], y + 1 - bbox[1]), chr(cid), font=font_f, fill=(255, 255, 255, 255))
        # yoffset 校正:原廠(BMGlyph 度量)與 PIL bbox 對「字形在方格內位置」
        # 的定義差約 +3px → 全域 -3 對齊 52 原廠基準線(防文字下移/被裁殘形)
        yoff = bbox[1] - 1 - 3 + ycomp
        xoff = bbox[0] - 1 + xcomp
        xadv = max(1, int(adv) + 1)
        # width/height 強制 ≥1:0 尺寸字形(如空格)會讓遊戲
        # CreateVertexBuffer 失敗 → 閃退(gfx_dx9.cpp:1490,52 原廠 space=3x1)
        out_metrics.append((cid, x, y, max(1, w - 2), max(1, h - 2), xoff, yoff, xadv))
    for cid, x, y, w, h, xoff, yoff, xadv in out_metrics:
        fnt_lines.append(
            f"char id={cid:<5} x={x:<5} y={y:<5} width={w:<5} height={h:<5} xoffset={xoff:<5} yoffset={yoff:<5} xadvance={xadv:<5} page=0"
        )
    # 與 52 原廠完全同構:只 output info/common/char 三種行。
    # 標準 BMF 的 page / chars count / kernings 行會讓 CK2 自製解析器
    # 錯亂(gfx_dx9.cpp Error create vertices → 無字 + 閃退),已全數移除。
    fnt_text = "\n".join(fnt_lines) + "\n"
    if dry:
        print(f"[dry] {name}: {len(ids)} glyphs, atlas {scale_w}x{scale_h}, DDS ~{round((scale_w*scale_h)//2/1e6,1)}MB")
        return
    write_dds(FONTS_DIR / f"{name}.dds", canvas, fmt)
    (FONTS_DIR / f"{name}.fnt").write_text(fnt_text, encoding="utf-8")
    print(f"[ok] {name}: {len(ids)} glyphs -> {name}.dds/.fnt")


def main():
    dry = "--dry-run" in sys.argv
    extra = corpus_chars()
    print(f"corpus chars: {len(extra)}")
    for name in FACES:
        rebuild_one(name, extra, dry)


if __name__ == "__main__":
    main()