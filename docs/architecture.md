# 架構與交接說明

> 讀者：接手或參與開發的工程師。最後更新：0.3.0。產品名稱「順打輸入法 Shunda IME」，內部代號 `smartime`。

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
- 另外兩個行程，都不在打字的路徑上：
  - **設定頁**（`backend/settings.py` → `smartime.settings`）：本機 HTTP 伺服器 + Edge/Chrome App 視窗（見 §5）。
  - **語音輸入**（`smartime.voice.service`）：開啟語音輸入時才啟動，用另外安裝的 Python 套件（見 §7）。
- 三個行程只透過使用者資料夾溝通：`config.json`（後端比對修改時間後重新載入）與 `user.db`（SQLite WAL）。

## 2. 引擎分層（`src/smartime/engine`）

| 模組 | 職責 |
|------|------|
| `bopomofo.py` | 注音結構：聲母/介音/韻母/聲調分類、組音節、聲調工具 |
| `layouts.py` | 實體按鍵 ↔ 注音符號（大千、倚天）；反查讀音 → 按鍵（Tab 接續用） |
| `lexicon.py` | 系統詞庫（唯讀 SQLite）＋ 使用者詞庫疊加：讀音→詞、讀音前綴、英文詞頻、詞語補全 |
| `userdict.py` | 我的詞庫與學習記憶（`user.db`）：新增、學習、刪除、封鎖、分類、備份與合併 |
| `decoder.py` | **核心**：把原始按鍵緩衝區解成中英混合的最佳分段（lattice + Viterbi） |
| `session.py` | 每個輸入情境的狀態機：插入/刪除/游標/候選/Tab/送出/中英模式/符號面板/學習時機 |
| `correction.py` | Vim 式修正模式（`CorrectionMixin`，混入 Session） |
| `symbols.py` | 符號面板的分類與最近使用（`recent-symbols.json`） |
| `keys.py` | 與平台無關的按鍵事件（數值沿用 Windows VK code；`extended` 區分左右 Alt） |

設定（`smartime/config.py`）是一個 dataclass：`from_dict()` 只接受認得的欄位並修正不合法的值，
所以舊版或手改壞的 `config.json` 不會讓輸入法起不來。

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
  | `DROP` | 小寫字母或鍵盤配置自己的標點鍵（大千 `, . / ; -`、倚天另含 `' =`）被當成誤觸而略過（不顯示、不改變語言狀態） | `Weights.drop`（低於最罕用真實音節；設定「保守」時更低） |

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
- 修正模式（`correction.py`）：`Esc` 進入，按鍵變指令；國字／注音／按鍵三種檢視畫在提示框（組字區永遠是國字，
  避免 App 看到注音字串）。`j/k` 循環換字只在游標離開時學最後停下的那個。
- 符號面板：單按右 Alt（`KeyInput.extended`）開關，`Tab` 換分類；用 PIME 的候選窗顯示。
  **PIME 不會把「按住 Alt 時的其他按鍵」交給輸入法**（只收到 Alt 本身），所以不能用 `Ctrl+Alt+,` 之類的組合鍵。
- `VK_PACKET`（其他程式用 SendInput 的 Unicode 模式送出的字，例如語音輸入、密碼管理器）一律放行，不進解碼器。

### 2.3 我的詞庫與學習（`userdict.py`）

- 一個 SQLite 檔 `%APPDATA%\SmartIME\user.db`（WAL）：`entries(phrase, reading, kind, category, source, count, blocked …)`，`UNIQUE(phrase, reading)`。
- **只從明確的選擇學習**：候選窗選字、Tab 接受、單字選出新詞、修正模式最後停下的字。解碼器猜的、使用者沒動的字不學，
  所以猜錯不會自我強化（使用者對 Windows 輸入法的主要抱怨）。
