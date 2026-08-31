#!/usr/bin/env python3
"""產生 Steam Workshop 上傳版:workshop/ 目錄。

每個版本一個「整併 mod」(三件套內容疊加,零衝突),各自獨立上傳:
  ck2_trad_tw(.mod + 解壓資料夾)   = CK2 Traditional Chinese (Full)
  ck2_trad_tw_basic                 = CK2 Traditional Chinese (Basic)
外加各版 description_*.txt(貼 Workshop 說明欄)與 UPLOAD-README.txt。
Workshop 上傳須 path= 格式、夾內禁有 descriptor.mod(官方 wiki)。
"""
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "workshop"
SRC_DIRS = ("ck2_chinese", "ck2_chinese_sup", "chinese_gui_fix_3")
SKIP_NAMES = {".mod", "descriptor.mod"}
SKIP_PARTS = (".fonts_bak", "__pycache__")

DESC_COMMON = """【{title}】

支援 CK2 3.3.5.1(64 位版)的繁體中文漢化。
將遊戲簡體漢化轉換為繁體中文,並依繁體中文用語習慣調整(如:網路、訊息、軟體)。

■ 安裝方式(重要,請依序完成)
步驟一:安裝漢化補丁 CK2dll(必需,否則無法正確顯示繁體字)
  下載:https://github.com/AosakiReiya/CK2dll/releases/latest
  解壓後將全部檔案放入遊戲資料夾 Crusader Kings II(保留 plugins 子資料夾結構)。
  ※ 此補丁無法經 Workshop 自動安裝,須手動放置。
步驟二:訂閱本 Mod
步驟三:啟動器勾選本 Mod → 開始遊戲

■ 版本區別(請擇一訂閱,勿同時啟用)
· {full_line}
· {basic_line}
  另一版本的 Workshop 頁:【上傳後填入:{other}】

■ 備註
· 本 Mod 已整併主漢化、補充文本與界面修復,訂閱一個即可完整運作
· 若曾手動安裝其他漢化版本,請先移除以免衝突
· 問題回報與原始檔案:https://github.com/AosakiReiya/ck2-zh-tw
"""


def desc(title: str, me_full: bool) -> str:
    full = "完整版(Full):繁體轉換 + 在地用語 + AI 語感潤飾,事件文字閱讀更道地"
    basic = "基本版(Basic):僅繁體轉換 + 在地用語,不改寫原句"
    if me_full:
        full += "  ← 本 Mod"
    else:
        basic += "  ← 本 Mod"
    return DESC_COMMON.format(
        title=title, full_line=full, basic_line=basic,
        other="基本版" if me_full else "完整版",
    )


def run(*a, cwd=None, **k):
    return subprocess.run(a, cwd=cwd, check=True, **k)


def materialize_basic() -> pathlib.Path:
    """回傳 basic-zh 的 LFS 已 smudge 工作樹路徑。"""
    wt = ROOT / ".workshop-basic"
    if wt.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=ROOT, capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "fetch", "origin", "basic-zh"], cwd=ROOT, capture_output=True)
    ref = "origin/basic-zh"
    if subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=ROOT).returncode != 0:
        ref = "basic-zh"
    run("git", "worktree", "add", "-f", "--detach", str(wt), ref, cwd=ROOT,
        capture_output=True)
    subprocess.run(["git", "-C", str(wt), "lfs", "pull"], cwd=ROOT, capture_output=True)
    return wt


def merge_tree(base: pathlib.Path, dest: pathlib.Path):
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in SRC_DIRS:
        src = base / d
        if not src.exists():
            raise SystemExit(f"缺少來源目錄: {src}")
        for p in sorted(src.rglob("*")):
            if p.is_dir():
                continue
            if p.name in SKIP_NAMES or any(part in SKIP_PARTS for part in p.parts):
                continue
            rp = p.relative_to(src)
            tgt = dest / rp
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, tgt)
            n += 1
    return n


