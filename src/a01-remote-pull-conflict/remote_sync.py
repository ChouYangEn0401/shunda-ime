"""Answer "does origin have commits we have not pulled yet?", then pull them.

    uv run python src/a01-remote-pull-conflict/remote_sync.py                     # only look; changes nothing
    uv run python src/a01-remote-pull-conflict/remote_sync.py --pull              # look, then bring them in
    uv run python src/a01-remote-pull-conflict/remote_sync.py --pull --abort-on-conflict
    uv run python src/a01-remote-pull-conflict/remote_sync.py --branch main --upstream origin/main

Why a script instead of just ``git pull``: three things about ``git pull`` are
easy to get wrong by hand and matter here.

1. **"No update" and "I could not ask" look the same.** A ``git pull`` that
   cannot reach the network leaves the work tree looking perfectly in sync. This
   script separates 已同步 (asked, nothing new) from 無法確認 (could not ask) and
   gives them different exit codes, so neither a human nor a pipeline reads an
   offline run as "we are up to date".
2. **Conflicts can be known before touching the work tree.** ``git merge-tree``
   performs the merge in memory, so the check mode reports exactly which files
   would conflict while the work tree stays untouched.
3. **Fast-forward vs merge commit is a convention decision**, not a detail — see
   ``pull_or_report`` and docs/a01-remote-pull-conflict.md §4.

Conflicts are reported, never auto-resolved: picking a side is a content
decision, and this script has no way to know which side is right. A conflicted
merge is either left in place for a human to finish, or undone entirely with
``--abort-on-conflict`` -- never half-resolved.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Exit codes, so a pipeline can branch on the answer without parsing the text.
EXIT_IN_SYNC = 0  # asked the remote; nothing to pull
EXIT_ERROR = 1  # could not ask (offline / no permission), or git refused
EXIT_USAGE = 2  # wrong invocation
EXIT_UPDATES_AVAILABLE = 10  # there are commits to pull (check mode only)
EXIT_CONFLICT = 20  # pulling conflicts (predicted in check mode, hit in --pull mode)

# `git merge-tree --write-tree` landed in 2.38 and `--name-only` in 2.40. Below
# that we still report the update, just without the conflict preview.
MERGE_TREE_MIN_GIT = (2, 40)


def git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    """Run git and return (exit code, output). Never raises on a git failure.

    ``core.quotepath=false`` keeps non-ASCII paths readable instead of
    ``\\344\\275\\240`` escapes, which matters for a repo with Chinese filenames.
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def git_out(*args: str, cwd: str | None = None) -> str:
    """Run git for its output; empty string if it failed."""
    code, out = git(*args, cwd=cwd)
    return out if code == 0 else ""


def git_version() -> tuple[int, ...]:
    raw = git_out("--version").removeprefix("git version ")
    parts: list[int] = []
    for piece in raw.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def resolve_branch(repo: str, wanted: str | None) -> str:
    """The local branch to bring up to date (default: whichever is checked out)."""
    if wanted:
        return wanted
    branch = git_out("symbolic-ref", "--short", "HEAD", cwd=repo)
    if not branch:
        raise SystemExit("HEAD 不在任何分支上（detached）：用 --branch 指定要更新哪一個分支")
    return branch


def resolve_upstream(repo: str, branch: str, remote: str, wanted: str | None) -> str:
    """Which remote ref `branch` should follow.

    Order: what the caller asked for, then the branch's own tracking ref, then
    the remote's default head. Guessing beyond that would risk merging the wrong
    line of history, so instead we stop and say so.
    """
    if wanted:
        return wanted
    tracked = git_out("rev-parse", "--symbolic-full-name", f"{branch}@{{upstream}}", cwd=repo)
    if tracked:
        return tracked.removeprefix("refs/remotes/")
    head = git_out("symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD", cwd=repo)
    if head:
        return head
    raise SystemExit(
        f"分支 {branch} 沒有設定 upstream，也問不到 {remote} 的預設分支：\n"
        f"  用 --upstream {remote}/<分支> 指定，或 git branch -u {remote}/<分支> {branch}"
    )


def ahead_behind(repo: str, branch: str, upstream: str) -> tuple[int, int]:
    """(behind, ahead): commits only on the upstream, commits only on the branch."""
    out = git_out("rev-list", "--left-right", "--count", f"{upstream}...{branch}", cwd=repo)
    if not out:
        raise SystemExit(f"比不出 {upstream} 和 {branch} 的差距：確認兩個 ref 都存在")
    behind, ahead = out.split()
    return int(behind), int(ahead)