- 分數與系統詞庫同為 log10：手動新增的詞至少 -3.0（相當常用詞）；使用次數加分 `0.9 + 0.6·log2(count)`，上限 +3。
- `Delete`（候選窗）：學來的 → 忘記；手動加的 → 刪除；系統詞庫的 → 封鎖（不再建議）。
- 設定頁與輸入法是不同行程：輸入法每個按鍵前比對 `PRAGMA data_version`，有變動才重新載入。
- 備份：設定頁匯出 `.smartime`（zip：`config.json` + 詞庫），匯入時**合併**（手動詞與分類加入、次數相加、封鎖保留），不覆蓋。

### 2.4 輸入法方案：注音、拼音、倉頡（`decoder.scheme`）

- 解碼器的 `decode(..., scheme=)` 決定中文怎麼打；英文、數字、標點、Viterbi 都共用。中英自動一次只混一種中文
  （`config.chinese_scheme`），因為同一個字母在三種打法意思不同；純拼音、純倉頡是獨立模式（`Mode.PINYIN`／`CANGJIE`）。
- **拼音**（`engine/pinyin.py`）：詞庫裡每個無聲調注音音節自動轉成標準拼音（ü＝v，另收 lue/nue），反查成打字表。
  `_pinyin_table` 從每個位置找出可能的音節，後面可以接聲調數字 1–5 與一個結束用的空白；`_py_edges` 把音節串起來，
  用 `zh.plain`（讀音去聲調）查詞，有打聲調的音節再過濾讀音。未完成的尾巴（`pending_pinyin`）比完整音節貴，
  所以 `women` 立刻顯示「我們」而不是「我 + men」。
- **倉頡五代**：`cangjie` 資料表（碼、字、重碼順位）。1–5 碼後接空白才成字；連續 2–3 個字時，若組成詞庫裡的詞
  （`Lexicon.text_info` 以字查詞）就用詞的分數，否則用單字分數加上順位成本（`cangjie_rank`）。
- 三種方案的段落都帶注音讀音（倉頡由字反查），所以學習、接續、修正模式的注音檢視都共用；
  Tab 接續插入的按鍵由 `Decoder.unit_keys(scheme, 字, 音節)` 產生（注音鍵、拼音字母或倉頡碼＋空白）。
- 拼音、倉頡下 `, . ;` 是標點（`PLAIN_PUNCT`），也不做雜鍵略過（字母都有意義）。
- 詞庫是 schema 2（`tools/build_data.py` 產生 `zh.plain` 與 `cangjie`）；舊詞庫時 `Lexicon.has_pinyin`／`has_cangjie`
  為假，這兩個模式自動隱藏。

## 3. PIME 協定重點（`src/smartime/pime`）

- 請求：`<client_id>|<json>`；回覆：`PIME_MSG|<client_id>|<json>`。stdout 只能輸出協定訊息，紀錄寫到 `%APPDATA%\SmartIME\logs\backend.log`。
- 方法：`init`、`onActivate`、`onDeactivate`、`filterKeyDown`/`onKeyDown`、`filterKeyUp`/`onKeyUp`、`onCommand`、`onMenu`、`onKeyboardStatusChanged`、`onCompositionTerminated`、`close`。
- PIME 套用回覆的順序：message → candidates → **commit → composition**。所以同一個回覆可以「送出前半段、保留後半段在組字區」。
- 候選數不可超過 `setSelKeys` 的長度（C++ 端有 assert）。
- 提示（藍色注音）與 Tab 建議目前都用 PIME 的 message window 顯示；外觀無法客製（要改 PIME C++，列在後續階段）。
- **陷阱：開始組字的那個回覆不能帶 `showMessage`。** PIME 先處理 message、後處理 composition；
  若當下沒有組字，它會開一個臨時組字並在回覆結尾結束它，結果第一個按鍵被當成原始字母送出。
  因此提示從第二個鍵開始顯示（`SmartTextService._composing`，有回歸測試）。
