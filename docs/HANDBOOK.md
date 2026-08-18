# CK2 繁體漢化 — 技術調查與修復紀錄

本文記錄整個「繁體字型與渲染相容」排查過程中確認的**根因與閘門**,供後續維護者查閱,
避免重蹈覆轍。所有結論均來自實測(遊戲載入 / 崩潰 / 渲染對照)。

---

## 1. 崩潰 / 掛死(全部已修 + 自動閘門)

### 1.1 字形數 >8192 → 載入越界崩潰(CK2 自製 BMF 解析器定長緩衝)
- 52 原廠六檔字形數全部 ≤7461;我們第一版 = 8919 → 只要超過 ~8192 就載入即崩
- **閘門**:`rebuild_fonts.py` 鎖 `MAX_GLYPH=7000`;`verify_report.py` A 檢查對
  `≥8192` 直接 FAIL

### 1.2 fnt 的多餘行(page / chars count / kernings)→ 解析器錯亂
- 52 原廠 fnt 只含 `info` / `common` / `char` 三種行(尾註 `### ... ###` 無害)
- 我們原輸出含標準 BMF 的 `page`、`chars count=`、`kernings count=` → CK2 自製
  解析器錯亂 → DX9 `gfx_dx9.cpp:1490 Error create vertices`(error.log 4022 次)→ 無字 + 閃退
- **閘門**:`verify_report.py` F 檢查:出現非 `info/common/char` 行 → FAIL
- 附註:char 行 token 必須與原廠一致(`id x y width height xoffset yoffset xadvance page`)

### 1.3 零尺寸字形(width/height=0)→ vertex 建立失敗
- 我們以 PIL `getbbox` 產出的空格 = 0×0(原廠 space = 3×1)→ 每次渲染空格
  建 quad 失敗
- **閘門**:F 檢查 `width=0 或 height=0` → FAIL;輸出端 `max(1, …)` 強制 ≥1

### 1.4 控制字元字形(9/10/13)
- 我們曾輸出 TAB/CR/LF 字形;52 原廠完全沒有(渲染器自然跳過)→ 移除
- **閘門**:F 檢查 `id ∈ {9,10,13}` → FAIL

### 1.5 DDS header 逐欄位必須與原廠同構
- `linearSize = w×h`(DXT3/DXT5 為 8bpp;我們曾宣告半張 → 載入卡死)
- decorative/map = **DXT5**、`flags=0xA1007`、`depth=1`、`mip=1`
- 文字四款 = **DXT3**、`flags=0x81007`、`depth=1`、`mip=0`
- 尺寸上限:decorative 4096×7000(優先)/4096×8192、map 4096×8192;
  **絕不可回到 8192×8192**(52 從未使用,無相容先例)
- **閘門**:F 檢查逐欄 SPEC 比對

### 1.6 RGB565 的 G 通道必須 `>>2`(6-bit)
- 誤用 `>>3` → 白色文字變成 (248,124,248) 紫色
- **閘門**:G 檢查「字形像素白度 ≥200」,紫(低 G)即 FAIL

### 1.7 字形度量(y/x offset)以 52 原廠為基準自適應校準
- PIL 的 `getbbox` 對字形在方格內位置的定義與原廠 BMGlyph 度量差 ~3px → 文字下移、
  小號渲染盒內被裁成「殘形」(看起來像亂碼字符)
- 修法:`yoffset = bbox[1]-1-3+Δ`、`xoffset = bbox[0]-1+Δ`,Δ = 與原廠共同字形中位差
  (實測:文字款 ±1px、decorative/map −11、map 另 +2)
- **閘門**:H 檢查 y/x 中位差 ≤1,超過即 FAIL

---

## 2. 「視窗 chrome 文字(如設置 tab 標題)會變成 ó」— 特殊雷區

### 2.1 現象
設置視窗「音頻」tab 標題(KEY `SM_AUDIO`,值「聲音」)顯示成單一拉丁字元
**ó(U+00F3)**;簡體原樣「声音」正常;「遊戲/圖像」等其他 tab 正常。

