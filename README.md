# CK2 繁體中文漢化 (ck2-zh-tw)

Crusader Kings II 3.3.x 繁體中文漢化(臺灣常用語調)。
基於 52 漢化組的簡體版本以 OpenCC s2twp 轉換,保留遊戲 escape 格式。

## 內容
- `ck2_chinese/` 主體漢化(含顯示用字型 `.fnt/.dds`)
- `ck2_chinese_sup/` 補充(文化/事件/人物/歷史)
- `chinese_gui_fix_3/` UI 介面修正
- `tools/` 轉換腳本、字型重建工具與術語表

## 分支
- `main`: 最新遊戲版本(目前 3.3.x)
- `simplified-src`: 原始簡體源
- 舊遊戲版本會以 `archive/<版本>` 分支保留

## 安裝(手動,Documents mod 目錄)
```
C:\Users\<你>\Documents\Paradox Interactive\Crusader Kings II\mod\
├── ck2_chinese_tw.mod       ← descriptor(資料夾內同名檔,ASCII 無 BOM)
├── ck2_chinese_tw\          ← 解壓內容(localisation、gfx/fonts…)
├── ck2_chinese_sup.mod / ck2_chinese_sup\
└── chinese_gui_fix_3.mod / chinese_gui_fix_3\
```
啟動器內啟用三個 mod 即可。GitHub Actions 的 zip 內含同名資料夾,解壓即用。

## 注意事項
- 語法檔(`.txt`)以位元組級等長替換轉換,escape 結構與簡體源完全一致
- localisation(`.csv`)以 OpenCC 片語級轉換(克羅地亞→克羅埃西亞 等臺灣慣用音譯)
- 字型以微軟正黑體重建,補上簡體字形集缺少的繁體字形

## 重新轉換
```bash
pip install opencc-python-reimplemented
git checkout simplified-src -- ck2_chinese ck2_chinese_sup chinese_gui_fix_3
python3 tools/convert_tw.py          # 產出繁體(放在 main)
python3 tools/convert_tw.py --dry-run  # 預覽統計
```