- `onCompositionTerminated`：`forced=false` = PIME 自己結束（處理我們的 commit 時）→ **保留緩衝區**。誤把它當成 App
  結束會讓「自動送出前段」後剩下的文字消失（VS Code 實測問題）。
  `forced=true` = App 結束組字：一般是使用者造成的（點別處、Ctrl+Enter 送出、換視窗），文字已留在文件裡 → 重設緩衝區。
  **例外：Chromium/Electron 的編輯器重繪時會自己結束組字，但頁面上還留著舊的組字**，下一個組字會把它整段蓋掉
  （「長句後面內容遺失」，`browser_typing_test` 可重現）。所以前景是 `winapp.KEEP_APPS` 裡的 App、和開始組字時同一個、
  1.5 秒內沒有按鍵交給 App、滑鼠沒有按下（含「按過」位元）時，保留緩衝區，下一鍵把整段重新送出。
  設定 `keep_on_app_interrupt` 可關掉；紀錄檔的 `kept=` 欄位記下每次判斷（只記 App 名稱與長度）。
- Launcher 以**小寫** GUID 對應後端（`init` 的 `id` 必須是小寫）；找不到後端時**不會回覆**，客戶端會卡住。
- PIME 讀 `ime.json` / `backends.json` 用 jsoncpp：必須是合法 JSON、不可有 BOM（`tests/test_backend_files.py` 檢查）。

## 4. 系統詞庫（`tools/build_data.py`）

1. 下載固定 commit 的 McBopomofo `Source/Data`（MIT），用它自己的 curation pipeline 產生 `data.txt`（含多音字規則與後製斷言）。
2. 過濾：去掉標點/符號項、只有聲調的項、字數與音節數不符的項（引擎假設一字一音節）。
3. 英文：wordfreq 前 80,000 詞 + `data/lexicon/en_terms.txt`（我們維護的中英夾雜常用詞，最低給 -3.5 分）。
4. 輸出單一 SQLite：`data/generated/smartime.db`（不進 git，可重現）。

## 5. 設定頁（`src/smartime/settings`）

- `python -m smartime.settings`（安裝後：開始功能表「順打輸入法 設定」、系統匣選單「設定…」、PIME 的 configTool）。
- 標準函式庫 `ThreadingHTTPServer`，只聽 127.0.0.1、隨機埠；用 Edge 或 Chrome 的 `--app` 視窗開啟，找不到就用預設瀏覽器。
- 安全：每次啟動產生 token（`X-SmartIME-Token`），並檢查 `Host` 必須是 127.0.0.1（防 DNS rebinding）；
  CSP 只允許自己的資源。其他網頁碰不到 API。
- 同時只有一個：`settings-server.json` 記下埠與 token，第二次開啟沿用同一個伺服器，只是多開一個視窗。網頁每隔幾秒 ping，
  視窗關掉 75 秒後自行結束（下載模型、安裝元件期間不結束）。
- 介面（`ui/`）與設計稿 `docs/design/settings-mockup.html` 一致；設定存檔後輸入法下一個按鍵就生效（`Engine.refresh()`）。

## 6. 安裝檔（`installer/`、`tools/build_installer.py`）

- `uv run python tools/build_installer.py` → `dist\ShundaIME-Setup-<版本>.exe`（Inno Setup 6；預設找 `build/tools/InnoSetup6/ISCC.exe`）。
  建置時下載並以 SHA-256 驗證：PIME 1.3.0 官方安裝檔、Python embeddable、Inno Setup 繁中訊息檔。
- 安裝流程：沒有 PIME 時以 `/S` 安靜安裝官方版 → 停止 launcher 與後端 → 複製到 `<PIME>\smartime` →
  寫 `backends.json`、以 TSF API 註冊 64 位元與 32 位元設定檔 → 以原本的使用者身分加到語言清單 →
  經由 `explorer.exe` 重新啟動 launcher（不屬於安裝程式的行程）→ `verify.py` 端對端檢查。
