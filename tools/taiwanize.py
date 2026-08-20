#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
taiwanize.py — 台灣用語本土化(等長安全替換 + 可選 LLM 句子校訂)。

安全鐵律:
1. 只在「escape 值區」做替換(文本層 → 原 prefix_map 重新編碼)
   → esc_pos 相同、non_esc_bytes 不變 → 結構(B)與 prefix 語意(C)檢查自然通過。
2. 只接受「字符數 1:1」的替換(等長):不等長 → 跳過並記錄(可走 REWORD 白名單)。
3. 替換後必須跑 verify_report.py 全檢查 PASS 才允許提交。

用法:
  python3 tools/taiwanize.py                 # 套用詞表(全部文本)
  python3 tools/taiwanize.py --dry-run       # 只統計不寫入
  python3 tools/taiwanize.py --limit 100     # 每檔最多處理行數(測試)
  python3 tools/taiwanize.py --dump-terms    # 列出詞表與命中統計
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from convert_tw import decode_escape, sniff

# escape 語意:顯示碼 = payload + shift;prefix 類別決定 payload 算法
PREF_SHIFT = {0x10: 0, 0x11: -0x0F, 0x12: 0x900, 0x13: 0x8F1}


def esc_groups(data: bytes):
    """掃描 escape 3-byte 組:「bytes 偏移 -> (prefix, display_cp)」。"""
    out = {}
    rl = False
    i = 0
    while i < len(data) - 2:
        b = data[i]
        if b in (0x10, 0x11, 0x12, 0x13):
            payload = int.from_bytes(data[i + 1:i + 3], "little")
            out[i] = (b, payload + PREF_SHIFT[b])
            i += 3
        else:
            i += 1
    return out


def refill_cp(prefix: int, display_cp: int) -> int:
    """依 prefix 類別算出 payload(顯示碼還原)。"""
    return display_cp - PREF_SHIFT[prefix]


def safe_payload(pref: int, target_cp: int):
    """目標字元在該大類下選一個 prefix,使 payload 低字節避開 CRITICAL
    (0x00/0x0A/0x0D,值內裸 0A 會被遊戲/檢查當換行)。失敗回傳 None。"""
    fam = (0x11, 0x10) if pref in (0x10, 0x11) else (0x13, 0x12)
    for p in (pref,) + fam:
        pl = target_cp - PREF_SHIFT[p]
        if 0 <= pl <= 0xFFFF and (pl & 0xFF) not in (0x00, 0x0A, 0x0D):
            return p, pl
    return None


def apply_byte_level(data: bytes, path, dry: bool):
    """byte 層詞表平替:只改 escape payload(3-byte 組),raw 區永不動。
    回傳替換數。"""
    if sniff(data) != "escape":
        return 0
    groups = esc_groups(data)
    positions = {}  # (byte_off) -> prefix
    for off, (pref, cp) in groups.items():
        positions[off] = (pref, cp)
    changed = 0
    out = bytearray(data)
    # 字元組匹配:詞(如 網絡)以「escape 組相鄰」形式搜尋 — 用「組對組」掃
    keys = sorted(positions)
    for ki, off in enumerate(keys[:-0]):
        pass
    # 直接:對每組比「詞首字」(組的 cp == 詞第一字),再檢查後續組 == 詞後續字
    for i in range(len(keys)):
        off = keys[i]
        pref, cp = positions[off]
        for src, dst in TERMS:
            if cp != ord(src[0]):
                continue
            if len(src) == 1:
                continue  # 單字替換不做(避免誤)
            ok = True
            for j in range(1, len(src)):
                if i + j >= len(keys):
                    ok = False
                    break
                off2 = keys[i + j]
                # 詞的第二字必須緊鄰(off2 為上組後 3 bytes)
                if off2 != off + 3 * j:
                    ok = False
                    break
                p2, c2 = positions[off2]
                if c2 != ord(src[j]):
                    ok = False
                    break
            if not ok:
                continue
            # 全部匹配 → 平替 payload(優先保持 prefix;CRITICAL 低字節 → 切同大類 prefix)
            plan = []
            ok_all = True
            for j in range(len(src)):
                o = off + 3 * j
                pj, _ = positions[o]
                r = safe_payload(pj, ord(dst[j]))
                if r is None:
                    ok_all = False
                    break
                plan.append((o, r))
            if ok_all:
                total = 0
                for o, (np_, npl) in plan:
                    out[o] = np_
                    out[o + 1:o + 3] = npl.to_bytes(2, "little")
                    total += 1
                if total == len(src):
                    changed += 1
    if changed and not dry:
        path.write_bytes(bytes(out))
    return changed

