import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from github_access import get_latest_commit, get_worktree_status, format_commit_summary
from server import ACTION_KEYWORDS


def test_repo_action_keywords_include_repo_checks():
    assert "check_repo" in ACTION_KEYWORDS
    repo_keywords = ACTION_KEYWORDS["check_repo"]
    assert "latest commit" in repo_keywords
    assert "git status" in repo_keywords
    assert "open_whatsapp" in ACTION_KEYWORDS
    assert "open_telegram" in ACTION_KEYWORDS


def test_latest_commit_summary_exists():
    commit = get_latest_commit(Path(__file__).parent.parent)
    assert commit is not None
    summary = format_commit_summary(commit)
    assert "Latest commit" in summary
    assert commit.sha
    assert commit.subject


def test_worktree_status_shape():
    status = get_worktree_status(Path(__file__).parent.parent)
    assert "clean" in status
    assert "branch" in status
    assert "changed_files" in status