- 64 位元系統工具用 `{sys}`（Inno Setup 是 32 位元程式，`Sysnative` 在 64 位元 cmd 裡看不到）。
- 移除時保留 PIME 與其他 PIME 輸入法，也不刪 `%APPDATA%\SmartIME`。
- 發行前驗證：`tools\test_installer.ps1`（一次 UAC：安裝 → 驗證 → 移除 → 還原開發模式）。安裝檔還沒有程式碼簽章。

## 7. 語音輸入（`src/smartime/voice`）

- 獨立行程，不在打字的路徑上。需要的套件（faster-whisper、sherpa-onnx、sounddevice、numpy、opencc；有 NVIDIA 顯示卡
  另加 cuBLAS／cuDNN）裝在 `%LOCALAPPDATA%\SmartIME\voice-runtime`：設定頁「安裝語音元件」複製輸入法自己的
  embeddable Python，用官方 `pip.pyz --target` 安裝，不需要管理員權限（`install.py`）。開發時用 repo 的 `.venv`
  （`uv sync --group voice`）。找 Python 的順序見 `launch.voice_python()`。
- 啟動：輸入法 `onActivate` 時若 `voice_enabled` 就 `launch.start()`；設定頁打開開關時也會啟動。mutex
  `Local\SmartIME.Voice` 保證只有一個。服務每 3 秒讀 `config.json`：關掉就自行結束，換模型就在背景重新載入。
- 按鍵：`WH_KEYBOARD_LL` 放在專用執行緒（自己的訊息迴圈），不攔截任何按鍵，只記狀態並 PostMessage 給主執行緒，
  所以主執行緒開麥克風或打長文字時不會拖慢整台電腦的鍵盤（Windows 也會移除逾時的 hook）。
  右 Ctrl 按下 → 開麥克風；放開 → 辨識；中途按了其他鍵 → 取消（那是快捷鍵）；不到 0.35 秒 → 忽略。
- 辨識（`asr.py`）：`auto` = 有 CUDA 且 Breeze 已下載 → Breeze-ASR-25（faster-whisper／CTranslate2，float16），
  否則 SenseVoice Small（sherpa-onnx，int8，CPU）。模型在 `%LOCALAPPDATA%\SmartIME\models`（設定頁下載，可續傳）。
- 後處理（`text.py`）：OpenCC **s2tw**（只換字形；s2twp 會把使用者說的「文件」換成「檔案」）、去掉中文字間空白、
  SenseVoice 的全大寫英文改回小寫但保留縮寫（API、MVP）、接回被拆開的縮寫（`MV P` → MVP）、我的詞庫裡的英文拼法優先。
- 輸出：`SendInput` 的 `KEYEVENTF_UNICODE`（App 收到 `VK_PACKET`，本輸入法一律放行）。提示框是
  `WS_EX_NOACTIVATE` 的小視窗，不搶焦點，文字才會打進原本的視窗。
- 隱私：只在按住時開麥克風；紀錄檔（`logs\voice.log`）只記音檔秒數、耗時與字數，不記內容。
- 驗證：`python -m smartime.devtools.voice_test [--engine breeze|sensevoice]`：以錄好的音檔代替麥克風，
  其餘全是真的（SendInput 按右 Ctrl、辨識、打進啟用本輸入法的文字框）；同樣等閒置 5 秒、碰到鍵盤滑鼠就停。

## 8. 路徑與可攜性

- 系統資料：相對於套件位置解析（`paths.app_root()`），開發與部署兩種版面都適用。
- 使用者資料：`%APPDATA%\SmartIME`（可用環境變數 `SMARTIME_USER_DIR` 覆寫，測試即如此）。換電腦時帶走此資料夾即可。
- 程式碼中不得出現機器相關的絕對路徑。

## 9. 開發流程

- **版本號**：唯一來源是 `src/smartime/__init__.py` 的 `__version__`（安裝檔、設定頁、匯出檔都讀它）。
  要改版本用 `uv run python tools/set_version.py 0.4.0`，它會一起改 `pyproject.toml`、`ime.json`（PIME 要字面值）、
  `uv.lock`；不帶參數則列出各處版本並檢查一致。`tests/test_backend_files.py` 會擋下不一致。CHANGELOG 手寫。
