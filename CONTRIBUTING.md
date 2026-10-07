# 開發與交接

這份講**怎麼在這個專案上工作**：環境、測試、改完要驗什麼、怎麼出一版。
程式**為什麼長這樣**在 [docs/architecture.md](docs/architecture.md)。

---

## 1. 三十秒版本

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python tools\build_data.py      # 建詞庫 -> data\generated\smartime.db（約 30 MB）
.venv\Scripts\python -m pytest                # 應該全綠
.venv\Scripts\python -m smartime.devtools.simulate "ji3ap7{DOWN}"   # 不用安裝就能試打字
```

需要 [python.org 的 Python 3.13](https://www.python.org/downloads/windows/)（裝給自己就好，不用勾 PATH）。
套件版本全部釘在 `requirements.txt`（開發、測試、建置）與 `requirements-voice.txt`（語音輸入，選用，很大）。

> **不要用 uv 或其他套件管理器。** 這個專案只用標準的 `python -m venv` 加
> `requirements*.txt`，執行工具一律 `.venv\Scripts\python.exe`。

---

## 2. 改東西之前先知道的三件事

**一、引擎只用標準函式庫。** `src/smartime/engine/` 裡不可以 import 第三方套件，
也不可以 import Windows API。輸入法跑在一份 embeddable Python 上，那裡什麼都沒裝。
需要畫圖、需要 Win32 的東西放 `src/smartime/ui/`，需要協定的放 `src/smartime/pime/`。

**二、解碼器的權重是被測試釘住的。** `decoder.Weights` 裡每一個數字都影響
`tests/test_typing_corpus.py`——那是使用者真實的鍵盤紀錄配上他本來想打的字。
動了權重就要跑那個檔案，紅了就是真的讓別的情況變差了，不是測試太嚴。

**三、面板的繪圖程式可以畫到離屏點陣圖。** 所以 UI 改動看得到結果，
也所以文件裡的圖是程式產生的（§5）。

---

## 3. 重現一個 bug 回報

使用者回報的是「我打了這句話，結果變成那樣」。要先變成按鍵才能重現：

```powershell
# 一句中文 -> 打出它需要的按鍵
.venv\Scripts\python -m smartime.devtools.keyscript "當我們今天針對數據的第 i 項"
# 直接打給我看
.venv\Scripts\python -m smartime.devtools.keyscript --run "第 i 項"
# 自己拼按鍵，看每一鍵之後的狀態
.venv\Scripts\python -m smartime.devtools.simulate --steps "ji3ee/4dj94{ESC}h"
```

按鍵腳本的寫法：一般字元照打，具名鍵放在大括號裡——
`{BS} {DEL} {ENTER} {ESC} {TAB} {LEFT} {RIGHT} {UP} {DOWN} {HOME} {END} {SPACE}`、
`{PGUP} {PGDN}`、`{S-TAB}` `{S-LEFT}`（Shift 組合）、
`{NUM1}`–`{NUM9}`（數字鍵盤，NumLock 開）、`{KP1}`–`{KP9}`（同樣的鍵，NumLock 關）、
`{RCTRL}` `{RALT}`（單按一下）、`{C-d}` `{CS-/}`（Ctrl 組合）。

> `simulate` 預設用**暫存的**使用者資料夾，所以重現 bug 不會把測試字詞學進你自己的詞庫。
> 真的要用真詞庫才加 `--real-memory`。

重現出來以後，把那個案例加進測試再修。語料檔：

| 檔案 | 放什麼 |
|------|--------|
| `tests/test_typing_corpus.py` | 「這串按鍵應該變成這句話」的解碼語料 |
| `tests/test_correction_scenarios.py` | 整段修字的情境：打錯 → 進修正模式 → 改好 → 送出 |
| `tests/test_session.py` | 單一行為（某個鍵做某件事） |

---

## 4. 改完要驗什麼

單元測試是必要但不夠的——這個專案踩過的坑幾乎都是**單元測試看不到**的整合問題
（無效的 JSON 讓 PIME 整個起不來、IMM32 程式吃掉按鍵、面板視窗找不到錨點）。

| 改了什麼 | 至少要跑 |
|----------|---------|
| 任何東西 | `.venv\Scripts\python -m pytest` |
| 引擎、解碼器 | 上面 ＋ `tests/test_typing_corpus.py` 必須全綠 |
| PIME 協定、text service | ＋ `python -m smartime.devtools.pime_probe --require-conversion` |
| 面板、UI | ＋ `python -m smartime.devtools.panel_check out_dir`（實機，會打字到真的文字框） |
| 設定頁 | ＋ `python -m smartime.devtools.settings_shot out_dir --view <頁面>`（headless Edge，會回報 JS 錯誤） |
| 鍵盤處理 | ＋ `python -m smartime.devtools.tsf_typing_test`（EDIT＝IMM32 路徑）與 `--richedit`（TSF 路徑） |
| 安裝檔 | ＋ `tools\test_installer.ps1 -Setup <exe> -RestoreDev`（需系統管理員，一次 UAC） |

實機測試（`panel_check`、`tsf_typing_test`）**會真的在這台電腦上打字**。
它們會等電腦閒置 5 秒才開始、遇到真人輸入就中止、結束後還原原本的輸入法，
而且測試期間關閉學習。要在別人的機器上跑之前先說一聲。

測試絕對不可以送出真的輸入事件：`conftest.py` 設了
`SMARTIME_NO_SENDINPUT` 和 `SMARTIME_NO_PANEL`。

### 開發模式安裝

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev      # PIME 直接連到這個 repo（需管理員）
powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1        # 改了程式以後重新載入
powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1 -Rebuild   # 連詞庫一起重建
```