def check(dest: pathlib.Path, label: str):
    mods = [p for p in dest.rglob("*") if p.suffix == ".mod"]
    assert not mods, f"{label}: 夾內不得有 .mod/descriptor.mod: {mods}"
    for f in ("gfx/fonts/zh-hans-16.dds", "gfx/fonts/zh-hans-map.dds",
              "gfx/fonts/zh-hans-16.fnt", "localisation/HolyFury.csv"):
        fp = dest / f
        assert fp.exists(), f"{label}: 缺 {f}"
    head = (dest / "gfx/fonts/zh-hans-16.dds").read_bytes()[:4]
    assert head == b"DDS ", f"{label}: dds 非真檔(LFS pointer?) {head!r}"
    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_dir() is False)
    assert total < 340 * 1024 * 1024, f"{label}: {total/1e6:.0f}MB 逼近 Workshop 上限"
    print(f"  ✓ {label}: 檢查通過({total/1e6:.1f}MB)")


def mod_file(name: str, folder: str) -> str:
    return (f'name="{name}"\npath="mod/{folder}"\n'
            f'tags={{\n\tLanguage Localisation\n}}\npicture="thumb.jpg"\n')


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    print("== Workshop 建置 ==")

    # 版本一:main 工作樹(必須已 smudge;若 dds 是 pointer 先 lfs pull)
    head = (ROOT / SRC_DIRS[0] / "gfx/fonts/zh-hans-16.dds")
    if head.exists() and head.read_bytes()[:4] != b"DDS ":
        subprocess.run(["git", "lfs", "pull"], cwd=ROOT, capture_output=True)
    n = merge_tree(ROOT, OUT / "ck2_trad_tw")
    print(f"main: 合併 {n} 檔")
    (OUT / "ck2_trad_tw.mod").write_text(
        mod_file("CK2 Traditional Chinese (Full)", "ck2_trad_tw"), encoding="utf-8")
    check(OUT / "ck2_trad_tw", "Full")
    (OUT / "description_ck2_trad_tw.txt").write_text(
        desc("CK2 Traditional Chinese (Full)", True), encoding="utf-8")

    # 版本二:basic-zh worktree
    wb = materialize_basic()
    n = merge_tree(wb, OUT / "ck2_trad_tw_basic")
    print(f"basic-zh: 合併 {n} 檔")
    (OUT / "ck2_trad_tw_basic.mod").write_text(
        mod_file("CK2 Traditional Chinese (Basic)", "ck2_trad_tw_basic"), encoding="utf-8")
    check(OUT / "ck2_trad_tw_basic", "Basic")
    (OUT / "description_ck2_trad_tw_basic.txt").write_text(
        desc("CK2 Traditional Chinese (Basic)", False), encoding="utf-8")

    (OUT / "UPLOAD-README.txt").write_text("""== Workshop 上傳步驟(每個版本各自上傳為獨立 item)

1. 將本目錄的 ck2_trad_tw(或 ck2_trad_tw_basic)與同名 .mod
   複製到 Documents\\Paradox Interactive\\Crusader Kings II\\mod\\
2. 確認 Steam 雲端同步已開啟(上傳必要條件)
3. 啟動遊戲 → 啟動器勾選該 mod → 主選單 Content → Manage → Publish
   (遊戲會自動把解壓資料夾打包成 archive 格式上傳)
4. 上傳完成後到 Steam 客戶端的 Mod 頁面:
   - 貼上對應的 description_*.txt 全文
   - 上傳截圖(建議含主選單/事件對話繁體畫面各一張)
   - Visibility 設為 Public
5. 兩版各自取得 Workshop 連結後,回填 description_*.txt 中的
   「【上傳後填入連結】」位置 → 於遊戲內 Manage → Update 重推
   (或僅更新 Workshop 頁面說明文字)

注意:
- 更新時請先移除 mod 目錄內舊的上傳殘留(clipboards/或 .mod 改回 path= 格式)
- 夾內不可有 descriptor.mod
- 「完整版」與「基本版」為兩個獨立 item,說明欄已互相標註連結位置
""", encoding="utf-8")

    run("git", "worktree", "remove", "--force", str(ROOT / ".workshop-basic"),
        cwd=ROOT, capture_output=True)
    print("\n== 產出 ==")
    for p in sorted(OUT.iterdir()):
        print("  ", p.name)
    print("上傳指南見 workshop/UPLOAD-README.txt")


if __name__ == "__main__":
    main()
