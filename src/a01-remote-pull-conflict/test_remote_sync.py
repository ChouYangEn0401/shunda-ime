"""Tests for remote_sync.py, run against throwaway repos in a temp dir.

    uv run pytest src/a01-remote-pull-conflict/test_remote_sync.py -v

Not picked up by a plain ``uv run pytest``: pyproject sets
``testpaths = ["tests"]`` and this file lives next to the script it tests
(see docs/a01-remote-pull-conflict.md §6 for why), so it needs the path above.

No network: the "remote" is a bare repo in the same temp dir, reached by file
path, which exercises fetch/merge for real while staying offline. The one test
that needs a *broken* remote points it at a path that does not exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "remote_sync.py"

EXIT_IN_SYNC = 0
EXIT_ERROR = 1
EXIT_UPDATES_AVAILABLE = 10
EXIT_CONFLICT = 20

# A repo-shaped fixture needs an identity and must ignore the machine's real git
# config, or the result depends on who runs the tests.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    proc = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return proc.stdout.strip()


def write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")


def commit(repo: Path, name: str, text: str, message: str) -> None:
    write(repo, name, text)
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


def sync(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the script under test against `repo`."""
    env = {**os.environ, **GIT_ENV, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A local clone of a bare "origin" that already has one commit on main.

    Returns the clone; `origin_work(clone)` gives a second clone for pretending
    to be somebody else pushing.
    """
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-b", "main", str(seed))
    commit(seed, "shared.txt", "line one\n", "seed: first commit")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "-u", "origin", "main")

    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    return work


def origin_work(clone: Path) -> Path:
    """The seed clone, used to push commits that `clone` has not seen yet."""
    return clone.parent / "seed"


def push_remote_commit(clone: Path, name: str = "shared.txt", text: str = "line one\nline two\n") -> None:
    seed = origin_work(clone)
    commit(seed, name, text, "remote: a commit the clone has not pulled")
    git(seed, "push", "-q", "origin", "main")


def test_in_sync_is_reported_as_in_sync(clone: Path) -> None:
    result = sync(clone)
    assert result.returncode == EXIT_IN_SYNC, result.stdout
    assert "已經同步" in result.stdout


def test_remote_commit_is_detected_and_described(clone: Path) -> None:
    push_remote_commit(clone)
    result = sync(clone)
    assert result.returncode == EXIT_UPDATES_AVAILABLE, result.stdout
    assert "落後" in result.stdout
    assert "a commit the clone has not pulled" in result.stdout
    assert "shared.txt" in result.stdout
    assert "不會衝突" in result.stdout


def test_check_mode_changes_nothing(clone: Path) -> None:
    push_remote_commit(clone)
    before = git(clone, "rev-parse", "HEAD")
    sync(clone)
    assert git(clone, "rev-parse", "HEAD") == before
    assert git(clone, "status", "--porcelain") == ""


def test_pull_fast_forwards_a_branch_with_no_own_commits(clone: Path) -> None:
    push_remote_commit(clone)
    result = sync(clone, "--pull")
    assert result.returncode == EXIT_IN_SYNC, result.stdout
    assert (clone / "shared.txt").read_text(encoding="utf-8") == "line one\nline two\n"
    # Fast-forward, so the tip is the upstream commit itself with a single parent.
    assert git(clone, "rev-list", "--count", "--merges", "main") == "0"
    assert git(clone, "rev-parse", "main") == git(clone, "rev-parse", "origin/main")


def test_pull_makes_a_merge_commit_when_both_sides_have_commits(clone: Path) -> None:
    push_remote_commit(clone)
    commit(clone, "local.txt", "mine\n", "local: work only this clone has")
    result = sync(clone, "--pull")
    assert result.returncode == EXIT_IN_SYNC, result.stdout
    # The owner's --no-ff convention: the batch stays identifiable and revertable.
    assert git(clone, "rev-list", "--count", "--merges", "main") == "1"
    assert len(git(clone, "rev-list", "--parents", "-1", "main").split()) == 3
    assert "併入" in git(clone, "log", "-1", "--format=%s", "main")


def test_conflict_is_predicted_without_touching_the_work_tree(clone: Path) -> None:
    push_remote_commit(clone, text="line one\nremote version\n")
    commit(clone, "shared.txt", "line one\nlocal version\n", "local: same line, different answer")
    result = sync(clone)
    assert result.returncode == EXIT_CONFLICT, result.stdout
    # Not just "會衝突": that is a substring of the clean message, 不會衝突.
    assert "這些檔案會衝突" in result.stdout
    assert "不會衝突" not in result.stdout
    assert "shared.txt" in result.stdout
    # Predicted in memory: no merge started, nothing staged, no conflict markers.
    assert not (clone / ".git" / "MERGE_HEAD").exists()
    assert git(clone, "status", "--porcelain") == ""
    assert "<<<<<<<" not in (clone / "shared.txt").read_text(encoding="utf-8")


def test_pull_leaves_a_conflicted_merge_for_a_human(clone: Path) -> None:
    push_remote_commit(clone, text="line one\nremote version\n")
    commit(clone, "shared.txt", "line one\nlocal version\n", "local: same line, different answer")
    result = sync(clone, "--pull")
    assert result.returncode == EXIT_CONFLICT, result.stdout
    assert "這些檔案衝突了" in result.stdout
    assert (clone / ".git" / "MERGE_HEAD").exists()
    assert "<<<<<<<" in (clone / "shared.txt").read_text(encoding="utf-8")
    assert "git merge --abort" in result.stdout


def test_abort_on_conflict_leaves_nothing_to_clean_up(clone: Path) -> None:
    push_remote_commit(clone, text="line one\nremote version\n")
    commit(clone, "shared.txt", "line one\nlocal version\n", "local: same line, different answer")
    before = git(clone, "rev-parse", "HEAD")
    result = sync(clone, "--pull", "--abort-on-conflict")
    assert result.returncode == EXIT_CONFLICT, result.stdout
    assert not (clone / ".git" / "MERGE_HEAD").exists()
    assert git(clone, "status", "--porcelain") == ""
    assert git(clone, "rev-parse", "HEAD") == before
    assert (clone / "shared.txt").read_text(encoding="utf-8") == "line one\nlocal version\n"


def test_dirty_work_tree_is_refused_before_merging(clone: Path) -> None:
    push_remote_commit(clone)
    write(clone, "shared.txt", "uncommitted edit\n")
    result = sync(clone, "--pull")
    assert result.returncode == EXIT_ERROR, result.stdout
    assert "工作目錄不乾淨" in result.stdout
    assert (clone / "shared.txt").read_text(encoding="utf-8") == "uncommitted edit\n"


def test_unreachable_remote_is_not_reported_as_in_sync(clone: Path) -> None:
    """The failure this script exists for: offline must not read as up to date."""
    git(clone, "remote", "set-url", "origin", str(clone.parent / "does-not-exist.git"))
    result = sync(clone)
    assert result.returncode == EXIT_ERROR, result.stdout
    assert "連不到" in result.stdout
    assert "不是「現在確定沒有更新」" in result.stdout


def test_no_fetch_never_claims_in_sync(clone: Path) -> None:
    """--no-fetch did not ask, so it must not return the "asked, nothing new" code."""
    push_remote_commit(clone)
    result = sync(clone, "--no-fetch")
    # The commit is on the real origin, but this clone never asked, so its stale
    # refs make it *look* in sync. Reporting that as exit 0 would be the exact
    # false negative this script exists to prevent.
    assert result.returncode == EXIT_ERROR, result.stdout
    assert "可能已經過時" in result.stdout
    assert "不是「現在確定沒有更新」" in result.stdout
