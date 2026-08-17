# TODO

## 進行中:繁體顯示修復
- [x] 確認 52漢化 escape SHIFT 編碼規則(0x12 = payload+0x900、0x13 = payload+0x8F1、0x10/0x11 = 原碼)
- [x] convert_tw.py:decode/encode 套用 SHIFT 規則
- [x] 控制字元防禦(0x0A/0x22/0x3B 等低字節 → 改 0x13 形式,行結構不被破壞)
- [x] 重轉 + 驗證(payload 危險字節 = 0、mask 結構與簡體一致)
- [ ] 部署 folder mod + 重打包 zip → 遊戲內驗證繁體顯示(主 mod 單開)

## 待辦:台灣用語(LLM 批次漢化)
- [ ] 寫 LLM 批次翻譯工具(CK2 CSV 版):沿用 translate_batch_example 的模式(batch JSON / retry / progress 斷點 / placeholder 保護)
  - 不另建專名對照表;直接由 LLM 依台灣用語慣例統一(網絡→網路、信息→訊息 等),確保整體翻譯名詞統一
  - 批次以「句」為單位,保護 $XXX$ / £X$ / §G 色彩碼 / escape 結構;輸出經 byte-inplace 安全編碼寫回
  - 優先處理 OpenCC 兜不住的台灣用語/語感;逐批抽查

## 待辦:其它
- [ ] 三個 mod 全開閃退問題複測(byte 級修復後理論上已解,需實機確認)
- [ ] 繁體字型缺字巡檢(愛/願/裡/灣 等已重建,實機確認無豆腐)
- [ ] ck2dll fork:main 同步檢查、release workflow 驗證(GitHub Actions 產包)