def conflict_preview(repo: str, branch: str, upstream: str) -> list[str] | None:
    """Files that would conflict, without touching the work tree.

    ``None`` means "could not tell" (git too old, or merge-tree errored) — which
    is deliberately not the same answer as ``[]``, "no conflicts".
    """
    if git_version() < MERGE_TREE_MIN_GIT:
        return None
    code, out = git("merge-tree", "--write-tree", "--name-only", branch, upstream, cwd=repo)
    if code == 0:
        return []
    if code != 1:  # 128 and friends: not a conflict answer, an error
        return None
    # Output is: tree oid, then one conflicted path per line, then a blank line
    # and free-text messages. Stop at the blank line and drop the oid.
    lines = out.splitlines()
    paths: list[str] = []
    for line in lines[1:]:
        if not line.strip():
            break
        paths.append(line.strip())
    return paths


def describe_incoming(repo: str, branch: str, upstream: str) -> None:
    print(f"\n要併進來的 commit（{branch}..{upstream}）：")
    for line in git_out("log", "--oneline", "--no-decorate", f"{branch}..{upstream}", cwd=repo).splitlines():
        print(f"  {line}")
    changed = git_out("diff", "--name-status", f"{branch}...{upstream}", cwd=repo).splitlines()
    print(f"\n它們動到的檔案（{len(changed)} 個）：")
    for line in changed:
        print(f"  {line}")


def report_conflicts(paths: list[str], *, predicted: bool) -> None:
    when = "如果現在 pull，這些檔案會衝突" if predicted else "這些檔案衝突了"
    print(f"\n⚠ {when}（{len(paths)} 個）：")
    for path in paths:
        print(f"  {path}")


def fetch(repo: str, remote: str, upstream: str) -> bool:
    """Update remote-tracking refs; says whether the remote was actually reached.

    Reports the before/after of the upstream ref, so "the fetch worked and
    nothing moved" is visible as its own outcome.
    """
    before = git_out("rev-parse", "--verify", "--quiet", upstream, cwd=repo)
    code, out = git("fetch", "--prune", remote, cwd=repo)
    if code != 0:
        print(f"✗ 連不到 {remote}：")
        for line in out.splitlines():
            print(f"    {line}")
        return False
    after = git_out("rev-parse", "--verify", "--quiet", upstream, cwd=repo)
    if before != after:
        print(f"✓ fetch 完成：{upstream} {before[:7] or '（原本沒有）'} → {after[:7]}")
    else:
        print(f"✓ fetch 完成：{upstream} 沒有動（還是 {after[:7] or '不存在'}）")
    return True


def tracking_summary(repo: str) -> None:
    """Every local branch against its upstream -- the "本專案" view, not just one branch."""
    fmt = "%(refname:short)\t%(upstream:short)\t%(upstream:track)"
    rows = [r.split("\t") for r in git_out("for-each-ref", f"--format={fmt}", "refs/heads", cwd=repo).splitlines()]
    print("\n本機分支 vs upstream：")
    for name, upstream, track in rows:
        if not upstream:
            print(f"  {name:34} （沒有 upstream）")
        else:
            print(f"  {name:34} {upstream:22} {track or '[已同步]'}")


