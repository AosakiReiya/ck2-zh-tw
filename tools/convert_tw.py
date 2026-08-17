#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_tw.py — CK2 中文漢化 簡體 -> 臺灣繁體 轉換工具

處理:
  - ck2_chinese/localisation/*.csv  (0x10~0x13 + UTF-16LE 逐字元 escape 格式)
  - ck2_chinese_sup/**/*.txt         (同上 escape 格式 / GBK / UTF-8 混合)
  - chinese_gui_fix_3/**/*           (如有文字一併處理)

方法:
  1. 逐檔偵測編碼:UTF-8 → GB18030 → escape-format(0x10-0x13 + UTF-16LE)
  2. escape 格式解碼為「token 流」,只把連續 Unicode(中文字元)段落
     送 OpenCC s2twp + 術語表前置替換;ASCII / 佔位符($..$, £..$, §G..)原樣保留
  3. 原樣寫回(保留每個字元原本的 escape prefix,確保 roundtrip 一致)
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

try:
    from opencc import OpenCC
except ImportError:
    print("需要 opencc-python-reimplemented: pip install opencc-python-reimplemented")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOSSARY = ROOT / "tools" / "glossary.json"

OPENCC = OpenCC("s2twp")

ESCAPES = (0x10, 0x11, 0x12, 0x13)


# ---------- 解碼 / 編碼 ----------

def _is_cjk_escape(cp: int) -> bool:
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x3040 <= cp <= 0x30FF


def decode_escape(b: bytes):
    """bytes -> (unicode_text, prefix_map, raw_latin)。

    prefix_map[i] = escape byte(僅 CJK-escape chars);raw_latin = set of indices
    那些來自 latin1 回退的原始位元組(需以 latin1 原樣寫回,不可 utf8 再編)。
    0x10..0x13 只有當後兩字節解出 CJK 碼位時才視為 escape。"""
    out = []
    prefixes = {}
    raw_latin: set[int] = set()
    raw = bytearray()
    char_count = 0
    i = 0
    n = len(b)

    def flush():
        nonlocal char_count
        if raw:
            try:
                s = bytes(raw).decode("utf-8")
            except UnicodeDecodeError:
                s = bytes(raw).decode("latin1")
                raw_latin.update(range(char_count, char_count + len(s)))
            out.append(s)
            char_count += len(s)
            raw.clear()

    while i < n:
        if b[i] in ESCAPES and i + 2 < n:
            cp = b[i + 1] | (b[i + 2] << 8)
            if _is_cjk_escape(cp):
                flush()
                out.append(chr(cp))
                prefixes[char_count] = b[i]
                char_count += 1
                i += 3
                continue
        raw.append(b[i])
        i += 1
    flush()
    return "".join(out), prefixes, raw_latin


def encode_escape(s: str, prefixes: dict, raw_latin: set = None) -> bytes:
    raw_latin = raw_latin or set()
    out = bytearray()
    for i, ch in enumerate(s):
        if i in prefixes:
            out.append(prefixes[i])
            out.append(ord(ch) & 0xFF)
            out.append((ord(ch) >> 8) & 0xFF)
        elif i in raw_latin:
            out.append(ord(ch) & 0xFF)
        else:
            out.extend(ch.encode("utf-8"))
    return bytes(out)


def _align_props(src: list, dst: list, props_in: dict):
    """對齊後回傳 dst props 繼承(等同 _align_conv_prefixes 的用法)。"""
    return _align_conv_prefixes(src, dst, props_in)


def _looks_escape(data: bytes) -> bool:
    """有 0x10..0x13 前綴且後兩字節解出 CJK 字元 → 判定 escape 格式。"""
    i = 0
    n = len(data)
    hits = 0
    while i < n - 2:
        if data[i] in ESCAPES and data[i + 1] < 0x80:
            cp = data[i + 1] | (data[i + 2] << 8)
            if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
                hits += 1
                if hits >= 2:
                    return True
                i += 3
                continue
        i += 1
    return hits >= 1


