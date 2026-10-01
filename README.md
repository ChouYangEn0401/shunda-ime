# 智慧輸入法 (Smart IME)

免切換中英混打的注音輸入法（Windows）。打字手感參考華碩智慧輸入法：字母先出現、旁邊顯示注音提示、按聲調鍵轉成中文、Tab 接續；
底層改用「整句重新解碼」的 lattice 解碼器，從根本解決順序打反、多按雜鍵、誤判英文等問題，並記住你的用詞（學錯可以刪）。

> 狀態：**0.2.0**。已完成：混打解碼與容錯、三種輸入模式、我的詞庫與學習記憶、Vim 式修正模式、符號面板、設定頁、倚天鍵盤、單一安裝檔、
> 本地語音輸入（按住右 Ctrl 說話）。
> 調查報告：[docs/research/phase0-1-research.md](docs/research/phase0-1-research.md)

## 安裝（Windows 10/11）

1. 下載 `SmartIME-Setup-0.2.0.exe`，按兩下執行（會跳出系統管理員權限確認）。
   安裝檔還沒有數位簽章，Windows 可能顯示「Windows 已保護您的電腦」：按「其他資訊」→「仍要執行」。
2. 安裝程式會一併裝好 PIME 輸入法框架（沒有的話）、註冊輸入法，並加到你的語言清單。不需要網路。
3. 按 `Win + Space` 切換到「智慧輸入法」。

- 設定：開始功能表「智慧輸入法 設定」，或系統匣輸入法圖示按右鍵 →「設定…」。
- 移除：Windows 設定 → 應用程式 → 智慧輸入法（PIME 與其他 PIME 輸入法會保留）。
- 個人資料（設定、我的詞庫、學習記憶）在 `%APPDATA%\SmartIME`，安裝／移除都不會動到；
  換電腦用設定頁「資料與隱私」匯出成一個 `.smartime` 檔，在新電腦匯入（合併，不會覆蓋）。

## 怎麼打

| 動作 | 按鍵 |
|------|------|
| 打中文 | 直接用注音打（大千或倚天），按聲調鍵轉成中文 |
| 打英文 | 直接打，不用切換；未完成的注音會以原字母顯示，旁邊提示注音 |
| 選字 | `↓` 或 `↑` 叫出候選；`1–9` 直接選，`↑↓` 移動、`Enter` 確認、`←→` 翻頁、`Esc` 取消 |
| 換成別種解讀 | 候選窗跨類別：英文 `mvp` 可換成「勳」、`i␣`（喔）可換回英文 `i`、任何中文都可換回「原始按鍵」 |
| 修改前面的字 | `←` `→` 把游標移到字前面，提示框顯示「字 注音 ⌨ 按鍵」，再按 `↑`/`↓` 換字；或用下面的修正模式 |
| 接續詞 | 旁邊出現「xx ⇥Tab」時按 `Tab`；`Shift+Tab` 列出全部接續詞 |
| 符號面板 | 單按一下右 `Alt`：常用標點、括號、希臘字母、數學、箭頭、單位……；`Tab` 換分類 |
| 加到我的詞庫 | `Ctrl+D`：把游標前的中文（例如剛打好的朋友名字）加進我的詞庫；候選窗中按則加入目前這個候選 |
| 刪掉學錯的詞 | 候選窗停在那個詞上按 `Delete` |
| 送出 | `Enter`，或打句讀標點（，。？！：；）時自動送出 |
| 刪除 | `Backspace` 刪一個字（未完成的注音則刪一鍵） |
| 切換模式 | 單按右 `Shift`：英文 ⇄ 上次用的中文模式；系統匣圖示按右鍵選模式 |

### 修正模式（Vim 式）

組字中按 `Esc` 進入，字不會送出，按鍵變成指令（再按一次 `Esc` 才是清除整段）：

| 鍵 | 作用 | 鍵 | 作用 |
|----|------|----|------|
| `h` `l` | 左右移動 | `j` `k` | 換成下一個／上一個候選 |
| `v` | 切換檢視：國字 → 注音 → 按鍵 | `x` | 刪除（按鍵檢視中刪一鍵，可清掉雜鍵） |
| `e` | 這個字在中文／英文／原始按鍵之間切換 | `r` | 重打這個字 |
| `a` | 加到我的詞庫 | `u` | 復原 |
| `i` | 回到打字 | `Enter` | 送出 |

### 標點

全形標點（`"` 預設是半形，想要 ； 請用 `Ctrl+;`）：

| 按鍵 | 結果 | 按鍵 | 結果 |
|------|------|------|------|
| `Ctrl+,` 或 `Shift+,` | ， | `Ctrl+.` 或 `Shift+.` | 。 |
| `Ctrl+;` | ； | `Ctrl+Shift+;` 或 `Shift+;` | ： |
| `Ctrl+'` 或 `'` | 、 | `Ctrl+Shift+/` 或 `Shift+/` | ？ |
| `Ctrl+Shift+1` 或 `Shift+1` | ！ | `Ctrl+/` | … |
| `Ctrl+[` 或 `[` | 「 | `Ctrl+]` 或 `]` | 」 |
| `Ctrl+Shift+[` | 『 | `Ctrl+Shift+]` | 』 |
| `Ctrl+Shift+,` | 《 | `Ctrl+Shift+.` | 》 |
| `Ctrl+Shift+9` / `0` | （ ） | `Ctrl+-` | — |

