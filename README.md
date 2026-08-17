# CK2 繁體中文漢化 (ck2-zh-tw)

Crusader Kings II 3.3.x 繁體中文漢化(臺灣常用語調)。
基於 52 漢化組的簡體版本以 OpenCC s2twp + 術語表轉換,保留遊戲 escape 格式。

## 內容
- `ck2_chinese/` 主體漢化(含顯示用 zh-hans 字型 `.fnt/.dds`)
- `ck2_chinese_sup/` 補充(文化/事件/人物/歷史)
- `chinese_gui_fix_3/` UI 介面修正
- `tools/` 轉換腳本與術語表

## 分支
- `main`: 最新遊戲版本(目前 3.3.x)
- `simplified-src`: 原始簡體源
- 舊遊戲版本會以 `archive/<版本>` 分支保留

## 重新轉換
```bash
pip install opencc-python-reimplemented
git checkout simplified-src -- ck2_chinese ck2_chinese_sup chinese_gui_fix_3
python3 tools/convert_tw.py          # 產出繁體(放在 main)
python3 tools/convert_tw.py --dry-run  # 預覽統計
```