### 2.2 位元組層根因(實測歸納)
- `ó = U+00F3 = 243` = **「音」LE 低字節 `F3` 單獨被讀、高位補 0x00 的結果**
- 觸發 byte 是「聲」的 LE 碼 **`72 80`** 中的 `0x80`(=bit7 旗標區):
  該 chrome 文字解碼器(遊戲內建,不走 JPS 插件)把 `U+8000-U+80FF` 判為
  「旗標/換模式」字元 → 後續位元組 +1 錯位 → 值尾的「音」(F3 97)被拆開、落單的
  `F3` 補零為 `U+00F3` → 整行只剩「ó」可顯示
- 遊戲內其他文字走插件(JPS)escape 解碼 → 同樣「聲」(0x8072)完全正常
- 簡體「声(F0 58)」的 bit7 模式不觸發該分支 → 正常(實測事實)

### 2.3 影響範圍(完整調查)
- 全文 corpus 中共 **62 個字**落在 `U+8000-U+80FF`(能/者/聖/聽/老/耶/職/考/
  肯/耳/背/聚/耀/聞/聯/育/胡/肉/聊/耐/肖…),總出現 25082 次
- 但受害**只限「視窗 chrome 文字」路徑**(不經插件);62 字在遊戲內其他文字全部正常
- 唯一命中 chrome 的 KEY 即 `SM_AUDIO(聲音)`;後續掃描另抓到
  `FE_JOIN_INTERNET_GAME(聯)`、`FE_YOUNG_RULER(者)`

### 2.4 對策
| KEY | 原值 | 新值(皆繁體) | 原因 |
|---|---|---|---|
| SM_AUDIO | 聲音 | 音效 | 聲=U+8072;音/效皆安全 |
| FE_JOIN_INTERNET_GAME | 加入互聯網遊戲 | 多人遊戲 | 聯=U+806F |
| FE_YOUNG_RULER | 統治者年幼 | 幼主在位 | 者=U+8005 |

換詞注意:
- **不可用「線上」**(「上」的 payload 低字節 0x0A = LF 會斷行;CRITICAL 規則)
- payload 低字節不得為 {0x00, 0x0A, 0x0D};否則換 0x11(shift −0x0F)或換詞
- **閘門**:`verify_report.py` I 檢查:`SM_*`/`FE_*` 標題(值≤8字)含 0x80xx → FAIL
- 換詞行在 B 檢查有 REWORD 豁免(只驗 escape 型別合法),並記錄於 `check_structure` 註解

### 2.5 驗證狀態
- 「音效」版已部署;待最終遊戲內確認(音量 tab 顯示「音效」)

---

## 3. 其他交付規範(勿再改變)

- **zip 載入格式**:mod 目錄放 `xxx.zip` + 根 `.mod`(內容
  `archive="mod/xxx.zip"`,**不可用 `path=`** → 會資源 0 變全英文);
  zip 第一層直接是 `localisation/`、`gfx/`、`interface/`…,並含 `descriptor.mod`
- **字型無用於換字**:拼音/度量全部以 52 原廠為金標準;字體 = 思源宋 TC
  (`SourceHanSerifTC-Regular/Bold.otf`,位於
  `E:\Projects\_GameTranslate\OTF\TraditionalChinese`)
- 六檢查(@make_release):字形覆蓋(含字形數閘)、結構、prefix 語意、簡體殘留、
  KEY、字型規格、白度、度量校準、chrome 0x80xx — 任一 FAIL 不產包
- 打包排除任何 `.bak`/`__pycache__`/`.fonts_bak`(曾因備份夾混入 zip 造成舊字型覆蓋)

## 4. 待辦(記於 todo.md)
- 台灣用語 LLM 批次校訂(網路/訊息等,localhost:1234)
- 三 mod 全開(jps sup + gui fix)於最終版複測