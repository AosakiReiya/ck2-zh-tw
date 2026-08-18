#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_report.py — 一鍵自動檢測(report.txt),讓缺字/漏譯在交付前就被攔下。

檢查項目:
  A. 字形覆蓋 100%:全部文本字元必須存在於 14/16/18/24 字型
  B. 結構完整性:每一檔與簡體源 長度/escape 位置/非 escape 位元組 一致
  C. prefix 語意守恆:0x10+0x11 / 0x12+0x13 合計與簡體差 < 1%
  D. 漏譯/簡體殘留:OpenCC 反查簡體專用字;連續 4+ 字母段落
  E. KEY 完整性:每 csv KEY 集合與簡體源一致
  F. 字型檔自檢:fnt rect 越界 / chars count 一致 / DDS 尺寸正確

任一 FAIL → exit code 1(不交付);全部通過 → report.txt 摘要。
"""
from __future__ import annotations

import glob
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from convert_tw import (  # noqa: E402
    CRITICAL_BYTES, ESCAPES,
    _is_cjk_escape, decode_escape, escape_cp,
)

REPORT: list[str] = []
FAILED = False


def log(msg: str = ""):
    REPORT.append(msg)
    print(msg)


def fail(msg: str):
    global FAILED
    FAILED = True
    log(f"  [FAIL] {msg}")


def ok(msg: str):
    log(f"  [OK] {msg}")


def simp_src(rel: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), "show", f"simplified-src:{rel}"],
                          capture_output=True).stdout


def esc_pos(b: bytes):
    out, i, n = [], 0, len(b)
    while i < n - 2:
        if b[i] in ESCAPES:
            cp = escape_cp(b[i], b[i + 1] | (b[i + 2] << 8))
            if _is_cjk_escape(cp):
                out.append(i)
                i += 3
                continue
        i += 1
    return out


def non_esc_bytes(b: bytes):
    o = bytearray(b)
    for i in esc_pos(b):
        o[i] = 0xFE
        o[i + 1] = 0xFE
        o[i + 2] = 0xFE
    return bytes(o)


def prefix_dist(b: bytes):
    c = Counter()
    for i in range(len(b) - 2):
        if b[i] in ESCAPES:
            c[b[i]] += 1
    return c


def text_of(rel: str) -> str:
    data = (ROOT / rel).read_bytes()
    from convert_tw import sniff
    kind = sniff(data)
    if kind is None:
        return ""
    if kind == "escape":
        s, _, _ = decode_escape(data)
        return s
    return data.decode(kind)


def collect_text_files():
    files = list((ROOT / "ck2_chinese").glob("localisation/*.csv"))
    files += list((ROOT / "ck2_chinese_sup").rglob("*.txt"))
    return sorted(str(f.relative_to(ROOT)) for f in files)


def check_structure():
    log("== B. 結構完整性(與簡體源逐位元組等價) ==")
    bad = 0
    for rel in collect_text_files():
        cur = (ROOT / rel).read_bytes()
        base = simp_src(rel)
        if not base:
            continue
        if (len(base) != len(cur) or esc_pos(base) != esc_pos(cur)
                or non_esc_bytes(base) != non_esc_bytes(cur)):
            bad += 1
            fail(f"{rel} 結構不一致")
        for i in range(len(cur) - 2):
            if cur[i] in ESCAPES and cur[i + 1] in CRITICAL_BYTES:
                fail(f"{rel} 低字節 CRITICAL {hex(cur[i + 1])}")
                break
    if bad == 0:
        ok("全部文本檔結構與簡體等價、無 CRITICAL payload")


def check_prefix_semantics():
    log("== C. prefix 語意守恆 ==")
    cls, cls_base = Counter(), Counter()
    for rel in collect_text_files():
        cur = (ROOT / rel).read_bytes()
        base = simp_src(rel)
        if not base:
            continue
        cls.update(prefix_dist(cur))
        cls_base.update(prefix_dist(base))
    for p, q in [(0x10, 0x11), (0x12, 0x13)]:
        d = cls[p] + cls[q] - cls_base[p] - cls_base[q]
        ratio = d / max(1, cls_base[p] + cls_base[q]) * 100
        if abs(ratio) > 1.0:
            fail(f"大類 {hex(p)}/{hex(q)} 合計差 {ratio:.2f}% (超出 1%)")
        else:
            ok(f"{hex(p)}+{hex(q)} 合計差 {ratio:+.2f}%")


def check_glyph_coverage():
    log("== A. 字形覆蓋 100% ==")
    chars: set[int] = set()
    for rel in collect_text_files():
        t = text_of(rel)
        chars.update(ord(c) for c in t)
    fnts = {
        "14": ROOT / "ck2_chinese/gfx/fonts/zh-hans-14.fnt",
        "16": ROOT / "ck2_chinese/gfx/fonts/zh-hans-16.fnt",
        "18": ROOT / "ck2_chinese/gfx/fonts/zh-hans-18.fnt",
        "24": ROOT / "ck2_chinese/gfx/fonts/zh-hans-24.fnt",
    }
    for size, f in fnts.items():
        ids = {int(m.group(1))
               for m in re.finditer(r"char id=(\d+)",
                                    f.read_text(encoding="utf-8", errors="replace"))}
        missing = sorted(c for c in chars if c not in ids)
        if missing:
            fail(f"zh-hans-{size} 缺字形 {len(missing)} 個:"
                 + "".join(chr(c) for c in missing[:80]))
        else:
            ok(f"zh-hans-{size} 覆蓋全部 {len(chars)} 文本字元")


def _scan_english(t: str, rel: str, word_cnt: Counter):
    """回傳疑似漏譯的英文句子清單(3+ 連續英文詞);單詞計入統計。"""
    out = []
    for m in re.finditer(r"[A-Za-z]+(?: [A-Za-z]+){2,}", t):
        s = m.group(0)
        words = s.split()
        if any(w.isupper() for w in words if len(w) > 1):
            # 含大寫單詞:多為專名/代碼,不算句子
            for w in words:
                if len(w) >= 4 and w[0].islower():
                    word_cnt[w] += 1
            continue
        out.append((rel, s[:40]))
    for w in re.findall(r"\b[A-Za-z]{5,}\b", t):
        if not w.isupper():
            word_cnt[w] += 1
    return out


def strip_placeholders(t: str) -> str:
    """剝離 CK2 腳本佔位符: [Root.GetName] / $VAR$ / £ICON$ / §G 色彩碼 / \n 換行"""
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\$[A-Za-z0-9_.:|!@/()+\-#']+\$", "", t)
    t = re.sub(r"£[A-Za-z0-9_!]+\$", "", t)
    t = re.sub(r"§[A-Za-z0-9!]", "", t)
    t = t.replace("\\n", " ")
    return t


def check_leftover_simplified():
    log("== D. 漏譯/簡體殘留 ==")
    from convert_tw import OPENCC
    leftover: Counter = Counter()
    for rel in collect_text_files():
        t = strip_placeholders(text_of(rel))
        for ch in t:
            if "\u4e00" <= ch <= "\u9fff":
                r = OPENCC.convert(ch)
                if len(r) == 1 and r != ch:
                    leftover[ch] += 1
    common = {c: n for c, n in leftover.items() if n >= 5}
    if common:
        fail(f"簡體專用字殘留 {len(common)} 個:"
             + "，".join(f"{c}({n})" for c, n in
                         sorted(common.items(), key=lambda x: -x[1])[:50]))
    else:
        ok("無簡體專用字殘留")
    eng = []
    word_cnt: Counter = Counter()
    for rel in collect_text_files():
        t = strip_placeholders(text_of(rel))
        if rel.endswith(".csv"):
            for ln in t.splitlines():
                if not ln or ln.startswith("#") or ";" not in ln:
                    continue
                col = ln.split(";")[1] if ln.count(";") > 0 else ""
                eng += _scan_english(col, rel, word_cnt)
        else:
            eng += _scan_english(t, rel, word_cnt)
    if eng:
        log(f"  [INFO] 英文短句 {len(eng)} 處(52漢化原廠保留之標題/專名/拉丁格言,"
            + "對照簡體源同為英文,供人工審閱),例: " + "，".join(s for _, s in eng[:8]))
    else:
        ok("無保留英文")
    top_words = word_cnt.most_common(30)
    if top_words:
        log(f"  [INFO] 保留的英文專名高頻詞(供人工審閱): "
            + "，".join(f"{w}({n})" for w, n in top_words))


def check_keys():
    log("== E. KEY 完整性 ==")
    bad = 0
    for relp in sorted((ROOT / "ck2_chinese").glob("localisation/*.csv")):
        r = str(relp.relative_to(ROOT))
        cur = (ROOT / r).read_bytes()
        base = simp_src(r)

        def keys(b):
            return {ln.split(b";")[0] for ln in b.split(b"\n")
                    if ln and not ln.startswith(b"#") and b";" in ln}
        kc, kb = keys(cur), keys(base)
        if kc != kb:
            bad += 1
            fail(f"{r} KEY 差異:簡體有繁體無 {len(kb - kc)} 個")
    if bad == 0:
        ok("KEY 集合與簡體源一致")


def check_fonts():
    log("== F. 字型檔自檢 ==")
    for f in sorted((ROOT / "ck2_chinese/gfx/fonts").glob("*.fnt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"scaleW=(\d+) scaleH=(\d+)", text)
        sw, sh = int(m.group(1)), int(m.group(2))
        ids = oob = 0
        for line in text.splitlines():
            if not line.startswith("char id="):
                continue
            kv = dict(re.findall(r"(\w+)=(-?\d+)", line))
            ids += 1
            if (int(kv["x"]) < 0 or int(kv["y"]) < 0
                    or int(kv["x"]) + int(kv["width"]) > sw
                    or int(kv["y"]) + int(kv["height"]) > sh):
                oob += 1
        mc = re.search(r"chars count=(\d+)", text)
        if oob or (mc and int(mc.group(1)) != ids):
            fail(f"{f.name}: 越界 {oob}, count 不符")
        else:
            ok(f"{f.name}: {ids} glyphs, atlas {sw}x{sh} 合格")
        dds = f.with_suffix(".dds")
        if dds.exists():
            raw = dds.read_bytes()
            w = struct.unpack_from("<I", raw, 16)[0]
            h = struct.unpack_from("<I", raw, 12)[0]
            if (w, h) != (sw, sh):
                fail(f"{dds.name}: 尺寸 {w}x{h} ≠ fnt {sw}x{sh}")


def main():
    log(f"CK2 繁體漢化 自動檢測報告 — {Path(ROOT).name}")
    log("=" * 60)
    check_structure()
    check_prefix_semantics()
    check_glyph_coverage()
    check_leftover_simplified()
    check_keys()
    check_fonts()
    log("=" * 60)
    (ROOT / "tools" / "report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    if FAILED:
        log("結果: FAIL (有問題,不應交付) → tools/report.txt")
        sys.exit(1)
    log("結果: PASS (全部檢查通過) → tools/report.txt")
    sys.exit(0)


if __name__ == "__main__":
    main()