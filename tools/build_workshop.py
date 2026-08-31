#!/usr/bin/env python3
"""產生 Steam Workshop 上傳版:workshop/ 目錄(6 個獨立 item)。

每個版本(完整版/基本版)各 3 件套,分別上傳:
  1. CK2 Traditional Chinese (Full/Basic)              ← ck2_chinese
  2. CK2 Traditional Chinese Supplemental (Full/Basic) ← ck2_chinese_sup
  3. CK2 Traditional Chinese Interface Fix (Full/Basic)← chinese_gui_fix_3

Workshop 上傳須 path= 格式、夾內禁有 descriptor.mod(官方 wiki);
dependencies 欄位不使用(workshop 下載會剝除引號,wiki 警告)。
每個 item 各附專屬 description_*.txt(含安裝步驟與互貼連結佔位)。
"""
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "workshop"
SRC_DIRS = ("ck2_chinese", "ck2_chinese_sup", "chinese_gui_fix_3")

SLOT = "【上傳後填入:{which}】"


def _desc(title, body, extra):
    parts = [
        f"【{title}】",
        "",
        body.strip(),
        "",
        "■ 安裝方式(重要,請依序完成)",
        "步驟一:安裝漢化補丁 CK2dll(必需,否則無法正確顯示繁體字)",
        "  下載:https://github.com/AosakiReiya/CK2dll/releases/latest",
        "  解壓後將全部檔案放入遊戲資料夾 Crusader Kings II(保留 plugins 子資料夾結構)。",
        "  ※ 此補丁無法經 Workshop 自動安裝,須手動放置。",
        "步驟二:訂閱本漢化所需之三件套(見下方連結,缺一不可)",
        "步驟三:啟動器勾選三件套 → 開始遊戲",
        "",
        extra.strip(),
        "",
        "■ 版本區別(Full 與 Basic 兩系請勿混用或同時啟用)",
        "· 完整版(Full):繁體轉換 + 在地用語 + AI 語感潤飾,事件文字閱讀更道地",
        "· 基本版(Basic):僅繁體轉換 + 在地用語,不改寫原句",
        "",
        "■ 備註",
        "· 若曾手動安裝其他漢化版本,請先移除以免衝突",
        "· 問題回報與原始檔案:https://github.com/AosakiReiya/ck2-zh-tw",
    ]
    return "\n".join(parts) + "\n"


def description(item: str, edition: str) -> str:
    """item ∈ {main, sup, gui}; edition ∈ {full, basic}"""
    ed = "完整版(Full)" if edition == "full" else "基本版(Basic)"
    other_ed = "基本版(Basic)" if edition == "full" else "完整版(Full)"
    ed_tag = "Full" if edition == "full" else "Basic"
    names = {
        "main": f"CK2 Traditional Chinese ({ed_tag})",
        "sup": f"CK2 Traditional Chinese Supplemental ({ed_tag})",
        "gui": f"CK2 Traditional Chinese Interface Fix ({ed_tag})",
    }
    body = {
        "main": "Crusader Kings II 繁體中文漢化【主模組】。\n"
                "將遊戲簡體漢化轉換為繁體中文,並依繁體中文用語習慣調整(如:網路、訊息、軟體)。\n"
                "此為必需元件:包含全部介面文字、事件與人物地名的 localisation 檔與繁體字型。",
        "sup": "Crusader Kings II 繁體中文漢化【補充文本】。\n"
               "補充漢化文化、王朝、宗教、事件與歷史人物等文本,\n"
               "使遊戲內容完整呈現繁體中文。",
        "gui": "Crusader Kings II 繁體中文漢化【界面修復】。\n"
               "修正王朝名稱等界面元素於繁體中文下的顯示,使字體顯示更加完整。",
    }[item]

    bundle = "本漢化由三個 Workshop 項目組成,請全部訂閱(缺一不可):"
    lines = [bundle]
    for k in ("main", "sup", "gui"):
        if k == item:
            lines.append(f"  · {names[k]}:  ← 本 Mod")
        else:
            lines.append(f"  · {names[k]}: {SLOT.format(which=names[k])}")
    extra = "\n".join(lines)
    return _desc(names[item], body, extra)


def run(*a, **k):
    return subprocess.run(a, cwd=ROOT, check=True, **k)


def materialize(ref: str, tag: str) -> pathlib.Path:
    wt = ROOT / f".workshop-{tag}"
    if wt.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=ROOT, capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=ROOT)
    if r.returncode != 0:
        subprocess.run(["git", "fetch", "origin", ref], cwd=ROOT, capture_output=True)
    run("git", "worktree", "add", "-f", "--detach", str(wt), ref, capture_output=True)
    subprocess.run(["git", "-C", str(wt), "lfs", "pull"], cwd=ROOT, capture_output=True)
    return wt


