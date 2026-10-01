# 架構與交接說明

> 讀者：接手或參與開發的工程師。最後更新：Phase 3（MVP）。

## 1. 全貌

```
 應用程式 (任何 App)
   │  TSF (Text Services Framework)
   ▼
 PIMETextService.dll  ← PIME 提供的 C++ 前端（x86/x64，載入到每個 App 內）
   │  named pipe
   ▼
 PIMELauncher.exe     ← PIME 提供；依 backends.json 啟動各後端行程
   │  stdin/stdout，每行一個 JSON
   ▼
 <PIME>\smartime\runtime\python.exe server.py      ← 我們的後端（本 repo）
   └─ smartime.pime.server → SmartTextService → engine.Session
```

- 我們**不修改 PIME**，只在 `backends.json` 新增一個名為 `smartime` 的後端，並在
  `<PIME>\smartime\input_methods\smartime\ime.json` 宣告輸入法（固定 GUID `{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}`）。
- 後端使用**自己下載的 embeddable Python 3.13**（`backend/runtime`），不依賴 PIME 內建的 Python 3.8，也不依賴使用者電腦上的 Python。
- 引擎只用標準函式庫，所以 embeddable Python 不需要安裝任何套件。

## 2. 引擎分層（`src/smartime/engine`）

| 模組 | 職責 |
|------|------|
| `bopomofo.py` | 注音結構：聲母/介音/韻母/聲調分類、組音節、聲調工具 |
| `layouts.py` | 實體按鍵 ↔ 注音符號（目前：大千）；反查讀音 → 按鍵（Tab 接續用） |
| `lexicon.py` | 唯讀 SQLite 詞庫存取與快取：讀音→詞、讀音前綴、英文詞頻、詞語補全 |
| `decoder.py` | **核心**：把原始按鍵緩衝區解成中英混合的最佳分段（lattice + Viterbi） |
| `session.py` | 每個輸入情境的狀態機：插入/刪除/游標/候選/Tab/送出/中英模式 |
| `keys.py` | 與平台無關的按鍵事件（數值沿用 Windows VK code） |

### 2.1 解碼器（decoder）

- 輸入是**原始按鍵序列**（不是注音），每按一鍵就**整段重新解碼**，所以後面的字可以改變前面的判讀。
- 每一種「把一段按鍵解讀成某種輸出」都是一條邊（`Segment`），帶 log10 分數：

  | Kind | 說明 | 分數來源 |
  |------|------|----------|
  | `ZH` | 一串音節 → 詞庫中的詞 | 詞庫分數（McBopomofo） |
  | `EN` | 英數字串，原樣輸出 | wordfreq 詞頻；未知字串依長度扣分 |
  | `NUM` | 數字 | 常數 |
  | `PUNCT` | 全形/半形標點 | 常數 |
  | `SPACE` | 字面空白 | 常數 |
  | `PENDING` | 緩衝區尾端尚未打聲調的注音（原樣顯示 + 注音提示） | 0 |
  | `LITERAL` | 任何單鍵原樣輸出（保底，確保一定有解） | 很低 |

- Viterbi 狀態 = (上一個語言, 上一個 segment 種類)，用來計算「中英切換成本」等轉移分數。所有常數集中在 `Weights`。
- 使用者選過的候選會成為 **pin**（固定的邊），解碼時強制經過，其他邊不得跨越它。
- Phase 3 只接受「標準順序」的音節（與華碩相同的嚴格行為）；Phase 4 會在同一個 lattice 上加入雜訊通道（重排、多按、少按、相鄰鍵）。

### 2.2 Session（模式 B）

- 狀態只有：`keys`（原始按鍵）、`pins`、`cursor`（按鍵位置）、`mode`、候選清單、Tab 建議。
- 顯示用的每個字元（unit）都對應一段按鍵；中文一字 = 一個音節的按鍵，其他種類一字 = 一鍵。游標永遠停在 unit 邊界。
- 送出時機：`Enter`、全形子句標點（，。？！：；）、超過 `max_buffer_chars` 時送出最舊的部分、切換中英模式。
- `view()` 回傳前端需要的一切（組字字串、游標、送出字串、候選、提示、Tab 建議、模式）；**呼叫後會清空待送出字串**，每個事件只呼叫一次。

## 3. PIME 協定重點（`src/smartime/pime`）

- 請求：`<client_id>|<json>`；回覆：`PIME_MSG|<client_id>|<json>`。stdout 只能輸出協定訊息，紀錄寫到 `%APPDATA%\SmartIME\logs\backend.log`。
- 方法：`init`、`onActivate`、`onDeactivate`、`filterKeyDown`/`onKeyDown`、`filterKeyUp`/`onKeyUp`、`onCommand`、`onMenu`、`onKeyboardStatusChanged`、`onCompositionTerminated`、`close`。
- PIME 套用回覆的順序：message → candidates → **commit → composition**。所以同一個回覆可以「送出前半段、保留後半段在組字區」。
- 候選數不可超過 `setSelKeys` 的長度（C++ 端有 assert）。
- 提示（藍色注音）與 Tab 建議目前都用 PIME 的 message window 顯示；外觀無法客製（要改 PIME C++，列在後續階段）。

## 4. 資料（`tools/build_data.py`）

1. 下載固定 commit 的 McBopomofo `Source/Data`（MIT），用它自己的 curation pipeline 產生 `data.txt`（含多音字規則與後製斷言）。
2. 過濾：去掉標點/符號項、只有聲調的項、字數與音節數不符的項（引擎假設一字一音節）。
3. 英文：wordfreq 前 80,000 詞 + `data/lexicon/en_terms.txt`（我們維護的中英夾雜常用詞，最低給 -5.0 分）。
4. 輸出單一 SQLite：`data/generated/smartime.db`（不進 git，可重現）。

## 5. 路徑與可攜性

- 系統資料：相對於套件位置解析（`paths.app_root()`），開發與部署兩種版面都適用。
- 使用者資料：`%APPDATA%\SmartIME`（可用環境變數 `SMARTIME_USER_DIR` 覆寫，測試即如此）。換電腦時帶走此資料夾即可。
- 程式碼中不得出現機器相關的絕對路徑。

## 6. 開發流程

- `install.ps1 -Dev`：`<PIME>\smartime` 變成指向 `repo\backend` 的 junction；改完 Python 程式後，在系統匣 PIME 圖示選「Restart PIME」重啟後端即可。
- 改 `ime.json`（名稱、GUID、圖示）後需重新執行安裝（會重新登錄 TSF 語言設定檔）。
- 不安裝也能測：`python -m smartime.devtools.simulate --steps "<按鍵>"`；測試使用同一套模擬器。
- `tests/test_reported_issues.py` 記錄使用者回報、尚未修好的問題（xfail strict）；修好時移除標記。

## 7. 已知限制（Phase 3）

- 只支援大千鍵盤；只接受標準順序注音；沒有容錯與學習（Phase 4）。
- 提示與 Tab 建議共用一個 message window，樣式為 PIME 預設（非藍色）。
- `-Dev` 模式下圖示放在使用者資料夾內，部分 UWP（AppContainer）App 可能讀不到圖示；一般安裝無此問題。
- PIME 1.3.0 為 2023 版；主線（2026）有修正但無正式發行，之後評估自行建置。