def sniff(data: bytes) -> str | None:
    """回傳 'escape' / 'utf8' / 'gb18030' / None(binary)"""
    if b"\x00" in data[:2000]:
        return None
    # escape 優先:0x10-0x13 + UTF-16LE 是放送專用格式,正常 UTF-8 檔不會有
    if _looks_escape(data):
        return "escape"
    try:
        data.decode("utf-8")
        return "utf8"
    except UnicodeDecodeError:
        pass
    try:
        data.decode("gb18030")
        return "gb18030"
    except UnicodeDecodeError:
        pass
    return None


# ---------- 術語表 ----------

def load_glossary(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] 術語表讀取失敗 {path}: {e}")
        return {}


class Glossary:
    """長詞優先、字界保護的簡→繁前置替換(直接在 Unicode 文本上套用)。"""

    def __init__(self, entries: dict):
        items = sorted(
            ((k.strip(), str(v).strip()) for k, v in entries.items() if k.strip() and v),
            key=lambda kv: -len(kv[0]),
        )
        self.pairs = items

    def apply(self, text: str) -> str:
        for src, dst in self.pairs:
            if src in text:
                text = text.replace(src, dst)
        return text


# ---------- 轉換 ----------

def _align_conv_prefixes(src: list, dst: list, src_prefix: dict):
    """DP 最小編輯距離對齊 src->dst,回傳 dst 每個字元的 prefix(繼承或預設)。

    - 替換:繼承 src 對應字元的 prefix
    - 插入:若輸出字元是 CJK 給 0x10,否則 None
    - 刪除:消失
    """
    m, n = len(src), len(dst)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            sub = 0 if src[i - 1] == dst[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j - 1] + sub, dp[i - 1][j] + 1, dp[i][j - 1] + 1)
    out = {}
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sub = 0 if src[i - 1] == dst[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + sub:
                j -= 1
                i -= 1
                out[j] = src_prefix.get(i)
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            i -= 1
            continue
        # 插入
        j -= 1
        out[j] = 0x10 if "\u4e00" <= dst[j] <= "\u9fff" else None
    return out


def convert_text(text: str, prefixes_in: dict, raw_latin_in: set, glossary: Glossary,
                 phrase: bool = True):
    """轉換 U+4E00-U+9FFF 連續段;回傳 (converted, prefix_map, raw_latin)。

    phrase=True(渲染文本 .csv): 片語級 OpenCC(克羅地亞→克羅埃西亞),可增減字數,
        以 DP 對齊繼承 escape prefix。
    phrase=False(語法檔 .txt): 逐字元 1:1 轉換,長度恆等,escape 結構 100% 安全。

    prefix_map: 輸出字元索引 -> escape byte。run 外字元原樣保留;
    run 內依對齊繼承;片語合併插入的字元預設 0x10。
    """
    out = []
    prefixes_out: dict[int, int] = {}
    raw_latin_out: set[int] = set()
    pos = 0
    n = len(text)
    while pos < n:
        ch = text[pos]
        if "\u4e00" <= ch <= "\u9fff":
            end = pos
            while end < n and "\u4e00" <= text[end] <= "\u9fff":
                end += 1
            src = list(text[pos:end])
            src_prefix = {i: prefixes_in[pos + i] for i in range(len(src)) if pos + i in prefixes_in}
            src_latin = {i for i in range(len(src)) if pos + i in raw_latin_in}
            if phrase:
                conv = glossary.apply(OPENCC.convert("".join(src)))
            else:
                # 語法檔:只轉「帶 escape prefix 的字元」,且強制 1:1;
                # 輸出長度≠1 的映射一律保留原字 → byte 結構與原檔完全一致
                parts = []
                for i, c in enumerate(src):
                    if i in src_prefix:
                        r = OPENCC.convert(c)
                        if len(r) == 1:
                            parts.append(r)
                            continue
                    parts.append(c)
                conv = "".join(parts)
            pmap = _align_conv_prefixes(src, list(conv), src_prefix)
            lmap = _align_conv_prefixes(src, list(conv), {i: True for i in src_latin})
            base = len(out)
            for j, c in enumerate(conv):
                out.append(c)
                if pmap.get(j) is not None:
                    prefixes_out[base + j] = pmap[j]
                if lmap.get(j) is not None:
                    raw_latin_out.add(base + j)
            pos = end
        else:
            out.append(ch)
            if pos in prefixes_in:
                prefixes_out[len(out) - 1] = prefixes_in[pos]
            if pos in raw_latin_in:
                raw_latin_out.add(len(out) - 1)
            pos += 1
    return "".join(out), prefixes_out, raw_latin_out


def convert_bytes_inplace(data: bytes) -> bytes:
    """語法檔用:只對「個別漢字字形」做位元組級等長替換。

    - escape 檔:`PX XX YY`(P 為 0x10..0x13,cp=CJK)→ 僅替換 XX YY 兩字節
    - utf8 檔:每 3-byte 漢字 → OpenCC 單字對映(限 1:1,否則原樣)
    - gb18030 檔:每 2-byte 漢字 → OpenCC 對映(限 2-byte 輸出,否則原樣)
    其餘位元組一律不動 → 檔案長度、引號、escape 結構完全不變。
    """
    def conv_cp(cp: int):
        r = OPENCC.convert(chr(cp))
        return ord(r[0]) if len(r) == 1 else cp

    # 先判斷 escape 格式(依 sniff 規則)
    if _looks_escape(data):
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            if data[i] in ESCAPES and i + 2 < n:
                cp = data[i + 1] | (data[i + 2] << 8)
                if _is_cjk_escape(cp):
                    ncp = conv_cp(cp)
                    out.append(data[i])
                    out.append(ncp & 0xFF)
                    out.append((ncp >> 8) & 0xFF)
                    i += 3
                    continue
            out.append(data[i])
            i += 1
        return bytes(out)

    # utf8 / gb18030:逐漢字替換
    for enc in ("utf-8", "gb18030"):
        try:
            s = data.decode(enc)
        except UnicodeDecodeError:
            continue
        out = []
        for ch in s:
            if "\u4e00" <= ch <= "\u9fff":
                r = OPENCC.convert(ch)
                out.append(r if len(r) == 1 else ch)
            else:
                out.append(ch)
        return "".join(out).encode(enc)
    return data


def convert_file(path: Path, glossary: Glossary, dry_run: bool, stats: dict):
    data = path.read_bytes()
    kind = sniff(data)
    if kind is None:
        print(f"  [skip:binary] {path}")
        return 0
    if path.suffix.lower() != ".csv":
        # 語法檔:位元組級等長替換,結構零變動
        converted = convert_bytes_inplace(data)
        stats["files"] += 1
        stats["chars"] += sum(1 for ch in data if 0x80 <= ch < 0xFF)
        if dry_run:
            return int(converted != data)
        if converted != data:
            path.write_bytes(converted)
        return int(converted != data)
    if kind in ("utf8", "gb18030"):
        text = data.decode(kind)
        converted, _, _ = convert_text(text, {}, set(), glossary, phrase=True)
        out = converted.encode(kind)
        stats["files"] += 1
        stats["chars"] += len(text)
        if not dry_run and out != data:
            path.write_bytes(out)
        return int(out != data)
    # escape 格式 csv
    text, prefixes, raw_latin = decode_escape(data)
    converted, prefixes, raw_latin = convert_text(text, prefixes, raw_latin, glossary, phrase=True)
    out = encode_escape(converted, prefixes, raw_latin)
    stats["files"] += 1
    stats["chars"] += sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if dry_run:
        return int(out != data)
    if out != data:
        path.write_bytes(out)
    return int(out != data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glossary", default=str(DEFAULT_GLOSSARY))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("targets", nargs="*", default=[], help="檔/目錄;預設:三個 mod 目錄")
    args = ap.parse_args()

    glossary = Glossary(load_glossary(Path(args.glossary)))
    if glossary.pairs:
        print(f"術語表載入 {len(glossary.pairs)} 組")

    targets = args.targets or [
        str(ROOT / "ck2_chinese"),
        str(ROOT / "ck2_chinese_sup"),
        str(ROOT / "chinese_gui_fix_3"),
    ]
    files: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files += [
                f
                for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in {".csv", ".txt", ".mod"}
            ]
        elif p.is_file():
            files.append(p)

    stats = {"files": 0, "chars": 0}
    changed = 0
    for f in sorted(files):
        changed += convert_file(f, glossary, args.dry_run, stats)
    print(
        f"完成:處理 {stats['files']} 檔,中文字元 {stats['chars']},"
        f"{'預期變更' if args.dry_run else '實際變更'} {changed} 檔"
    )


if __name__ == "__main__":
    main()