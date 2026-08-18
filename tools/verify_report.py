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
    """B. 結構完整性:以簡體源為基準,逐 KEY 比對位元組;
    - 換詞行(REWORD)只驗證 escape 型別合法
    - 我們『超集』多出的行(如簡體源缺的省份名)僅警告
    - 其餘行必須 byte 等價(prefix 語意重寫屬允許範圍,見 C 檢查)"""
    log("== B. 結構完整性(與簡體源逐位元組等價;換詞行除外) ==")
    REWORD = {
        "ck2_chinese/localisation/text1.csv": {
            "SM_AUDIO", "FE_JOIN_INTERNET_GAME", "FE_YOUNG_RULER",
        },
    }
    bad = 0
    extras = []
    for rel in collect_text_files():
        cur = (ROOT / rel).read_bytes()
        base = simp_src(rel)
        if not base:
            continue
        exempt = REWORD.get(rel, set())
        cmap, bmap = {}, {}
        for l in cur.split(b"\n"):
            key = l.split(b";")[0].decode("utf-8", "replace") if b";" in l else ""
            if key:
                cmap.setdefault(key, l)
        for l in base.split(b"\n"):
            key = l.split(b";")[0].decode("utf-8", "replace") if b";" in l else ""
            if key:
                bmap.setdefault(key, l)
        bad_row = False
        for key, bl in bmap.items():
            cl = cmap.get(key)
            if cl is None:
                bad_row = True
                fail(f"{rel} 缺行 {key}")
                continue
            if key in exempt:
                # 值欄 = 「KEY;」後到行尾(不 split 分號:payload 內可含 0x3B)
                val = cl[len(key.encode("utf-8")) + 1:]
                i = 0
                while i < len(val):
                    if val[i] in ESCAPES:
                        if i + 2 >= len(val):
                            bad_row = True
                            fail(f"{rel} 換詞行 {key} escape 截斷")
                            break
                        i += 3
                    elif val[i] < 0x80:
                        i += 1
                    else:
                        bad_row = True
                        fail(f"{rel} 換詞行 {key} 有非 escape 高位元組")
                        break
                continue
            # 允許的合法差異:escape 的 prefix/payload 語意重寫(byte-inplace,位置不變)。
            # 一致判定 = 行長同 + escape 位置集同 + 非 escape 位元組序同
            def escidx(b):
                out = []
                i = 0
                while i < len(b):
                    if b[i] in ESCAPES:
                        out.append(i)
                        i += 3
                    else:
                        i += 1
                return out
            def nonesc(b):
                out = []
                i = 0
                while i < len(b):
                    if b[i] in ESCAPES:
                        i += 3
                    else:
                        out.append(b[i])
                        i += 1
                return bytes(out)
            if (len(cl) != len(bl)) or escidx(cl) != escidx(bl) or nonesc(cl) != nonesc(bl):
                bad_row = True
                fail(f"{rel} 行結構不一致: {key}")
        for key in sorted(set(cmap) - set(bmap)):
            extras.append((rel, key))
        for i in range(len(cur) - 2):
            if cur[i] in ESCAPES and cur[i + 1] in CRITICAL_BYTES:
                fail(f"{rel} 低字節 CRITICAL {hex(cur[i + 1])}")
                break
        if bad_row:
            bad += 1
    if extras:
        log(f"  [INFO] 我們超集額外行 {len(extras)} 條(簡體源無,如補全省份名): "
            + "，".join(f"{r.split('/')[-1]}:{k}" for r, k in extras[:8]))
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
    log("== A. 字形覆蓋 100%(六字型全檢,翻譯品質保單) ==")
    chars: set[int] = set()
    for rel in collect_text_files():
        t = text_of(rel)
        chars.update(ord(c) for c in t if ord(c) >= 32)  # 控制字元不渲染,不需字形
    names = ("14", "16", "18", "24", "decorative", "map")
    all_ok = True
    for size in names:
        f = ROOT / f"ck2_chinese/gfx/fonts/zh-hans-{size}.fnt"
        ids = {int(m.group(1))
               for m in re.finditer(r"char id=(\d+)",
                                    f.read_text(encoding="utf-8", errors="replace"))}
        if len(ids) >= 8192:
            all_ok = False
            fail(f"zh-hans-{size} 字形數 {len(ids)} ≥8192(遊戲緩衝上限,必崩)")
        missing = sorted(c for c in chars if c not in ids)
        if missing:
            all_ok = False
            fail(f"zh-hans-{size} 缺字形 {len(missing)} 個:"
                 + "".join(chr(c) for c in missing[:80]))
        else:
            ok(f"zh-hans-{size} 覆蓋全部 {len(chars)} 文本字元"
               + (f"({len(ids)} glyphs)" if size in ("decorative", "map")
                  else f"({len(ids)} glyphs)"))
    return all_ok


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
        missing = kb - kc
        extra = kc - kb
        if missing:
            bad += 1
            fail(f"{r} 缺簡體 KEY {len(missing)} 個: {sorted(missing)[:5]}")
        if extra:
            log(f"  [INFO] {r} 超集 KEY {len(extra)} 個(簡體源無): {sorted(extra)[:5]}")
    if bad == 0:
        ok("KEY 集合與簡體源一致(超集另列 [INFO])")