def copy_src(base: pathlib.Path, src: str, dest: pathlib.Path):
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted((base / src).rglob("*")):
        if p.is_dir():
            continue
        if p.suffix == ".mod" or p.name in ("descriptor.mod",) or any(
                part in (".fonts_bak", "__pycache__") for part in p.parts):
            continue
        tgt = dest / p.relative_to(base / src)
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, tgt)
        n += 1
    return n


def check(dest: pathlib.Path, label: str, need_fonts: bool):
    bad = [p for p in dest.rglob("*.mod")]
    assert not bad, f"{label}: 夾內不得有 .mod/descriptor.mod: {bad}"
    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    if need_fonts:
        for f in ("gfx/fonts/zh-hans-16.dds", "gfx/fonts/zh-hans-map.dds",
                  "gfx/fonts/zh-hans-16.fnt", "localisation/HolyFury.csv"):
            assert (dest / f).exists(), f"{label}: 缺 {f}"
        assert (dest / "gfx/fonts/zh-hans-16.dds").read_bytes()[:4] == b"DDS ", \
            f"{label}: dds 非真檔(LFS pointer?)"
    assert total < 340 * 1024 * 1024, f"{label}: {total/1e6:.0f}MB 逼近 Workshop 上限"
    print(f"  ✓ {label}({total/1e6:.1f}MB)")


def mod_file(name: str, folder: str, tags="Language Localisation"):
    return (f'name="{name}"\npath="mod/{folder}"\n'
            f'tags={{\n\t{tags}\n}}\npicture="thumb.jpg"\n')


ITEMS = [
    # (folder, src-dir, name_full, name_basic, description key, tags)
    ("ck2_trad_tw",       "ck2_chinese",
     "CK2 Traditional Chinese (Full)", "CK2 Traditional Chinese (Basic)", "main", "Language Localisation"),
    ("ck2_trad_tw_sup",   "ck2_chinese_sup",
     "CK2 Traditional Chinese Supplemental (Full)", "CK2 Traditional Chinese Supplemental (Basic)", "sup", "Translation"),
    ("ck2_trad_tw_gui",   "chinese_gui_fix_3",
     "CK2 Traditional Chinese Interface Fix (Full)", "CK2 Traditional Chinese Interface Fix (Basic)", "gui", "Translation"),
]


def build(base: pathlib.Path, edition: str):
    """edition: 'full' (main 工作樹) 或 'basic'(各用獨立資料夾後綴)"""
    n = 0
    for folder, src, name_full, name_basic, desc_key, tags in ITEMS:
        fd = folder if edition == "full" else f"{folder}_basic"
        name = name_full if edition == "full" else name_basic
        cnt = copy_src(base, src, OUT / fd)
        (OUT / f"{fd}.mod").write_text(mod_file(name, fd, tags), encoding="utf-8")
        (OUT / f"description_{fd}.txt").write_text(
            description(desc_key, edition), encoding="utf-8")
        check(OUT / fd, f"{edition}:{fd}", need_fonts=(desc_key == "main"))
        n += cnt
    print(f"{edition}: {n} 檔")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    print("== Workshop 建置(6 個獨立 item)==")

    build(ROOT, "full")
    wb = materialize("origin/basic-zh", "basic")
    build(wb, "basic")
    for tag in ("basic",):
        p = ROOT / f".workshop-{tag}"
        if p.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(p)],
                           cwd=ROOT, capture_output=True)

    (OUT / "UPLOAD-README.txt").write_text("""== Steam Workshop 上傳步驟(6 個 item,每個版本 3 件)

上傳順序(建議先主模組,再另兩件,最後回填互貼連結):
  完整版:ck2_trad_tw → ck2_trad_tw_sup → ck2_trad_tw_gui
  基本版:ck2_trad_tw_basic → ck2_trad_tw_basic_sup → ck2_trad_tw_basic_gui

1. 將對應「解壓資料夾 + 同名 .mod」複製到
   Documents\\Paradox Interactive\\Crusader Kings II\\mod\\
2. 開啟 Steam 雲端同步(上傳必要條件)
3. 啟動遊戲 → 啟動器勾選 → Content → Manage → Publish(遊戲自動轉 archive 上傳)
4. 上傳後於 Steam 客戶端該 Mod 頁面:貼上對應 description_*.txt 全文 + 截圖 → 設為 Public
5. 取得各 item 的 Workshop 連結後,將 description_*.txt 中「【上傳後填入:XXX】」
   替換為真實連結(三件套互貼),再於 Workshop 頁面更新說明即可

注意:
- 上傳前確認解壓夾內【無】descriptor.mod(有則刪除,否則遊戲會崩)
- 更新流程:取消訂閱 → 移除舊 zip/.mod → 放新解壓夾(path= 格式)→ 遊戲內 Manage → Update → 重新設 Public
- CK2dll 補丁不經 Workshop,description 已附 GitHub 連結
""", encoding="utf-8")
    print("\n== 產出 ==")
    for p in sorted(OUT.iterdir()):
        print("  ", p.name)


if __name__ == "__main__":
    main()