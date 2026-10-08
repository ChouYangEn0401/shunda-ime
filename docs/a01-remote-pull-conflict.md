# remote 更新檢查與 pull（a01-remote-pull-conflict）

> 讀者：要同步這個 repo 的人，或接手這條線的工程師。
> 工具：`src/a01-remote-pull-conflict/remote_sync.py`。寫於 2026-10-09。

## 1. 要回答的問題，和這次實際的答案

原話：**「確認是否本專案有 remote 更新，然後 pull，如果有 conflict 要回報或者解決。」**

這次**沒有辦法回答**。不是「沒有更新」，是**問不到**：

| | |
|---|---|
| remote | `origin` → `https://github.com/ChouYangEn0401/shunda-ime.git` |
| 本機最後知道的 `origin/main` | `bd15cad`（commit 日期 2026-10-02） |
| 本機 `main` | `bd15cad`——跟上面一樣 |
| `origin/main` 的 reflog | 空的（這個 remote-tracking ref 從 clone 之後沒有被更新過） |
| 這次有連到 remote 嗎 | **沒有**

寫這份文件的 session 是在沙箱裡跑的，`git fetch`、`git ls-remote`、
連 GitHub API 的 `WebFetch` 全部都要人按核准，而那個 session 是非互動的，沒有人可以按。
所以本機能看到的最新資訊是 2026-10-02 的狀態，到 2026-10-09 之間 remote 有沒有動，**無從得知**。

**這個區別很重要，而且很容易被弄混**：一個連不到網路的 `git pull` 不會留下任何痕跡，
工作目錄看起來跟「已經是最新」一模一樣。所以下面的工具刻意把
「問過了，沒有新東西」和「沒問到」當成兩個不同的答案，用不同的離開碼（見 §3）。

## 2. 人要怎麼把這件事做完

在**能連到網路**的環境、在主 checkout（`C:\Users\user\Documents\_sandbox\shunda-ime`）跑：

```powershell
uv run python src/a01-remote-pull-conflict/remote_sync.py --branch main
```

它只看、不動任何檔案，然後告訴你：remote 有沒有新東西、新的是哪幾個 commit、
動到哪些檔案、以及**如果現在 pull 會不會衝突、哪些檔案會衝突**。

確定要拿進來：

```powershell
uv run python src/a01-remote-pull-conflict/remote_sync.py --branch main --pull
```

衝突的話它會列出衝突檔案並停在那裡等人處理；想要「先別留半完成的 merge」就加
`--abort-on-conflict`，它會 `git merge --abort` 把工作目錄還原。

> 注意：`main` 現在 checkout 在主 checkout 那邊，不在這條線的 worktree。
> 在 worktree 裡不能更新 `main`，要在主 checkout 跑。

## 3. 離開碼

寫在 `remote_sync.py` 開頭，給自動化判斷用，不用去解析文字：

| 常數 | 意思 |
|---|---|
| `EXIT_IN_SYNC` | **問到了**，而且沒有新東西 |
| `EXIT_UPDATES_AVAILABLE` | 有 commit 可以拿（只看模式） |
| `EXIT_CONFLICT` | 會衝突（只看模式）或已經衝突（`--pull`） |
| `EXIT_ERROR` | 問不到 remote、工作目錄不乾淨、或 git 失敗 |
| `EXIT_USAGE` | 不在 git repo 裡之類的呼叫錯誤 |

`EXIT_IN_SYNC` 只在**真的連上 remote 且沒有新東西**時才會回。
`--no-fetch` 永遠不會回 `EXIT_IN_SYNC`，因為它根本沒問——這正是 §1 那個陷阱。

## 4. 為什麼有時候快轉、有時候留 merge commit

擁有者的慣例是**合併分支一律留 merge commit**（`git merge --no-ff`）：
之後看歷史分得出「這一批是同一個功能、一起進來的」，要退也能整批退。

工具照這個慣例，但把兩種其實不同的操作分開：

- **分支自己有 commit**（兩邊都有東西）→ 這是真的在合併，用 `git merge --no-ff`，
  訊息寫併進來了什麼、為什麼留這個 merge commit。