# ── 台灣用語詞表(等長:新詞字符數 == 原詞字符數)──
TERMS = [
    ("網絡", "網路"),
    ("信息", "訊息"),
    ("軟件", "軟體"),
    ("鼠標", "滑鼠"),
    ("存盤", "存檔"),
    ("設置", "設定"),
    ("菜單", "選單"),
    ("字符", "字元"),
    ("字符串", "字串"),
    ("光標", "游標"),
    ("通過", "透過"),
    ("視頻", "影片"),
    ("剪貼", "剪貼"),
    ("粘貼", "貼上"),
    ("剪切", "剪下"),
    ("加載", "載入"),
    ("重新加載", "重新載入"),
    ("服務器", "伺服器"),
    ("數據", "資料"),
    ("數據庫", "資料庫"),
    ("存儲", "儲存"),
    ("緩存", "快取"),
    ("緩衝", "緩衝"),
    ("默認", "預設"),
    ("配置", "設定"),
    ("文件", "檔案"),
    ("文件夾", "資料夾"),
    ("路徑", "路徑"),
    ("圖像", "圖像"),
    ("鼠標右鍵", "滑鼠右鍵"),
    ("鼠標左鍵", "滑鼠左鍵"),
    ("回車", "輸入"),
    ("空格", "空白"),
    ("界麵", "界面"),
    ("窗口", "視窗"),
    ("進程", "程序"),
    ("程序", "程式"),
    ("內存", "記憶體"),
    ("硬件", "硬體"),
    ("軟件", "軟體"),
    ("網上", "線上"),
    ("在上", "在上"),
]

# 去重並強制等長
_TERMS = []
_seen = set()
for src, dst in TERMS:
    if (src, dst) in _seen or src == dst:
        continue
    if len(src) != len(dst) or not all("\u4e00" <= c <= "\u9fff" for c in src):
        continue
    _seen.add((src, dst))
    _TERMS.append((src, dst))
TERMS = _TERMS


def apply_terms_to_text(text: str, esc_mask=None) -> tuple[str, int]:
    """等長詞表替換。esc_mask(每字符是否在 escape 區)非 None 時,
    整詞所有字符必須全在 escape 區才替換(raw utf8 字不改,結構零破壞)。"""
    out = []
    n = 0
    i = 0
    while i < len(text):
        hit = None
        for src, dst in TERMS:
            if text.startswith(src, i):
                if esc_mask is None or all(esc_mask.get(i + j, False) for j in range(len(src))):
                    hit = (src, dst)
                break
        if hit:
            out.append(hit[1])
            n += 1
            i += len(hit[0])
        else:
            out.append(text[i])
            i += 1
    return "".join(out), n


def process_file(path: Path, dry: bool, limit: int) -> int:
    """byte 層詞表平替(escape 檔);raw/utf8/gb18030 檔不改(結構安全)。"""
    data = path.read_bytes()
    if sniff(data) != "escape":
        return 0
    return apply_byte_level(data, path, dry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dump-terms", action="store_true")
    args = ap.parse_args()
    if args.dump_terms:
        for src, dst in TERMS:
            print(f"  {src} -> {dst}")
        print(f"共 {len(TERMS)} 條(全部等長)")
        return
    files = sorted(glob.glob(str(ROOT / "ck2_chinese" / "localisation" / "*.csv")))
    files += sorted(glob.glob(str(ROOT / "ck2_chinese_sup" / "**" / "*.txt"), recursive=True))
    total = 0
    for f in files:
        p = Path(f)
        n = process_file(p, args.dry_run, args.limit)
        if n:
            print(f"  {p.relative_to(ROOT)}: {n} 處替換")
        total += n
    print(f"{'預覽' if args.dry_run else '已套用'}: 共 {total} 處詞表替換")
    if not args.dry_run:
        print("下一步: python3 tools/verify_report.py 確認全 PASS 後再打包。")


if __name__ == "__main__":
    main()