後端在被使用時會一直握著 `smartime.db`，所以 `dev-reload` 會先停掉
PIMELauncher、做完事再用 `explorer.exe` 重新啟動它（這樣它不屬於這個主控台）。

---

## 5. 文件裡的圖

```powershell
.venv\Scripts\python tools\make_docs_images.py          # -> docs\images\
.venv\Scripts\python tools\make_docs_images.py --dark   # 連深色主題一起
```

圖是用輸入法**自己的繪圖程式**和**真正的設定頁**產生的，不是手動擷取。
動了面板或設定頁的外觀，跑一次這個，`docs/index.html` 和 README 的圖就跟著對了。

---

## 6. 出一版

### 版本號怎麼取

正式版是乾淨的 `0.8.0`。**還在測的東西不要佔用那個號碼**，用前置版本：

```
0.8.0-alpha.1   自己或使用者在試的建置，可能一天好幾個
0.8.0-alpha.2
0.8.0-rc.1      準備要發了，只差最後確認
0.8.0           正式版
```

- 在 GitHub 發佈前置版本時**一定要勾「Set as a pre-release」**。
  `releases/latest` 的定義就是「最新的、沒有被標成 pre-release 的版本」，
  所以設定頁的「檢查更新」不會把 alpha 推給一般使用者；而跑 alpha 的人在正式版
  出來時照樣會被通知（`update.version_tuple` 的排序：
  `0.7.0 < 0.8.0-alpha.3 < 0.8.0-rc.1 < 0.8.0`）。
- `pyproject.toml` 會自動寫成 Python 工具認得的拼法（`0.8.0a1`），其他地方維持
  SemVer 的寫法。`set_version.py` 會處理，不用自己改。
- CHANGELOG 的小節用正式版號（`## 0.8.0`），alpha 階段一直往那一節裡補。

```powershell
.venv\Scripts\python tools\set_version.py                  # 看目前版本
.venv\Scripts\python tools\set_version.py 0.8.0-alpha.1    # 一次改好所有地方
.venv\Scripts\python tools\build_installer.py              # -> dist\ShundaIME-Setup-<版本>.exe（需 Inno Setup 6）
```

`build_installer.py` 會下載並用 SHA-256 核對釘住的第三方檔案
（PIME 1.3.0 的安裝檔、python.org 的 embeddable Python、Inno Setup 的中文訊息檔），
從 PIME 安裝檔裡取出**核心三個檔案**，再編譯 `installer/smartime.iss`。
PIME 官方安裝檔本身不會被散佈，也不會被執行——它會連帶裝上新酷音等其他輸入法。

出版本前：

1. `tools\test_installer.ps1 -Setup dist\...exe -RestoreDev`（乾淨安裝、takeover、移除後未重開機重裝）
2. 更新 `CHANGELOG.md`
3. 打 tag、推上去、在 GitHub 上發佈 Release 並附上安裝檔
   （設定頁的「檢查更新」看的就是 Releases API 的 `tag_name` 和 `.exe` 附件）

> 沒有被要求就不要改版本號，也不要覆蓋 `dist/` 裡已經發佈過的檔案。

---

## 7. Commit 的規矩

一個主題一包，做完就 commit，不要累積成一大包。
每一則訊息都要說清楚**做了什麼**和**為什麼這樣決定**（繁體中文）：

```
fix(decoder): 兩邊有空白的單一字母維持英文，不吃掉當聲調的空白

做了什麼
- 解碼器的英文邊多一個 delimited 判斷：…

決策緣由
使用者回報「第 i 項」會變成「第 喔 項」：ㄧ／ㄛ 加上當第一聲的空白，
分數贏過只有一個字母的英文。…
```

一年後有人用 `git log` 找「這行為什麼是這樣」的時候，答案要在訊息裡。

---

## 8. 容易踩的坑

- **任何外部程式要解析的檔案都要驗過。** `ime.json` 給 jsoncpp 讀：不能有 BOM，
  escape 必須合法。寫含有反斜線的檔案（JSON 路徑、Windows 路徑、regex、PS1）
  不要用 shell heredoc，它會把 `\\` 吃成 `\`——用編輯器寫，寫完 `json.loads` 驗一次。
- **PIME 的 `KeyEvent::scanCode()` 是壞的**（忘了把 lParam 右移 16 位，永遠回傳 0）。
  要分辨數字鍵盤和專用方向鍵區只能靠 `isExtended`。
- **PIME 每次 `showMessage` 都會砍掉重建提示視窗**，所以不要把會變的東西放進去。
  我們只送一個固定的空白字元，把那個視窗當成定位錨點（它是這個行程唯一知道
  游標在哪的管道），畫面由 `smartime.ui` 自己畫。
- **實驗性功能要是開關、預設關閉**，並且在自己的分支上開發、用一次 `--no-ff` merge
  進來，這樣整包 revert 得掉。
- **內部代號 `smartime` 不要改。** Python 套件、PIME 後端資料夾、
  `%APPDATA%\SmartIME`、GUID 都用它；改了使用者的設定和詞庫就接不上。