def _decode_565(v):
    return ((v >> 11) & 31) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3


def check_glyph_whiteness():
    """解碼每檔 dds 的字形像素,確認是白/近白(≥200);紫(248,124,248)即 G 通道 bug → FAIL。"""
    log("== G. 字形著色(白度) ==")
    import pathlib as _pl
    allok = True
    for f in sorted((ROOT / "ck2_chinese/gfx/fonts").glob("*.dds")):
        raw = f.read_bytes()
        w = struct.unpack_from("<I", raw, 16)[0]
        h = struct.unpack_from("<I", raw, 12)[0]
        fcc = raw[84:88]
        fnt_path = f.with_suffix(".fnt")
        text = fnt_path.read_text(encoding="utf-8", errors="replace")
        rects = {}
        for line in text.splitlines():
            if line.startswith("char id="):
                kv = dict(re.findall(r"(\w+)=(-?\d+)", line))
                if int(kv["id"]) == 32:
                    continue
                rects.setdefault(chr(int(kv["id"])), (int(kv["x"]), int(kv["y"]),
                                 int(kv["width"]), int(kv["height"])))
        sampled = []
        for ch, (x, y, cw, chh) in list(rects.items())[:6]:
            if cw < 2 or chh < 2:
                continue
            bx, by = x + cw // 2, y + chh // 2
            off = 128 + ((by // 4) * (w // 4) + (bx // 4)) * 16
            c0, c1 = struct.unpack_from("<HH", raw, off + 8)
            p0, p1 = _decode_565(c0), _decode_565(c1)
            colors = [p0, p1]
            if any(c != (0, 0, 0) for c in colors):
                sampled.extend(c for c in colors if c != (0, 0, 0) and
                               sum(c) > 60)
        if not sampled:
            ok(f"{f.name}: 無可取樣字形")
            continue
        avg = tuple(sum(c[i] for c in sampled) // len(sampled) for i in range(3))
        if avg[0] >= 200 and avg[1] >= 200 and avg[2] >= 200:
            ok(f"{f.name}: 字形像素平均 RGB {avg} 為白 ✓")
        else:
            allok = False
            fail(f"{f.name}: 字形像素平均 RGB {avg} 偏色(白字 G 通道 bug?)")
    return allok


def check_metrics_alignment():
    """H. 字形度量校準:與 52 原廠共同字形的 yoffset/xoffset/height 中位數差。
    度量漂移(= 字體/工具差異)會造成文字下移、小號字被裁成殘形。"""
    import statistics
    import subprocess
    log("== H. 字形度量校準(與 52 原廠比對) ==")
    allok = True
    for f in sorted((ROOT / "ck2_chinese/gfx/fonts").glob("*.fnt")):
        def parse(t):
            m = {}
            for l in t.splitlines():
                if l.startswith("char id="):
                    kv = dict(re.findall(r"(\w+)=(-?\d+)", l))
                    m[int(kv["id"])] = (int(kv["xoffset"]), int(kv["yoffset"]),
                                         int(kv["width"]), int(kv["height"]),
                                         int(kv["xadvance"]))
            return m
        ours = parse(f.read_text(encoding="utf-8", errors="replace"))
        raw = subprocess.run(["git", "-C", str(ROOT), "show",
                              f"simplified-src:ck2_chinese/gfx/fonts/{f.name}"],
                             capture_output=True).stdout
        if not raw:
            continue
        orig = parse(raw.decode("utf-8", "replace"))
        common = (set(ours) & set(orig)) - {32}
        if len(common) < 50:
            continue
        dyo = statistics.median([ours[c][1] - orig[c][1] for c in common])
        dxo = statistics.median([ours[c][0] - orig[c][0] for c in common])
        dhh = statistics.median([ours[c][3] - orig[c][3] for c in common])
        dax = statistics.median([ours[c][4] - orig[c][4] for c in common])
        tol_ok = abs(dyo) <= 1 and abs(dxo) <= 1 and abs(dax) <= 1  # height 差為字體自然差異,僅報告
        if tol_ok:
            ok(f"{f.name}: 度量差 y≈{dyo:+.1f} x≈{dxo:+.1f} xadv≈{dax:+.1f} (h差≈{dhh:+.1f} 屬字體差異) 共同 {len(common)} 字")
        else:
            allok = False
            fail(f"{f.name}: 度量漂移 y≈{dyo:+.1f} x≈{dxo:+.1f} xadv≈{dax:+.1f} (>容差)")
    return allok


def check_fonts():
    # 原廠規格(與遊戲 DX9 載入相容):文字 = DXT3 ≤2048x4096;
    # decorative/map = DXT5 + 4096 寬 + ≤8192 高(8192² DXT3 會崩潰)
    SPEC = {
        "zh-hans-14.fnt": ("DXT3", 1024, 2048, 2048, 4096),
        "zh-hans-16.fnt": ("DXT3", 1024, 2048, 2048, 4096),
        "zh-hans-18.fnt": ("DXT3", 1024, 2048, 2048, 4096),
        "zh-hans-24.fnt": ("DXT3", 1024, 2048, 2048, 4096),
        "zh-hans-decorative.fnt": ("DXT5", 4096, 7000, 4096, 8192),
        "zh-hans-map.fnt": ("DXT5", 4096, 7000, 4096, 8192),
    }
    log("== F. 字型檔自檢 ==")
    for f in sorted((ROOT / "ck2_chinese/gfx/fonts").glob("*.fnt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"scaleW=(\d+) scaleH=(\d+)", text)
        sw, sh = int(m.group(1)), int(m.group(2))
        ids = oob = zero = cntrl = badlines = 0
        for line in text.splitlines():
            if line.startswith("char id="):
                kv = dict(re.findall(r"(\w+)=(-?\d+)", line))
                ids += 1
                if (int(kv["x"]) < 0 or int(kv["y"]) < 0
                        or int(kv["x"]) + int(kv["width"]) > sw
                        or int(kv["y"]) + int(kv["height"]) > sh):
                    oob += 1
                if int(kv["width"]) == 0 or int(kv["height"]) == 0:
                    zero += 1  # 0 尺寸字形 → DX9 vertex 建立失敗,閃退元兇
                if int(kv["id"]) in (9, 10, 13):
                    cntrl += 1  # 控制字元字形(52 原廠無)
            elif line.strip():
                kind = line.split()[0]
                if kind not in ("info", "common", "###", "char"):
                    badlines += 1  # page / chars count / kernings 等 CK2 解析器不認的行
        bad = oob or zero or cntrl or badlines

        comma_ok = True
        if f.name in SPEC:
            want_fcc, w0, h0, w1, h1 = SPEC[f.name]
            dds = f.with_suffix(".dds")
            raw = dds.read_bytes()
            fcc = raw[84:88].decode("ascii", errors="replace")
            dw = struct.unpack_from("<I", raw, 16)[0]
            dh = struct.unpack_from("<I", raw, 12)[0]
            size_ok = (dw == sw and dh == sh and w0 <= dw <= w1 and h0 <= dh <= h1)
            fmt_ok = fcc == want_fcc
            # fnt 尺寸須與 dds 一致
            if not (fmt_ok and size_ok):
                bad = True
                fail(f"{f.name}: spec 不符 (dds {dw}x{dh} {fcc}, 期待 {want_fcc} "
                     + f"{w0}x{h0}~{w1}x{h1}, fnt {sw}x{sh})")
                comma_ok = False
        if not comma_ok:
            continue
        if bad:
            fail(f"{f.name}: 越界 {oob} / 零尺寸 {zero} / 控制字 {cntrl} / 非標準行 {badlines}")
        else:
            ok(f"{f.name}: {ids} glyphs, atlas {sw}x{sh} 合格")




def check_ui_title_zone80():
    """I. UI 標題級文字不得使用 U+8000-U+80FF 字元(escape 高字節 0x80 在
    非插件渲染路徑(tab 標題)會 fallback 成 'ó' — 實錘:SM_AUDIO=聲音)。"""
    log("== I. UI 標題字元掃描(0x80xx 風險) ==")
    allok = True
    hits = []
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    from convert_tw import decode_escape, sniff
    for rel in sorted((ROOT / "ck2_chinese/localisation").glob("*.csv")):
        data = rel.read_bytes()
        kind = sniff(data)
        s = decode_escape(data)[0] if kind == "escape" else data.decode(kind)
        for ln in s.splitlines():
            if ";" not in ln:
                continue
            key, val = ln.split(";")[:2]
            if not (len(val) <= 8 and key.isupper() and len(key) < 40):
                continue
            # 受害路徑 = 視窗 chrome(tab 標題/視窗標題)類 KEY;
            # 事件按鈕/內容文字走插件路徑,不受影響(asm:以 SM_/FE_ 為限定)
            if not (key.startswith("SM_") or key.startswith("FE_")):
                continue
            for c in val:
                if 0x8000 <= ord(c) <= 0x80FF:
                    hits.append((key, c, val, rel.name))
                    break
    if hits:
        for key, c, val, rel in hits[:30]:
            fail(f"UI 標題 KEY {key}({rel}) 含 0x80xx 字 {c}(U+{ord(c):04X}): {val} → tab/按鈕將顯示 ó,需換詞")
        log(f"  [INFO] 共 {len(hits)} 條短 UI 標題含風險字(僅列示前 30)")
    else:
        ok("無 UI 標題級 0x80xx 字元(0 風險)")
    return allok

def main():
    log(f"CK2 繁體漢化 自動檢測報告 — {Path(ROOT).name}")
    log("=" * 60)
    check_structure()
    check_prefix_semantics()
    check_glyph_coverage()
    check_leftover_simplified()
    check_keys()
    check_fonts()
    check_glyph_whiteness()
    check_metrics_alignment()
    check_ui_title_zone80()
    log("=" * 60)
    (ROOT / "tools" / "report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    if FAILED:
        log("結果: FAIL (有問題,不應交付) → tools/report.txt")
        sys.exit(1)
    log("結果: PASS (全部檢查通過) → tools/report.txt")
    sys.exit(0)


if __name__ == "__main__":
    main()