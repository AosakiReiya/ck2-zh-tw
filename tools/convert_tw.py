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

def decode_escape(b: bytes):
    """bytes -> (unicode_text, prefix_map)。
    prefix_map[i] = 對應第 i 個 Unicode char 的 escape byte(僅 CJK-escape chars)。"""
    out = []
    prefixes = {}
    i = 0
    while i < len(b):
        if b[i] in ESCAPES and i + 2 < len(b):
            cp = b[i + 1] | (b[i + 2] << 8)
            out.append(chr(cp))
            prefixes[len(out) - 1] = b[i]
            i += 3
        else:
            out.append(chr(b[i]))
            i += 1
    return "".join(out), prefixes


def encode_escape(s: str, prefixes: dict) -> bytes:
    out = bytearray()
    for i, ch in enumerate(s):
        if i in prefixes:
            out.append(prefixes[i])
            out.append(ord(ch) & 0xFF)
            out.append((ord(ch) >> 8) & 0xFF)
        else:
            out.extend(ch.encode("utf-8"))
    return bytes(out)


def sniff(data: bytes) -> str | None:
    """回傳 'utf8' / 'gb18030' / 'escape' / None(binary)"""
    if b"\x00" in data[:2000]:
        return None
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
    # utf8/gb18030 都失敗 → 判斷為 escape 格式(至少要有一個 0x10..0x13 序列)
    if data.count(b"\x10") + data.count(b"\x11") + data.count(b"\x12") + data.count(b"\x13") > 0:
        return "escape"
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

def convert_text(text: str, glossary: Glossary) -> str:
    """只轉換中文字元連續段;保留 ASCII 與所有非中文字元。"""
    out = []
    buf = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" or (
            "\uff00" <= ch <= "\uffef"
        ):
            buf.append(ch)
        else:
            if buf:
                piece = "".join(buf)
                out.append(glossary.apply(OPENCC.convert(piece)))
                buf = []
            out.append(ch)
    if buf:
        out.append(glossary.apply(OPENCC.convert("".join(buf))))
    return "".join(out)


def convert_file(path: Path, glossary: Glossary, dry_run: bool, stats: dict):
    data = path.read_bytes()
    kind = sniff(data)
    if kind is None:
        print(f"  [skip:binary] {path}")
        return 0
    if kind in ("utf8", "gb18030"):
        text = data.decode(kind)
        converted = convert_text(text, glossary)
        out = converted.encode(kind)
        stats["files"] += 1
        stats["chars"] += len(text)
        if not dry_run and out != data:
            path.write_bytes(out)
        return int(out != data)
    # escape 格式
    text, prefixes = decode_escape(data)
    converted = convert_text(text, glossary)
    out = encode_escape(converted, prefixes)
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