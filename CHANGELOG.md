# Changelog

## Phase 3.1 — 安裝修正與實機驗證（2026-10-01）

- 修正 `ime.json` 不是合法 JSON（圖示路徑反斜線）——PIME 註冊時解析失敗的原因
- 安裝改用 TSF API 只登錄本輸入法，不再 regsvr32 重新註冊整個 PIME
- 修正「第一個注音會變成原始字母」：開始組字的回覆不能同時顯示提示訊息（PIME 行為）
- 新增 `pime_probe`（launcher 端對端）與 `tsf_typing_test`（真實文字框打字，EDIT 與 RichEdit/TSF 兩種）；安裝腳本最後自動驗證
- 實機結果：8 個打字情境在 EDIT 與 RichEdit 皆通過

## Phase 3 — MVP（2026-10-01）

可以安裝試玩的第一版，重現華碩智慧輸入法的打字手感（模式 B：可回頭修改）。

- 引擎：注音結構、大千鍵盤、SQLite 詞庫、lattice 解碼器、session 狀態機
- 混打：字母先顯示 + 注音提示 → 聲調鍵轉中文；英文、數字、標點自動判斷
- 選字：`↑/↓` 候選窗（直式、1–9 選字）、游標移到任意字修改、選過的字固定（pin）
- Tab 接續詞、全形標點自動送出、超長自動送出舊文字、單按 Shift 切換純英文
- PIME 後端（自帶 Python 3.13 embeddable），安裝/移除腳本（一般與 `-Dev` 模式）
- 測試：45 項（含使用者回報問題的 xfail 測試，留待 Phase 4）

## Phase 0–1 — 調查（2026-10-01）

- 市場與技術調查報告：`docs/research/phase0-1-research.md`