- `install.ps1 -Dev`：`<PIME>\smartime` 變成指向 `repo\backend` 的 junction；改完 Python 程式後，在系統匣 PIME 圖示選「Restart PIME」重啟後端即可。
- 改 `ime.json`（名稱、GUID、圖示）後需重新執行安裝（會重新登錄 TSF 語言設定檔）。
- 不安裝也能測：`python -m smartime.devtools.simulate --steps "<按鍵>"`；測試使用同一套模擬器。
- `tests/test_reported_issues.py` 記錄使用者回報的問題；未修好時用 xfail(strict)，修好就移除標記成為回歸測試。
- 安裝後的三層驗證（任何動到 PIME/TSF 的改動都要跑）：
  1. `uv run pytest` — 引擎、session、協定、靜態檔案檢查
  2. `python -m smartime.devtools.pime_probe --require-conversion` — 以 named pipe 直接連 PIMELauncher（如同 App 內的 DLL），驗證 launcher → 後端 → 引擎；`install.ps1` 最後一步也會自動跑
  3. `python -m smartime.devtools.tsf_typing_test`（與 `--richedit`）— 建立真的文字框、以 TSF 啟用本輸入法、用 SendInput 實際打字並讀回結果，要求「實機 == 模擬器」。
     **會等使用者閒置 5 秒才開始，偵測到真人按鍵/點擊立即中止**；使用者在用電腦時不要跑。
     每個案例前把學習記憶倒回測試開始時的狀態（`MemoryGuard`），結束後還原，不會污染使用者的詞庫。
  4. `python -m smartime.devtools.browser_typing_test` — 同樣的保護，在 Edge（獨立的暫時設定檔）的
     textarea、contenteditable、React 受控元件與「會打斷組字的編輯器」裡打字，另測組字中點滑鼠、Ctrl+Enter 送出不會重複。
- 開發模式改完程式／詞庫後：`scripts\dev-reload.ps1 [-Rebuild]`（停 launcher → 重建 → 以 explorer 重啟 → probe）。
  只殺後端行程不夠：launcher 會立刻重啟它，而且詞庫檔會一直被占用。
- PIME launcher 的除錯紀錄（`%LOCALAPPDATA%\PIME\PIMELauncher.json` 的 `logLevel: debug`）會記下每個按鍵與回覆，
  是分析實機問題的最佳資料（配對 SEND/RECV 的 seqNum 即可重建每個 session）；也因此含有使用者打過的字，除錯完應建議關閉。
- 用 bash heredoc 產生含反斜線的檔案時，`\\` 可能被吃成 `\`（ime.json 事故）；這類檔案請用編輯器／Write 工具寫，並驗證。

## 10. 已知限制（0.3.0）

- 鍵盤：大千、倚天；許氏（一鍵多義）尚未支援。拼音、倉頡五代在開發版（見 §2.4）。容錯有「順序錯」與「多按雜鍵」，少按/相鄰鍵尚未做。
- 詞庫缺台灣口語讀音（例：欸 只有 ㄞˇ/ㄟˋ，沒有 ㄟ），需要口語讀音補充表。
- 語言模型只有詞頻（unigram）：同音字靠詞頻選（例：「打逗號」可能成「打鬥號」），需要學習或 bigram。
- Chromium 系的自動化實機測試只有 Edge；VS Code、LINE 等 Electron App 靠同一套 `KEEP_APPS` 規則，尚未逐一實測。
- 提示與 Tab 建議共用一個 message window，樣式為 PIME 預設（非藍色）。
- 語音輸入的快速鍵固定為右 Ctrl；還不會串流顯示（放開後才辨識整段）。
- `-Dev` 模式下圖示放在使用者資料夾內，部分 UWP（AppContainer）App 可能讀不到圖示；一般安裝無此問題。
- PIME 1.3.0 為 2023 版；主線（2026）有修正但無正式發行，之後評估自行建置。
