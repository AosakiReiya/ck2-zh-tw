#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_release.py — 一鍵建置 + 自動驗證 + 打包 + 部署。

流程:
  1. convert_tw.py     簡體→繁體 byte 級 1:1(語意保留 escape 編碼)
  2. rebuild_fonts.py  六個字型重建(以完整文本為 corpus)
  3. verify_report.py  自動檢測(字形覆蓋 100% / 結構 / 語意守恆 / 漏譯 / KEY / 字型自檢)
     任一 FAIL → 中止,不打包
  4. 打包三份 zip + 複製 folder mod 到 Documents/OneDrive mod 目錄
  5. 輸出 report.txt 摘要
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import zipfile
import os

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

MODS = [  # (repo 目錄, mod 名)
    ("ck2_chinese", "ck2_chinese_tw"),
    ("ck2_chinese_sup", "ck2_chinese_sup"),
    ("chinese_gui_fix_3", "chinese_gui_fix_3"),
]
DEPLOY_DIRS = [
    pathlib.Path(r"/mnt/c/Users/samso/Documents/Paradox Interactive/Crusader Kings II/mod"),
    pathlib.Path(r"/mnt/c/Users/samso/OneDrive/文件/Paradox Interactive/Crusader Kings II/mod"),
]


def run(cmd, cwd=ROOT):
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        print(f"!! 指令失敗: {cmd}")
        sys.exit(r.returncode)


def zipdir(src: pathlib.Path, dst: pathlib.Path):
    """打包 mod 資料夾為 zip(排斥 .mod 描述檔與任何暫存/備份件)。"""
    skip_any = (".fonts_bak", "__pycache__", ".bak", "descriptor.mod")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in skip_any]
            for fn in files:
                if fn in skip_any or any(s in fn for s in (".bak",)):
                    continue
                p = os.path.join(root, fn)
                info = zipfile.ZipInfo(os.path.relpath(p, src).replace(os.sep, "/"),
                                       (2024, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, open(p, "rb").read())


def deploy():
    for base in DEPLOY_DIRS:
        base.mkdir(parents=True, exist_ok=True)
        for src_name, mod_name in MODS:
            fdir = base / mod_name
            if fdir.exists():
                shutil.rmtree(fdir)
            shutil.copytree(ROOT / src_name, fdir)
            for junk in ("__pycache__",):
                p = fdir / junk
                if p.exists():
                    shutil.rmtree(p)
            # 對應 zip
            out = ROOT / f"{mod_name}.zip"
            zipdir(ROOT / src_name, out)
            shutil.copy(out, base / out.name)
        print("已部署:", base)


def main():
    print("=" * 60)
    print("CK2 繁體漢化 一鍵建置(make_release)")
    print("=" * 60)
    if "--skip-convert" not in sys.argv:
        print("\n[1/4] 轉換 localisation/語法檔 ...")
        run([sys.executable, "-B", "tools/convert_tw.py"])
    else:
        print("\n[1/4] 跳過轉換(--skip-convert)")
    expected_fnt = ROOT / "ck2_chinese/gfx/fonts/zh-hans-16.fnt"
    if "--skip-fonts" in sys.argv:
        print("[2/4] 跳過字型重建(--skip-fonts)")
    else:
        print("\n[2/4] 重建字型(以完整文本 corpus)...")
        run([sys.executable, "-B", "tools/rebuild_fonts.py"])
    print("\n[3/4] 自動驗證 ...")
    run([sys.executable, "-B", "tools/verify_report.py"])
    print("\n[4/4] 打包 + 部署 ...")
    deploy()
    print("\n完成。報告: tools/report.txt")
    print("請使用者啟動遊戲只勾主 mod 驗證;確認後再全勾。")


if __name__ == "__main__":
    main()