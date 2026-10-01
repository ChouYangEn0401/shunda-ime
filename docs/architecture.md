# 架構與交接說明

> 讀者：接手或參與開發的工程師。最後更新：Phase 4-1。

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
  | `EN` | 英數字串，原樣輸出 | wordfreq 詞頻；未知字串依長度扣分，夾雜數字再加扣；單字母（a、I 除外）加扣 |
  | `NUM` | 數字 | 常數（刻意比真實中文音節貴：ㄅㄉㄓㄚㄞㄢ與聲調都在數字鍵上） |
  | `PUNCT` | 全形/半形標點 | 常數 |
  | `SPACE` | 字面空白 | 常數 |
  | `PENDING` | 緩衝區尾端尚未打聲調的注音（原樣顯示 + 注音提示） | 0 |
  | `LITERAL` | 任何單鍵原樣輸出（保底，確保一定有解） | 很低 |
  | `DROP` | 小寫字母或大千標點鍵被當成誤觸而略過（不顯示、不改變語言狀態） | `Weights.drop`（低於最罕用真實音節） |

- Viterbi 狀態 = (上一個語言, 上一個 segment 種類)，用來計算「中英切換成本」等轉移分數。所有常數集中在 `Weights`。
- 使用者選過的候選會成為 **pin**（固定的邊），解碼時強制經過，其他邊不得跨越它。
- **雜訊通道（Phase 4）**：同一音節內任意順序的按鍵都重排成標準順序（`bopomofo.canonical`，結果唯一），
  非標準順序收 `Weights.reorder` 成本。多按的雜鍵用 `DROP` 邊處理；少按/相鄰鍵為下一步，加在同一個音節表上。
- `decode(allow_english=False)` = 純中文模式：不產生 `EN` 邊，上排數字鍵只當注音（數字只來自數字鍵盤）。
- `zh_alternatives()` 列出某位置起的所有中文讀法，供候選窗做「英文 → 中文」的跨類別換字。
- 標點：`config.halfwidth_symbols` 中的符號鍵以半形為首選，其餘全形；`PUNCT_VARIANTS` 是候選窗的相關符號。
- **權重怎麼調**：`tests/test_typing_corpus.py` 是使用者真實按鍵（含打錯順序）的回歸語料；改任何
  `Weights` 都必須讓它維持綠燈。純同音字選擇（需要上下文）的案例標為 xfail，等語言模型改進。

### 2.2 Session（模式 B）

- 狀態只有：`keys`（原始按鍵）、`pins`、`cursor`（按鍵位置）、`mode`、`chinese_mode`、候選清單、Tab 建議。
- 模式：`AUTO`（中英自動）、`CHINESE`（純中文）、`ENGLISH`（純英文）。Shift 在 ENGLISH 與 `chinese_mode`（上次用的中文側模式）間切換；`set_mode()` 供系統匣選單使用。
- 候選窗跨類別：中文 → 同音詞 + 原始按鍵（含前面被略過的鍵）；英文/數字/原始 → 大小寫變化 + 中文讀法；標點 → 目前/全形/半形/相關符號。
- 提示：游標在尾端時顯示未完成音節的注音；游標往回移時顯示「字 注音 ⌨ 按鍵（略過 x）」。
- 顯示用的每個字元（unit）都對應一段按鍵；中文一字 = 一個音節的按鍵，其他種類一字 = 一鍵。游標永遠停在 unit 邊界。
- 送出時機：`Enter`、全形子句標點（，。？！：；，含 `Ctrl+符號` 打出的）、超過 `max_buffer_chars`
  時送出最舊的部分（尚在打的音節期間不觸發；觸發時送到上限以下 10 字，減少部分送出次數）、切換模式。
- `Ctrl(+Shift)+符號` → 全形標點（`session.CTRL_PUNCT`，微軟新注音慣例），只在中文側模式（自動／純中文）攔截。
- `view()` 回傳前端需要的一切（組字字串、游標、送出字串、候選、提示、Tab 建議、模式）；**呼叫後會清空待送出字串**，每個事件只呼叫一次。

## 3. PIME 協定重點（`src/smartime/pime`）

- 請求：`<client_id>|<json>`；回覆：`PIME_MSG|<client_id>|<json>`。stdout 只能輸出協定訊息，紀錄寫到 `%APPDATA%\SmartIME\logs\backend.log`。
- 方法：`init`、`onActivate`、`onDeactivate`、`filterKeyDown`/`onKeyDown`、`filterKeyUp`/`onKeyUp`、`onCommand`、`onMenu`、`onKeyboardStatusChanged`、`onCompositionTerminated`、`close`。
- PIME 套用回覆的順序：message → candidates → **commit → composition**。所以同一個回覆可以「送出前半段、保留後半段在組字區」。
- 候選數不可超過 `setSelKeys` 的長度（C++ 端有 assert）。
- 提示（藍色注音）與 Tab 建議目前都用 PIME 的 message window 顯示；外觀無法客製（要改 PIME C++，列在後續階段）。
- **陷阱：開始組字的那個回覆不能帶 `showMessage`。** PIME 先處理 message、後處理 composition；
  若當下沒有組字，它會開一個臨時組字並在回覆結尾結束它，結果第一個按鍵被當成原始字母送出。
  因此提示從第二個鍵開始顯示（`SmartTextService._composing`，有回歸測試）。