def pull_or_report(repo: str, branch: str, upstream: str, behind: int, ahead: int, abort: bool) -> int:
    """Bring `upstream` into `branch`, choosing fast-forward vs merge commit.

    The owner's convention is that **merging a branch always makes a merge
    commit** (``--no-ff``), so a batch of work stays identifiable and revertable.
    That applies when both sides have commits, and this does make a merge commit
    then. A branch with no commits of its own is a different operation: there is
    no batch to keep together, and forcing a merge commit would invent an empty
    one and push the branch *off* the upstream it is meant to mirror. So that
    case fast-forwards. See docs/a01-remote-pull-conflict.md §4.
    """
    dirty = git_out("status", "--porcelain", cwd=repo)
    if dirty:
        print("\n✗ 工作目錄不乾淨，不敢動它。先 commit 或收好這些改動：")
        for line in dirty.splitlines():
            print(f"  {line}")
        return EXIT_ERROR

    if ahead == 0:
        print(f"\n{branch} 沒有自己的 commit → 直接快轉（這是同步，不是合併一批功能）")
        code, out = git("merge", "--ff-only", upstream, cwd=repo)
    else:
        print(f"\n{branch} 另有 {ahead} 個本地 commit → 兩邊都有東西，做一個 merge commit（--no-ff）")
        subjects = git_out("log", "--format=%s", f"{branch}..{upstream}", cwd=repo).splitlines()
        message = (
            f"merge: 併入 {upstream} 的 {behind} 個更新\n\n"
            f"{branch} 另有 {ahead} 個本地 commit，所以留一個 merge commit，"
            "之後看歷史分得出這一批是一起進來的，要退也能整批退。\n\n"
            "併進來的：\n" + "\n".join(f"- {s}" for s in subjects) + "\n"
        )
        code, out = git("merge", "--no-ff", "-m", message, upstream, cwd=repo)

    if code == 0:
        print(f"✓ {branch} 已經更新到 {git_out('rev-parse', '--short', branch, cwd=repo)}")
        for line in out.splitlines():
            print(f"    {line}")
        return EXIT_IN_SYNC

    conflicted = git_out("diff", "--name-only", "--diff-filter=U", cwd=repo).splitlines()
    if not conflicted:
        print("\n✗ merge 失敗，但不是衝突：\n    " + "\n    ".join(out.splitlines()))
        return EXIT_ERROR

    report_conflicts(conflicted, predicted=False)
    if abort:
        git("merge", "--abort", cwd=repo)
        print("\n已經 git merge --abort，工作目錄回到 merge 之前的樣子。沒有東西需要善後。")
    else:
        print(
            "\nmerge 停在這裡等人處理（刻意不自動選邊）。接下來：\n"
            "  git diff --diff-filter=U            # 看衝突內容\n"
            "  # 改好每個檔案，然後\n"
            "  git add <檔案> && git commit        # 完成這個 merge\n"
            "  git merge --abort                   # 或者整個放棄，回到 merge 之前"
        )
    return EXIT_CONFLICT


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="確認 remote 有沒有本機還沒拿的更新，然後（加 --pull）把它拿進來。",
        epilog=f"離開碼：{EXIT_IN_SYNC} 已同步 / {EXIT_UPDATES_AVAILABLE} 有更新可拿 / "
        f"{EXIT_CONFLICT} 會衝突或已衝突 / {EXIT_ERROR} 問不到或 git 失敗",
    )
    parser.add_argument("--pull", action="store_true", help="真的把更新併進來（預設只看不動）")
    parser.add_argument("--abort-on-conflict", action="store_true", help="衝突就整個放棄，不留半完成的 merge")
    parser.add_argument("--remote", default="origin", help="要問哪個 remote（預設 origin）")
    parser.add_argument("--branch", help="要更新哪個本機分支（預設：現在 checkout 的）")
    parser.add_argument("--upstream", help="要跟哪個 remote ref 比（預設：該分支的 upstream）")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help=f"不連線，只用本機上次抓到的狀態（會過時，所以永遠不會回 {EXIT_IN_SYNC}）",
    )
    args = parser.parse_args(argv)

    repo = git_out("rev-parse", "--show-toplevel")
    if not repo:
        print("✗ 這裡不是 git repo")
        return EXIT_USAGE

    branch = resolve_branch(repo, args.branch)
    upstream = resolve_upstream(repo, branch, args.remote, args.upstream)
    print(f"repo     {repo}\n分支     {branch}\nupstream {upstream}")
    print(f"remote   {git_out('remote', 'get-url', args.remote, cwd=repo) or '（問不到 URL）'}\n")

    # Why this is tracked as a reason rather than a bool: every "nothing to
    # pull" line below has to say whether we actually asked. Exit code 0 is
    # reserved for "asked, and there is nothing new" -- never for "did not ask".
    stale_reason: str | None = None
    if args.no_fetch:
        stale_reason = "這次沒有問 remote（--no-fetch）"
        print("⚠ --no-fetch：沒有問 remote，下面用的是本機上次抓到的狀態，可能已經過時。")
    elif not fetch(repo, args.remote, upstream):
        stale_reason = "這次連不到 remote"

    behind, ahead = ahead_behind(repo, branch, upstream)
    tracking_summary(repo)

    if behind == 0:
        state = "已經同步" if ahead == 0 else f"本機多 {ahead} 個 commit，remote 沒有新東西"
        print(f"\n{'·' if stale_reason else '✓'} {branch}：{state}")
        if stale_reason:
            print(f"  ⚠ 但{stale_reason}，所以這句話只代表「上次抓到的狀態」，"
                  "不是「現在確定沒有更新」。")
            return EXIT_ERROR
        return EXIT_IN_SYNC

    print(f"\n● {branch} 落後 {upstream} {behind} 個 commit" + (f"，自己另有 {ahead} 個" if ahead else ""))
    describe_incoming(repo, branch, upstream)

    preview = conflict_preview(repo, branch, upstream)
    if preview is None:
        print("\n· 這個 git 版本看不出會不會衝突（需要 git >= "
              f"{'.'.join(map(str, MERGE_TREE_MIN_GIT))}），只能實際 merge 才知道。")
    elif preview:
        report_conflicts(preview, predicted=True)
    else:
        print("\n✓ 預演過了：這個 merge 不會衝突。")

    if stale_reason:
        print(f"\n⚠ {stale_reason}，上面是舊資料；問得到 remote 之後再跑一次。")
        return EXIT_ERROR

    if args.pull:
        return pull_or_report(repo, branch, upstream, behind, ahead, args.abort_on_conflict)

    print("\n只看不動（沒有加 --pull），工作目錄沒有被碰。要拿進來：加 --pull")
    return EXIT_CONFLICT if preview else EXIT_UPDATES_AVAILABLE


if __name__ == "__main__":
    sys.exit(main())