`Ctrl+符號` 沿用微軟新注音／華碩的習慣，在中英自動與純中文模式有效；純英文模式時 `Ctrl+,`、`Ctrl+.` 照常交給應用程式（例如 VS Code）。
打錯寬度時，游標停在標點後按 `↓`：全形、半形與相關符號都在候選裡。哪些符號預設半形可以在設定頁改。

### 三種模式

| 模式 | 圖示 | 說明 |
|------|------|------|
| 中英自動（預設） | 自 | 不用切換，依整句判斷每段是中文還是英文 |
| 純中文 | 中 | 每個鍵都是注音（傳統注音輸入法的行為）；數字請用數字鍵盤 |
| 純英文 | 英 | 按鍵直接交給應用程式 |

右 `Shift` 預設在「英文 ⇄ 中文側模式」之間切換；設定頁可改成三種模式輪流。

### 打字容錯

- 同一個字的注音按鍵順序打反也能辨識（`k27` → 的、`8a3` → 碼），提示會顯示「將變成的」標準順序
- 快打時多按、或修正時殘留的單一字母會被略過（`我e更快` → 我更快）；被略過的鍵可從候選窗的「原始按鍵」找回
- `i␣`、`o␣` 依前後文判斷：`i am a good guy` 維持英文，`你想我喔`、`喔！好酷！` 變成中文

### 我的詞庫與學習

- 只從你**明確的選擇**學習（候選窗選字、Tab 接受、修正模式最後停下的字），不會從自動送出的文字亂學
- 設定頁「我的詞庫」可以新增、修改、分類（例如「朋友」放朋友的名字）、刪除；學錯的詞可以刪掉或封鎖
- 資料只存在這台電腦（`%APPDATA%\SmartIME\user.db`）

### 語音輸入（按住右 Ctrl 說話）

1. 設定頁 →「語音輸入」：第一次先按「安裝語音元件」（不需要系統管理員權限；下載約 110 MB，有 NVIDIA 顯示卡再加約 1.3 GB 的 CUDA 元件）
2. 下載模型：有 NVIDIA 顯示卡選 **Breeze-ASR-25**（3.1 GB，台灣華語與中英夾雜最準），沒有就選 **SenseVoice**（170 MB，CPU 也很快）
3. 打開「使用語音輸入」，在任何程式按住右 `Ctrl` 說話、放開，文字就打在游標位置

- 需要麥克風（藍牙耳機要先連上，Windows 才會有輸入裝置）；找不到時提示框會說明
- 全部在這台電腦上辨識，聲音不會上傳；只有按住右 `Ctrl` 時麥克風才會開啟
- 右 `Ctrl` 和其他鍵一起按（例如 `右Ctrl+C`）是一般快捷鍵，不會錄音
- 我的詞庫裡自己加的詞（朋友名字、專案術語）會提示辨識器，英文詞照你的拼法輸出
- 速度參考：RTX 4070 + Breeze-ASR-25，8.5 秒的話約 0.5 秒辨識完；i9-14900K + SenseVoice 約 0.15 秒

## 開發

```powershell
uv sync --group dev --group build-data          # 建立 .venv（Python 3.13）；要開發語音輸入再加 --group voice
uv run --group build-data python tools/build_data.py   # 建詞庫 -> data/generated/smartime.db
uv run pytest                                    # 測試
uv run python -m smartime.devtools.simulate --steps "ji3ap7{DOWN}"   # 不安裝也能模擬打字
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev      # 開發模式安裝（PIME 直接連到這個 repo）
powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1 [-Rebuild]   # 讓開發模式的輸入法載入新程式／新詞庫
uv run python tools/build_installer.py           # 產生 dist\SmartIME-Setup-<版本>.exe（需要 Inno Setup 6）
uv run python -m smartime.settings               # 開設定頁（本機網頁）
```

- 架構與交接說明：[docs/architecture.md](docs/architecture.md)
- 資料與授權：[docs/licenses.md](docs/licenses.md)
- 版本紀錄：[CHANGELOG.md](CHANGELOG.md)

## 專案結構

```
src/smartime/engine/    輸入引擎（純標準函式庫）：注音、鍵盤配置、詞庫、使用者詞庫、解碼器、session、修正模式、符號
src/smartime/pime/      PIME 後端協定（stdin/stdout JSON）與 text service 轉接
src/smartime/settings/  設定頁：本機 HTTP 伺服器 + 網頁介面（Edge／Chrome App 視窗）
src/smartime/voice/     語音輸入：按住右 Ctrl 錄音、本機辨識、打到游標位置（獨立行程）
src/smartime/devtools/  模擬器與實機測試（EDIT、RichEdit、Edge 打字；語音輸入）
backend/                PIME 看到的後端資料夾（server.py、settings.py、ime.json、圖示）
installer/              Inno Setup 安裝檔腳本與安裝時用的輔助程式
tools/                  建置工具（詞庫、圖示、安裝檔）
scripts/                開發用安裝 / 移除 / 重新載入腳本
data/lexicon/           我們自己維護的詞表（例：中英夾雜常用英文詞）
tests/                  pytest
docs/                   調查、架構、授權、設計稿
```
