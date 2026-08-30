# CK2 繁體中文漢化 (zh-TW)

基於 52 漢化簡體的繁體中文化 — 台灣繁體、思源宋體、11 項自動檢查閘門防護。


## 版本對照與下載(最新發布)

📥 **[Releases 頁面](https://github.com/AosakiReiya/ck2-zh-tw/releases/latest)** — 每版提供「一鍵完整包 ×2」與單項元件(6 zip + 6 .mod)。

| 版本 | 主模組 | 內容 | 完整包 |
|---|---|---|---|
| 🏆 台灣化完整版 | `ck2_chinese_tw` | 繁體 + 本土詞表(網絡→網路、信息→訊息…)+ LLM 語感校訂 | `ck2_chinese_tw_full.zip` |
| 基本繁體版 | `ck2_chinese_basic` | 繁體 + 本土詞表,無 LLM(較保守原貌) | `ck2_chinese_basic_full.zip` |

兩版皆含:主模組 + `sup`(補充文本)+ `gui_fix`(界面修復),解壓完整包 → 全部拖進 mod 目錄 → 啟動器三勾全開即可。
**前置**:需 [CK2dll x64 補丁](https://github.com/AosakiReiya/CK2dll/releases/latest)(d3d9.dll + plugin64.dll)。

## 安裝

1. 下載三包(`ck2_chinese_tw.zip` / `ck2_chinese_sup.zip` / `chinese_gui_fix_3.zip`)與同名 `.mod`
2. 放入 `Documents\Paradox Interactive\Crusader Kings II\mod\`
   (本專案也內建部署工具,見下)
3. 啟動遊戲前確認:
   - 主模組 `ck2_chinese_tw` 必須啟用
   - `ck2_chinese_sup`(補充文本)、`chinese_gui_fix_3`(界面修復)建議全開
4. 進入設置畫面勾選三 mod → 啟動

> 若使用 zip 形式安裝,`.mod` 檔內為 `archive="mod/xxx.zip"`(官方格式);
> 不要改成 `path=`(會讀不到資源變成全英文)。


## 版本選擇(二選一)

| | 版本一:台灣化完整版 | 版本二:基本繁體版 |
|---|---|---|
| mod 名 | `ck2_chinese_tw` | `ck2_chinese_basic` |
| 內容 | 繁體 + 台灣本土化(T1 詞表 975 處 + LLM 語感 738 值) | 繁體 + 台灣本土化(T1 詞表 975 處)+ 8/18 修改字型,**無 LLM** |
| 字型 | 思源宋 Heavy(35 新字形版) | 思源宋 Heavy(8/18 穩定版) |
| 特點 | 完整語感校訂 | 乾淨樸素、不含 LLM 改寫 |
| 對應 commit | `079f472`(現部署) | `21a34ee` |

- 兩版**只能選一個**(localisation 檔案同名,同時啟用會互相覆蓋)。
- 分支模型:`main` = 版本一(台灣化完整版)/ `basic-zh` = 版本二(基本繁體版);
  GitHub Actions 依分支產包(`main` → `ck2_chinese_tw…`、`basic-zh` → `ck2_chinese_basic…`)。
- 兩版都需搭配 `ck2_chinese_sup`(補充文本)與 `chinese_gui_fix_3`(界面修復)。
- GitHub Release(tag `v*` 自動產出):`ck2_chinese_tw.zip` = 版本一、`ck2_chinese_basic.zip` = 版本二。
- 安裝方式相同(見上)。

## 一鍵建置與自動檢測

```bash
python3 tools/make_release.py
# 1. convert_tw.py   簡體→繁體 byte 級 1:1
# 2. rebuild_fonts.py 六字型重建(思源宋 TC;map 檔 DXT5)
# 3. verify_report.py 11 項自動檢查(任一 FAIL 不產包)
# 4. 打包 archive zip + .mod → 部署兩 mod 目錄
```

### 檢查清單(verify_report.py)
| # | 檢查 | 作用 |
|---|---|---|
| A | 字形覆蓋 100%(六字型)+ 字形數 <8192 | 防缺字 / 防解析器緩衝崩潰 |
| B | 結構與簡體源逐位元組等價(換詞行除外) | 防結構破壞 |
| C | prefix 語意守恆(0x10↔0x11、0x12↔0x13) | 防渲染語意錯亂 |
| D | 簡體專用字殘留 | 防漏譯/殘留 |
| E | KEY 完整性 | 防少 key |
| F | 字型檔規格(header/尺寸/格式/mip) | 防遊戲載入崩潰 |
| G | 字形白度(白字 RGB) | 防紫字/G 通道 bug |
| H | 度量校準(中心 ±1px) | 防文字偏移/裁切 |
| I | UI 標題 0x80xx 字元 | 防 chrome 渲染「ó」 |
| J | 結構字符串骨架與簡體源一致 | 防 §/$/[]/數字 被誤改 |
| K | CRITICAL payload(0x00/0A/0D 低字節) | 防換行/分隔字元破壞 |

### 台灣本土化工具
```bash
python3 tools/taiwanize.py --dry-run     # 詞表替換預覽(等長 1:1)
python3 tools/taiwanize.py               # 套用詞表(網路→網路、信息→訊息…)
python3 tools/taiwanize_sent.py          # LLM 句級語感校訂(gemma-4-26b-a4b-it,
                                         #  斷點續跑;僅接受等長變更)
```

## 目錄
- `tools/` 全部建置/驗證/台灣化工具
- `docs/HANDBOOK.md` 技術調查紀錄(崩潰根因、0x80xx ó 機制、交付規範)
- `ck2_chinese/` 主模組(文本 + 字型);`ck2_chinese_sup/`、`chinese_gui_fix_3/` 擴充
- `simplified-src` 分支 = 52 漢化簡體原版(比對金標準)