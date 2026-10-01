# 智慧輸入法 (Smart IME)

免切換中英混打的注音輸入法（Windows）。打字手感參考華碩智慧輸入法：字母先出現、旁邊顯示注音提示、按聲調鍵轉成中文、Tab 接續；
底層改用「整句重新解碼」的 lattice 解碼器，目標是從根本解決順序錯、多按、誤判英文等問題，並整合本地語音輸入。

> 狀態：**Phase 4 進行中**。已完成：注音順序容錯、數字鍵音節、Ctrl+符號標點、長句穩定性、快打雜鍵略過、跨類別換字、三種輸入模式。進行中：個人學習與刪除錯誤記憶、分類詞庫、修正模式。
> 調查報告：[docs/research/phase0-1-research.md](docs/research/phase0-1-research.md)

## 安裝（Windows 10/11）

需要：網路（第一次會下載 PIME 與一個私有的 Python 執行環境）、系統管理員權限（只有註冊輸入法那一步）。

```powershell
# 一般安裝（複製到 PIME 資料夾）
powershell -ExecutionPolicy Bypass -File scripts\install.ps1

# 開發模式（PIME 直接連到這個 repo，改完程式在系統匣 PIME 圖示選「Restart PIME」即生效）
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev
```

安裝後按 `Win + Space` 切換到「智慧輸入法」（系統匣圖示：智＝中英自動、中＝純中文、英＝純英文）。移除：`scripts\uninstall.ps1`。

個人資料（設定、日後的學習詞庫）都在 `%APPDATA%\SmartIME`，安裝/移除都不會動到；換電腦時整個資料夾帶走即可（Phase 7 會加匯出/匯入）。

## 怎麼打

| 動作 | 按鍵 |
|------|------|
| 打中文 | 直接用大千注音打，按聲調鍵（空白/ˊ/ˇ/ˋ/˙）轉成中文 |
| 打英文 | 直接打，不用切換；未完成的注音會以原字母顯示，旁邊提示注音 |
| 選字 | `↓` 或 `↑` 叫出候選；`1–9` 直接選，`↑↓` 移動、`Enter` 確認、`←→` 翻頁、`Esc` 取消 |
| 換成別種解讀 | 候選窗跨類別：英文 `mvp` 可換成「勳」、`i␣`（喔）可換回英文 `i`、任何中文都可換回「原始按鍵」 |
| 修改前面的字 | `←` `→` 把游標移到要改的字前面，提示框會顯示「字 注音 ⌨ 按鍵」（有被略過的雜鍵會標出），再按 `↑`/`↓` 換字 |
| 接續詞（自動完成） | 旁邊出現「xx ⇥Tab」時按 `Tab` |
| 送出 | `Enter`，或打句讀標點（，。？！：；）時自動送出 |
| 刪除 | `Backspace` 刪一個字（未完成的注音則刪一鍵）；`Esc` 清除整段 |
| 切換模式 | 單按右 `Shift`：英文 ⇄ 上次用的中文模式；系統匣圖示按右鍵選「中英自動／純中文／純英文」 |

全形標點（兩種都可以；`"` 預設是半形，想要 ； 請用 `Ctrl+;`）：

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

`Ctrl+符號` 沿用微軟新注音／華碩的習慣，在中英自動與純中文模式有效；切到純英文模式時 `Ctrl+,`、`Ctrl+.` 會照常交給應用程式（例如 VS Code 的設定、Quick Fix）。
打錯寬度時，游標停在標點後按 `↓`：全形、半形與相關符號（`"` → ； “ ” 「 」）都在候選裡。

三種模式：

| 模式 | 圖示 | 說明 |
|------|------|------|
| 中英自動（預設） | 智 | 不用切換，依整句判斷每段是中文還是英文 |
| 純中文 | 中 | 每個鍵都是注音（傳統注音輸入法的行為）；數字請用數字鍵盤 |
| 純英文 | 英 | 按鍵直接交給應用程式 |

打字容錯：

- 同一個字的注音按鍵順序打反也能辨識（`k27` → 的、`8a3` → 碼），提示會顯示「將變成的」標準順序
- 快打時多按、或修正時殘留的單一字母會被略過（`我e更快` → 我更快）；被略過的鍵可從候選窗的「原始按鍵」找回
- `i␣`、`o␣` 依前後文判斷：`i am a good guy` 維持英文，`你想我喔`、`喔！好酷！` 變成中文

## 開發

```powershell
uv sync --group dev --group build-data          # 建立 .venv（Python 3.13）
uv run --group build-data python tools/build_data.py   # 建詞庫 -> data/generated/smartime.db
uv run pytest                                    # 測試
uv run python -m smartime.devtools.simulate --steps "ji3ap7{DOWN}"   # 不安裝也能模擬打字
powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1 [-Rebuild]   # 讓已安裝(-Dev)的輸入法載入新程式／新詞庫
```

- 架構與交接說明：[docs/architecture.md](docs/architecture.md)
- 資料與授權：[docs/licenses.md](docs/licenses.md)
- 版本紀錄：[CHANGELOG.md](CHANGELOG.md)

## 專案結構

```
src/smartime/engine/    輸入引擎（純標準函式庫）：注音、鍵盤配置、詞庫、解碼器、session
src/smartime/pime/      PIME 後端協定（stdin/stdout JSON）與 text service 轉接
src/smartime/devtools/  模擬器等開發工具
backend/                PIME 看到的後端資料夾（server.py、ime.json、圖示；runtime/ 為安裝時下載）
tools/                  建置工具（詞庫、圖示）
scripts/                安裝 / 移除腳本
data/lexicon/           我們自己維護的詞表（例：中英夾雜常用英文詞）
tests/                  pytest
docs/                   調查、架構、授權文件
```