- `onCompositionTerminated`：`forced=true` = App 結束組字（點別處、換焦點）→ 重設緩衝區；
  `forced=false` = PIME 自己結束（處理我們的 commit 時）→ **保留緩衝區**。誤把後者當前者會讓
  「自動送出前段」後剩下的文字消失（VS Code 實測問題）。
- Launcher 以**小寫** GUID 對應後端（`init` 的 `id` 必須是小寫）；找不到後端時**不會回覆**，客戶端會卡住。
- PIME 讀 `ime.json` / `backends.json` 用 jsoncpp：必須是合法 JSON、不可有 BOM（`tests/test_backend_files.py` 檢查）。

## 4. 資料（`tools/build_data.py`）

1. 下載固定 commit 的 McBopomofo `Source/Data`（MIT），用它自己的 curation pipeline 產生 `data.txt`（含多音字規則與後製斷言）。
2. 過濾：去掉標點/符號項、只有聲調的項、字數與音節數不符的項（引擎假設一字一音節）。
3. 英文：wordfreq 前 80,000 詞 + `data/lexicon/en_terms.txt`（我們維護的中英夾雜常用詞，最低給 -3.5 分）。
4. 輸出單一 SQLite：`data/generated/smartime.db`（不進 git，可重現）。

## 5. 路徑與可攜性

- 系統資料：相對於套件位置解析（`paths.app_root()`），開發與部署兩種版面都適用。
- 使用者資料：`%APPDATA%\SmartIME`（可用環境變數 `SMARTIME_USER_DIR` 覆寫，測試即如此）。換電腦時帶走此資料夾即可。
- 程式碼中不得出現機器相關的絕對路徑。

## 6. 開發流程

- `install.ps1 -Dev`：`<PIME>\smartime` 變成指向 `repo\backend` 的 junction；改完 Python 程式後，在系統匣 PIME 圖示選「Restart PIME」重啟後端即可。
- 改 `ime.json`（名稱、GUID、圖示）後需重新執行安裝（會重新登錄 TSF 語言設定檔）。
- 不安裝也能測：`python -m smartime.devtools.simulate --steps "<按鍵>"`；測試使用同一套模擬器。
- `tests/test_reported_issues.py` 記錄使用者回報的問題；未修好時用 xfail(strict)，修好就移除標記成為回歸測試。
- 安裝後的三層驗證（任何動到 PIME/TSF 的改動都要跑）：
  1. `uv run pytest` — 引擎、session、協定、靜態檔案檢查
  2. `python -m smartime.devtools.pime_probe --require-conversion` — 以 named pipe 直接連 PIMELauncher（如同 App 內的 DLL），驗證 launcher → 後端 → 引擎；`install.ps1` 最後一步也會自動跑
  3. `python -m smartime.devtools.tsf_typing_test`（與 `--richedit`）— 建立真的文字框、以 TSF 啟用本輸入法、用 SendInput 實際打字並讀回結果，要求「實機 == 模擬器」。
     **會等使用者閒置 5 秒才開始，偵測到真人按鍵/點擊立即中止**；使用者在用電腦時不要跑。
- 開發模式改完程式／詞庫後：`scripts\dev-reload.ps1 [-Rebuild]`（停 launcher → 重建 → 以 explorer 重啟 → probe）。
  只殺後端行程不夠：launcher 會立刻重啟它，而且詞庫檔會一直被占用。
- PIME launcher 的除錯紀錄（`%LOCALAPPDATA%\PIME\PIMELauncher.json` 的 `logLevel: debug`）會記下每個按鍵與回覆，
  是分析實機問題的最佳資料（配對 SEND/RECV 的 seqNum 即可重建每個 session）；也因此含有使用者打過的字，除錯完應建議關閉。
- 用 bash heredoc 產生含反斜線的檔案時，`\\` 可能被吃成 `\`（ime.json 事故）；這類檔案請用編輯器／Write 工具寫，並驗證。

## 7. 已知限制（Phase 4-2）

- 只支援大千鍵盤；容錯有「順序錯」與「多按雜鍵」，少按/相鄰鍵與個人學習在 Phase 4 後續。
- 詞庫缺台灣口語讀音（例：欸 只有 ㄞˇ/ㄟˋ，沒有 ㄟ），需要口語讀音補充表。
- 語言模型只有詞頻（unigram）：同音字靠詞頻選（例：「打逗號」可能成「打鬥號」），需要學習或 bigram。
- Chromium 系（VS Code、Chrome、LINE 桌面版）尚無自動化實機測試，只有 EDIT 與 RichEdit。
- 提示與 Tab 建議共用一個 message window，樣式為 PIME 預設（非藍色）。
- `-Dev` 模式下圖示放在使用者資料夾內，部分 UWP（AppContainer）App 可能讀不到圖示；一般安裝無此問題。
- PIME 1.3.0 為 2023 版；主線（2026）有修正但無正式發行，之後評估自行建置。
