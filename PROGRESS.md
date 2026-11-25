## 第四輪（2026-11-25）：artifact 流程 ＋ release 連結

| 項目 | 狀態 | 說明 |
|---|---|---|
| 為什麼沒照 protocol 做 | ✅ 答覆 | 誠實答：沒想到。描述測試顯示描述不是主因（新舊都 6/6 觸發、0 誤觸）；缺的是「改之前」的提醒與順序檢查 |
| 憲章 §5、Shunda CLAUDE.md §1 一行 | ✅ | 指向 knowledge 全文；記憶 `artifact-sync-first-not-after` |
| hook `artifact-sync-guard.js` ＋ ack | ✅ 已裝 | 單元 22 項、端到端 13 步全過；裝到 `~/.claude/hooks`，`settings.json` 加一條（命令用 node 絕對路徑，這台 PATH 沒有 node） |
| 測試報告、ADR-0012 | ✅ | `docs/reports/skills/2026-11-25_…`、`docs/tech-book/adr/0012-…`；home-kit 分支合回 main（--no-ff），**未 push** |
| 新 skill 描述 | ⏳ 待你貼 | `knowledge/account-skills/artifact-sync-protocol/PROPOSED-SKILL.md`（skill 是網站同步的，我改不了） |
| 首頁 release 連結 | ⏳ 進行中 | alpha.5 pre-release、v0.10.1 正式版有安裝檔；照 protocol 由 subagent 更新 |

**要你知道的**
- 這台 PATH 沒有 node：範本 `settings.template.json` 寫的是 `node`，要在機器事實檔改。
- 測試過程中我寫錯兩次期望值（都已修正，沒有改程式）；一次測試紅燈是因為 PATH，已改用 `process.execPath`。

# 進度（2026-11-24）

## 第三輪：alpha.4 實機測試 → alpha.5

| 軌道／項目 | 狀態 | 說明 | 最後更新 |
|---|---|---|---|
| 實機測試 alpha.4（你裝的） | ✅ 全過 | EDIT／RichEdit 都過：反白＋單按 Ctrl 修好了（RichEdit「好們」，alpha.3 是「我好們」）、＠＃＄％＆＊、閒置 Ctrl+- 交給程式、↓ 換全形、注音、頁碼、整理建議頁 | 2026-11-24 |
| 測試工具兩個小毛病 | ✅ | tsf_typing_test 打不出 @ 等 Shift 符號；panel_check 不認得靠游標的閒置面板（`0925be0`） | 2026-11-24 |
| 標點表顯示 | ✅ | @ # $ % & * 也標「↓ ＠」；空格子改顯示「·」，不再和 Ctrl+- 的「—」一樣（`84df62e`） | 2026-11-24 |
| 發版 alpha.5 | ✅ | `dist/ShundaIME-Setup-0.11.0-alpha.5.exe`；660 passed；main、標籤已 push；Artifact v43 | 2026-11-24 |
| 安裝 alpha.5 | ✅ | 你裝好了 | 2026-11-24 |
| 實機測試 alpha.5 | ✅ 全過 | EDIT／RichEdit 標準測試全過；Edge（Chromium）裡反白＋單按 Ctrl 也保得住反白（textarea、contenteditable 都是「好們」） | 2026-11-24 |
| Edge 測試工具 | ✅ | 隔離 Edge（不登入、不同步擴充功能）、補一個 Enter；實跑 0 FAIL（`9093c74`） | 2026-11-24 |

## 第二輪：照建議全部做（0.11.0-alpha.4）

| 軌道／項目 | 狀態 | 說明 | 最後更新 |
|---|---|---|---|
| 實機測試 alpha.3（你裝的） | ✅ | pime_probe、tsf_typing_test EDIT／RichEdit 各 28/28、panel_check 9/9、alpha.2 的功能全過。找到 2 個 bug（下面兩列） | 2026-11-24 |
| bug：RichEdit／Word 反白後單按 Ctrl 反白被收成游標 | ✅ 修了（沒實機驗） | 有系統游標的程式，面板直接靠在游標下面、不送 PIME 提示訊息（`a6f1ec7`） | 2026-11-24 |
| bug：設定頁「一般」露出原始 HTML | ✅ | alpha.3 精簡文字時把 `<a` 寫成 `< `；修好並加測試（`82f22bd`） | 2026-11-24 |
| Ctrl+A／Ctrl+← 慢 1.2 秒 | ✅ 查清楚，不用改 | 是測試工具自己掛的鍵盤 hook 造成的，平常使用不會發生 | 2026-11-24 |
| 標點（方案 A） | ✅ | Ctrl+Shift+2 3 4 5 7 8 打 ＠＃＄％＆＊；任何符號 ↓ 都有全形；刪節號 ↓ 有 ‧（`20ef38b`、紅點 `4f4d5ae`） | 2026-11-24 |
| Ctrl+- 和 Ctrl+/ | ✅ | 只在打字中才是 — 和 …，沒在打字時交給程式（縮小、切換註解） | 2026-11-24 |
| 整理建議（不用 AI） | ✅ | 我的詞庫多一組：只用過一次且 14 天沒用又不是詞、90 天沒用、英文像打錯；勾選刪除（`ece0baa`、`3129ba6`） | 2026-11-24 |
| 打開「學習」 | ❌ 沒做 | 工具不准我改你的設定檔；請到設定頁「智慧修正 → 記住我選的字」打開 | 2026-11-24 |
| 發版 alpha.4 | ✅ | `dist\ShundaIME-Setup-0.11.0-alpha.4.exe`（sha256 `8b680fd8…2ba2559d`）；660 passed；main、標籤 `v0.11.0-alpha.4` 已 push | 2026-11-24 |
| 安裝 alpha.4 | ✅ | 你裝好了 | 2026-11-24 |
| 首頁 Artifact | ✅ | 照 protocol：rev .4 → .5（上鎖）→ .6（發佈＋釋放），線上 v41 | 2026-11-24 |
| 實機測試 alpha.4 | ✅ | 見第三輪 | 2026-11-24 |

## 第一輪（0.11.0-alpha.3）

全部完成：alpha.2 實機測試沒有產品 bug；設定頁文字精簡（Fable 審核 38 項）；標點盤點（`PunctInventory.md`）；測試工具三個小修；「注音」組說明更正；alpha.3 發版、push；Artifact v39。

## 問題（還在的）
- GitHub Release 沒建（這台沒有 gh）：alpha.3、alpha.4 的標籤都已 push，要的話你在 GitHub 上建 Release 並上傳安裝檔。

## 待決策
- 整理建議的「只用過一次」也套用在英文（14 天前只用過一次的 `venv` 會被列出來）。建議預設：維持；你覺得吵就改成英文只看「像打錯」。
- 整理建議刪除前會再問一次（「刪了就不能復原」）。建議預設：維持，因為真的不能復原。
- 標點盤點裡還沒決定的：——／…… 一鍵出兩個、“ ” 放哪個鍵、英文模式要不要打中文標點、拼音／倉頡的單按全形要不要跟注音一致。建議預設：先不動，用一陣子再說。
