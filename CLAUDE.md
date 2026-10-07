# 給 Claude 的專案規則

這份是**每次**在這個 repo 工作都要遵守的規則。怎麼開發見
[CONTRIBUTING.md](CONTRIBUTING.md)，程式為什麼長這樣見
[docs/architecture.md](docs/architecture.md)。

---

## 1. 專案首頁一定要有本機版本，而且兩邊同步

`docs/index.html` 是**唯一**的首頁原始檔。它同時是：

- repo 裡的本機版本（直接用瀏覽器開得起來，不需要網路、不需要伺服器）
- GitHub Pages 的首頁（Settings → Pages → deploy from branch `main` / `/docs`）
- 發佈出去的 Artifact

**改了就三邊一起更新，不可以只改其中一邊。** 發佈 Artifact 時用同一個檔案路徑
（這樣會更新同一個網址，不會長出第二個頁面），並且把 `docs/images/` 底下用到的圖
一起當附帶檔案送上去。

```
Artifact(file_path="docs/index.html", root="docs",
         files={"images/xxx.png": "images/xxx.png", ...})
```

頁面裡的文件連結一律用 **GitHub 的絕對網址**，不要用 `install.md` 這種相對路徑：
相對路徑在 Artifact 裡沒有東西可以指，在 GitHub Pages 上也會因為 Jekyll 把 `.md`
轉成 `.html` 而失效。

## 2. 文件裡的圖都是程式產生的

不要手動截圖。跑：

```powershell
.venv\Scripts\python tools\make_docs_images.py
```

它用輸入法**自己的繪圖程式**（`smartime.ui.panels`）和**真正的設定頁**產生
`docs/images/` 底下所有的圖。動了面板外觀、設定頁、或版本號，就重跑一次，
然後重新發佈 Artifact。文件和產品因此不會偷偷脫節。

## 3. 開發環境只用標準 venv

`python -m venv .venv` ＋ `requirements*.txt`，執行工具一律 `.venv\Scripts\python.exe`。
**不要引進 uv 或其他套件管理器**，文件和腳本裡也不要出現。

## 4. Commit 一個主題一包

做完一個主題就 commit，不要累積。訊息要寫「做了什麼」和「決策緣由」（繁體中文），
一年後用 `git log` 要看得懂為什麼。沒有被要求不要改版本號、不要覆蓋 `dist/` 裡
已發佈的檔案、不要 push。

## 5. 改完要自己驗

單元測試是必要但不夠的。對照 [CONTRIBUTING.md](CONTRIBUTING.md) §4 的表跑該跑的
實機測試，改完把新版裝起來給使用者。實機測試會在這台電腦上真的打字——跑之前先在
訊息裡說一聲。

## 6. 不要手寫含反斜線的檔案到 shell heredoc 裡

Git Bash 的 heredoc 會把 `\\` 吃成 `\`，曾經寫壞 `ime.json` 害輸入法起不來。
JSON、Windows 路徑、regex、PS1、Python escape 一律用編輯工具寫，寫完驗一次。

## 7. 不進版本控制

`bug_fix.txt`（使用者的回饋草稿）。
