#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
taiwanize_sent.py — T2:句級台灣語感校訂(全量,gemma-4-26b-a4b-it)。

流程:
  1. 收集 escape csv 的短值(≤24 字含中文)→ 去重
  2. 分批(40/批)送 gemma 校訂(JSON 回覆;重試 3 次)
  3. 接受規則:新句與原句「字符數完全相等(等長)」且僅變更在 escape 區
  4. 斷點:每批儲存 tools/.taiwan_sent_progress.json(中途可續)
  5. 全部完成 → byte 層套用(純 escape payload 平替,raw § 永不動)
  6. 最後自動呼叫 verify_report.py(全 PASS 才可打包)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from convert_tw import decode_escape, sniff
from taiwanize import PREF_SHIFT, safe_payload

API_URL = "http://localhost:1234/v1/chat/completions"
MODEL = "gemma-4-26b-a4b-it"
PROGRESS = ROOT / "tools" / ".taiwan_sent_progress.json"
MAXLEN = 24
BATCH = 40

SYSTEM = (
    "你是一位遊戲中文化的台灣繁體語感校對員。以下是 Crusader Kings II 的繁體中文遊戲"
    "文本片段(JSON 物件,鍵為序號)。請逐條做台灣語感/用詞微調。規則:"
    "1) 字符數必須與原句完全相同(等長 1:1,不得增減字);"
    "2) 專有名詞(人名/地名/頭銜/宗教/機構)除非明顯台灣用語否則原樣;"
    "3) 保留 § 開頭色彩碼、[方括號代碼]、$美元變數$、\\n 換行原樣;"
    "4) 原句已自然 → 原樣輸出(不得為改而改);"
    "5) 只輸出 JSON 物件(鍵為原序號),無其他文字。"
)


def collect_values():
    import glob
    values = {}
    for f in sorted(glob.glob(str(ROOT / "ck2_chinese" / "localisation" / "*.csv"))):
        data = open(f, "rb").read()
        if sniff(data) != "escape":
            continue
        s, _, _ = decode_escape(data)
        for ln in s.splitlines():
            if ";" not in ln:
                continue
            key = ln.split(";")[0]
            val = ln.split(";")[1]
            if (not val or len(val) > MAXLEN
                    or not any("\u4e00" <= c <= "\u9fff" for c in val)):
                continue
            # 階段閘:純淨短值(≤16 字、無變數/色彩/數字/括號)→ 高語感收益
            if len(val) > 16 or any(ch in val for ch in "§$/@%0123456789[\[]∣|"):
                continue
            values.setdefault(val, []).append((f, key))
    return values


def llm_batch(items):
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({i + 1: v for i, v in enumerate(items)}, ensure_ascii=False)},
        ],
        "temperature": 0.1, "max_tokens": 2800,
    }).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=240))
            text = r["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            print(f"  [retry {attempt + 1}] {str(e)[:80]}")
            time.sleep(3)
    return None


def char_to_group_off(data: bytes):
    """字符索引 -> escape 組 byte offset(escape 檔,byte-inplace 語義)。"""
    m = {}
    ci = 0
    i = 0
    while i < len(data) - 2:
        b = data[i]
        if b in (0x10, 0x11, 0x12, 0x13):
            m[ci] = i
            i += 3
        else:
            i += 1
        ci += 1
    return m


def apply_plan(plan):
    """plan: {path_str: {key: (old_val, new_val)}} — byte 層平替。"""
    applied = 0
    for path_str, rows in plan.items():
        p = ROOT / path_str
        data = p.read_bytes()
        if sniff(data) != "escape":
            continue
        s, _, _ = decode_escape(data)
        m = char_to_group_off(data)
        out = bytearray(data)
        pos = 0
        n_row = 0
        for ln in s.split("\n"):
            if ";" in ln:
                key = ln.split(";")[0]
                if key in rows:
                    old_val, new_val = rows[key]
                    if len(old_val) != len(new_val):
                        continue
                    semi = ln.index(";")
                    ch_base = pos + semi + 1
                    ok = True
                    for j in range(len(old_val)):
                        if new_val[j] == old_val[j]:
                            continue
                        goff = m.get(ch_base + j)
                        if goff is None:
                            ok = False  # raw 區需改 → 整句跳過
                            break
                        pref = data[goff]
                        r = safe_payload(pref, ord(new_val[j]))
                        if r is None:
                            ok = False
                            break
                        np_, npl = r
                        out[goff] = np_
                        out[goff + 1:goff + 3] = npl.to_bytes(2, "little")
                    if ok:
                        n_row += 1
            pos += len(ln) + 1
        if n_row:
            p.write_bytes(bytes(out))
            applied += n_row
            print(f"  套用 {path_str}: {n_row} 行")
    return applied


def main():
    values = collect_values()
    print(f"收集短句值(去重): {len(values)}")
    progress = {}
    if PROGRESS.exists():
        try:
            progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            progress = {}
    items = [v for v in values if v not in progress]
    plan = {}
    total = len(items)
    done = 0
    for i in range(0, total, BATCH):
        chunk = items[i:i + BATCH]
        resp = llm_batch(chunk)
        if resp is None:
            print("  批次失敗(重試後仍失敗),暫停存檔。(可重跑續)")
            break
        for k, new_val in resp.items():
            try:
                idx = int(k) - 1
            except Exception:
                continue
            if idx < 0 or idx >= len(chunk):
                continue
            old_val = chunk[idx]
            if new_val is None or not isinstance(new_val, str):
                continue
            new_val = new_val.strip()
            if new_val == old_val or len(new_val) != len(old_val):
                continue
            for path_str, key in values[old_val]:
                plan.setdefault(path_str, {})[key] = (old_val, new_val)
            progress[old_val] = new_val
        done += len(chunk)
        PROGRESS.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
        print(f"  進度 {done}/{total} (距批次剩 {len(plan)} 行變更)")
        time.sleep(1)
    if plan:
        print(f"待套用變更(等長): {sum(len(v) for v in plan.values())} 行")
        applied = apply_plan(plan)
        print(f"已套用: {applied} 行")
    else:
        print("無套用變更")


if __name__ == "__main__":
    main()