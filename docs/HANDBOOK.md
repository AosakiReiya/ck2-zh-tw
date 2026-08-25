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

## 2.6 台灣本土化(byte 層安全)與結構驗證閘門

- **原則**:僅允許「同長度 1:1 平替」與「escape 區內 CJK 替換」;`§/$/[`/數字等
  結構符號永不動(遊戲會做字串格式匹配,$AllyName$ 等變數被改壞 = 顯示裸碼)。
- **T1 詞表**(`tools/taiwanize.py`):網路/訊息/軟體/滑鼠/檔案/視窗/預設/選單/
  伺服器/儲存/字元/游標…969 詞處;`safe_payload` 避 CRITICAL bytes(0x00/0A/0D)。
- **T2 句級**(`tools/taiwanize_sent.py`):gemma-4-26b-a4b-it(localhost:1234)、
  每批 40、斷點 json 續跑;僅接受「等長」變更;純淨短值(≤16 字且無結構符號/數字)
  子集 38,621;套用用 `apply_plan`(逐值字元組對應,只動 3-byte escape payload)。
- **LLM 回覆寬容解析**:raw_decode 取首個 JSON 物件(容許尾隨資料/重複輸出);
  失敗批「跳批續跑」不中斷(斷點存儲,重跑即補該批)。
- **J. 結構字符串驗證**(新增閘門,用戶要求):對含 `§/$/[/£/數字/全形標點` 的
  行值,以「結構骨架」(CJK→'中',其餘逐字保留)與簡體源同 KEY 行逐字符比對,
  不一致即 FAIL。實測 25,406 條結構字符串骨架全數與簡體源一致。
- **D 檢查白名單**:里/托/占/征/伙 為正體多義字(里程/村里/哈裡發/芬里爾等譯名),
  不列入簡體殘留;但「托→託、占→佔、征→徵、伙→夥」仍以詞表替換(語感優先)。
- **LLM 引入新字元**:T2 換詞產生 35 個原 corpus 沒有的字(禦/盪/癒/捲/濕/痲/
  髮/鬍/鬆/隻/裡…)→ 必須重跑 `rebuild_fonts.py`(A 檢查缺字即 FAIL)。
- **建置鏈 archive 格式**:`make_release.py` / CI `modpack.yml` 產「zip 根 =
  內容 + descriptor.mod(archive=)」+ 根 `.mod`(archive= 指向);
  部署 = 兩 mod 目錄(Documents 與 OneDrive)。

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
- T2 全量句子批次剩餘 ~37.8k(背景續跑,斷點續;完成後重跑字型/A 檢查)
- 三 mod 全開(jps sup + gui fix)於最終版複測
- parse_error 失敗批補跑(重跑本腳本即重試)

## 5. 閃退調查與交付狀態(2026-08-25)

- 症狀:載入早期(主選單前)閃退;原版可開、只開主 mod 也崩。
- 二分結論(用戶實測):
  - 8/18 b9f1dc9、8/21 079f472(含 35 新字形重建、738 值句子批次)= **可玩**
  - 8/24 全量句子批次完成後(HEAD,42k 值、3,392 行 csv 變更、字型再重建 18 新字形)= **閃退**
  - 8/24 深夜的「53 新字形版」字型用戶從未實測過。
- 靜態調查(全部通過,未能靜態定位):
  - json 對映 vs csv 值(4,601 筆)/0 不一致;舊值消失/新值未出現 138 個 = 前後批覆蓋正常
  - 18 新字形(倖儘剷嚥姦捨沖祕穀穫紮繫蔔薑螫采餵鸠)六檔座標全在界內、無重複 id
  - 字型 dds 尺寸/格式(2048²、4096×7000、DXT3/DXT5)兩版一致
  - 0x80xx 私用區誤報釐清(0x8000-9FFF 是中文本尊區,非 chrome)
  - error.log 尾部 gfx_dx9 -2005530516 = DXGI 裝置移除,為接續錯誤非根因
- **決策(優先可玩)**:交付回滾為 079f472 實證可玩版(全量 89.9MB 主包+14.5MB sup+0.3MB gui)。
  06bdcebc(HEAD)內容保留於 git,未來要納回全量批次,
  **必須**在 079f472 基礎上以「每批一小組檔案逐一實測」方式導入(不得整批推)。
- zip 與 mod 目錄同步:兩 mod 目錄(Documents / OneDrive)md5 一致。


## 6. 雙版本發布(2026-08-25)

- 釋出架構:版本一 = 台灣化完整版(HEAD/079f472 內容,rework 為「main 工作區 = 可玩內容」);
  版本二 = 基本繁體版(commit `21a34ee`:T1 詞表 + 8/18 修改字型,無 LLM)。
- main 目錄內容已回滾為 079f472(可玩);全量批次(3,392 行)保留於 git 歷史,
  未來導入必須分批實測(見 §5)。
- `.gitignore` 新增 `release/`、`*.zip`、`*.mod`(產物不入庫;root 三 zip 已 untrack)。
- `.github/workflows/modpack.yml`:tag `v*` → 產六包(兩版 × 三模組)+ 自動貼 GitHub Release;
  main push/手動 → 產 artifacts;`21a34ee` 以 git archive 取用(不依賴工作區狀態)。
- 命名:版本一 = `ck2_chinese_tw` / 版本二 = `ck2_chinese_basic`;sup/gui_fix 各有對應(Basic 尾綴)。
- 本地實測:兩版 zip 110 條目、字型檔正確分離(734350 vs 734140)。