- **分支自己沒有 commit**（例如 `main` 單純跟著 `origin/main`）→ 這是**同步**，不是合併一批功能。
  沒有「一批」要保持在一起，硬做 merge commit 只會憑空生一個空的，還讓這個分支
  **離開**它本來要鏡像的 upstream（之後每次 pull 都變成 merge）。所以這種情況快轉。

慣例裡「不要用 `--ff-only` 把功能分支直接接上主線」講的是前一種；後一種是鏡像 upstream，不受影響。

## 5. 衝突為什麼只回報、不自動解決

- **先預演再動手**：`git merge-tree --write-tree` 會在記憶體裡做一次合併，
  所以「會不會衝突」在完全沒碰工作目錄的情況下就能知道（需要 git ≥ `MERGE_TREE_MIN_GIT`；
  更舊的 git 會說「看不出來」，而不是假裝沒有衝突）。
- **不自動選邊**：衝突是內容上的決定，工具沒有任何依據知道哪一邊才對。
  自動挑一邊（`-X ours` / `-X theirs`）會安靜地丟掉另一邊的修改。
- 所以結果只有兩種：**留著等人處理**，或**整個放棄**（`--abort-on-conflict`）。
  不會有「解一半」的狀態。
- `--pull` 之前會先檢查工作目錄乾不乾淨，不乾淨就不動——不拿別人沒進版的修改去冒險。

## 6. 測試

```powershell
uv run pytest src/a01-remote-pull-conflict/test_remote_sync.py -v
```

`pyproject.toml` 的 `testpaths = ["tests"]` 不會自動收這個檔案，所以要指定路徑。
它放在被測的腳本旁邊，是因為這條線的檔案所有權只到
`src/a01-remote-pull-conflict/**` 和這份文件；`tests/` 是別人的。
**這件事要讓後面的人決定**：要不要把它搬到 `tests/`，變成一般 `uv run pytest` 會跑到的測試。

測試用的「remote」是同一個暫存目錄裡的 bare repo，用檔案路徑連——
真的在跑 fetch 和 merge，但完全不需要網路。
需要「壞掉的 remote」的那一個，把 URL 指到一個不存在的路徑。

比較有份量的是兩個假陰性：**連不到 remote** 和 **`--no-fetch`**，
兩種情況本機的 ref 都是舊的、看起來像已同步，而兩種都必須拒絕這樣回報。
寫第二個測試的時候抓到一個真的 bug：`--no-fetch` 原本會回 `EXIT_IN_SYNC`，
等於沒問卻說「沒有更新」。已經修掉。

### 這次沒有跑過

**上面兩行指令，寫這份文件的 session 一行都沒有跑過，不要當成已經驗證。**
這個 worktree 沒有 `.venv`，而沙箱只允許 `.venv\Scripts\python*`，
裸的 `python` 和 `pytest` 都會被擋；`git fetch` 同樣被擋。
所以這份交付是**讀過、沒跑過**的程式碼。請先跑 §6 的測試再信它。

## 7. 被否決的方案

- **直接在這條線上 `git pull`。** 兩個理由不行：這個節點的協定明文禁止 merge，
  而且 pull 會改到整個 repo 的檔案，遠超出這條線的檔案所有權（`src/a01-remote-pull-conflict/**`）。
  機械檢查會擋下來，也應該擋下來。
- **繞過沙箱去連網**（`dangerouslyDisableSandbox`、或在 Python 裡用 subprocess 偷跑 `git fetch`）。
  試過一次正規路徑被要求核准，就該停下來問人，而不是找路繞過同一個拒絕。
- **用 `-X ours` / `-X theirs` 自動解衝突。** 見 §5：會安靜地丟掉修改。
- **包成 `tools/` 下的腳本**（跟 `tools/set_version.py` 放一起，風格上其實比較對）。
  `tools/` 不屬於這條線，等人決定要不要搬（見 §6）。
- **只寫一份「人要跑哪幾行」的文件，不寫工具。** 文件不會把「問不到」和
  「沒有更新」分開——而那正是這次唯一真正踩到的坑。
