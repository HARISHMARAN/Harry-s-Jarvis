"""
JARVIS GitHub Access — local repo intelligence, with optional GitHub API support.

This module does two things:
- Reads the current git repository state directly from the local checkout.
- Optionally uses a GitHub token to look up remote repo metadata.

The local git path is the reliable baseline. Remote API access is only used
when credentials are present and the request clearly needs GitHub-side data.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("jarvis.github")


@dataclass
class GitCommitSummary:
    sha: str
    short_sha: str
    subject: str
    body: str
    author: str
    date: str
    files_changed: list[str]
    insertions: int
    deletions: int
    branch: str
    remote_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "short_sha": self.short_sha,
            "subject": self.subject,
            "body": self.body,
            "author": self.author,
            "date": self.date,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "branch": self.branch,
            "remote_url": self.remote_url,
        }


def is_github_configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip())


def _run_git(args: list[str], cwd: str | Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git command failed")
    return proc.stdout.strip()


def find_repo_root(start: str | Path | None = None) -> Path | None:
    base = Path(start or Path(__file__).parent).resolve()
    try:
        root = _run_git(["rev-parse", "--show-toplevel"], cwd=base)
        return Path(root).resolve()
    except Exception:
        return None


def get_repo_remote_url(repo_root: str | Path | None = None) -> str:
    root = find_repo_root(repo_root)
    if not root:
        return ""
    try:
        return _run_git(["remote", "get-url", "origin"], cwd=root)
    except Exception:
        return ""


def get_current_branch(repo_root: str | Path | None = None) -> str:
    root = find_repo_root(repo_root)
    if not root:
        return ""
    try:
        return _run_git(["branch", "--show-current"], cwd=root)
    except Exception:
        return ""


def _parse_numstat(repo_root: Path, commit_ref: str) -> tuple[int, int, list[str]]:
    try:
        raw = _run_git(["show", "--numstat", "--format=", commit_ref], cwd=repo_root)
    except Exception:
        return 0, 0, []

    insertions = deletions = 0
    files: list[str] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            add, delete, path = parts[0], parts[1], parts[2]
            if add.isdigit():
                insertions += int(add)
            if delete.isdigit():
                deletions += int(delete)
            files.append(path)
    return insertions, deletions, files


def get_latest_commit(repo_root: str | Path | None = None) -> GitCommitSummary | None:
    root = find_repo_root(repo_root)
    if not root:
        return None

    try:
        sha = _run_git(["rev-parse", "HEAD"], cwd=root)
        short_sha = _run_git(["rev-parse", "--short", "HEAD"], cwd=root)
        subject = _run_git(["show", "-s", "--format=%s", "HEAD"], cwd=root)
        body = _run_git(["show", "-s", "--format=%b", "HEAD"], cwd=root)
        author = _run_git(["show", "-s", "--format=%an", "HEAD"], cwd=root)
        date = _run_git(["show", "-s", "--format=%ci", "HEAD"], cwd=root)
        branch = get_current_branch(root)
        remote_url = get_repo_remote_url(root)
        insertions, deletions, files = _parse_numstat(root, "HEAD")
        return GitCommitSummary(
            sha=sha,
            short_sha=short_sha,
            subject=subject or "(no subject)",
            body=body.strip(),
            author=author or "Unknown",
            date=date or "",
            files_changed=files,
            insertions=insertions,
            deletions=deletions,
            branch=branch,
            remote_url=remote_url,
        )
    except Exception as e:
        log.warning(f"Failed to read latest commit: {e}")
        return None


def get_recent_commits(limit: int = 5, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = find_repo_root(repo_root)
    if not root:
        return []

    try:
        raw = _run_git(
            ["log", f"-n{limit}", "--date=iso", "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%b"],
            cwd=root,
        )
    except Exception as e:
        log.warning(f"Failed to read recent commits: {e}")
        return []

    commits: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) >= 6:
            commits.append(
                {
                    "sha": parts[0],
                    "short_sha": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                    "subject": parts[4] or "(no subject)",
                    "body": parts[5].strip(),
                }
            )
    return commits


def get_worktree_status(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    if not root:
        return {"clean": True, "branch": "", "changed_files": [], "status": ""}

    try:
        branch = get_current_branch(root)
        status = _run_git(["status", "--short"], cwd=root)
    except Exception as e:
        log.warning(f"Failed to read worktree status: {e}")
        return {"clean": True, "branch": "", "changed_files": [], "status": ""}

    changed_files = []
    for line in status.splitlines():
        if len(line) > 3:
            changed_files.append(line[3:].strip())
    return {
        "clean": not bool(changed_files),
        "branch": branch,
        "changed_files": changed_files,
        "status": status,
    }


async def get_remote_repo_metadata(owner: str, repo: str) -> dict[str, Any] | None:
    token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
    if not token:
        return None

    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=headers)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.warning(f"GitHub repo metadata lookup failed: {resp.status_code} {resp.text[:200]}")
        raise e
    return resp.json()


def format_commit_summary(commit: GitCommitSummary | None) -> str:
    if not commit:
        return "I couldn't read the latest commit, sir."

    files = ", ".join(commit.files_changed[:6]) if commit.files_changed else "no tracked file changes"
    details = commit.body.strip().splitlines()[0] if commit.body.strip() else ""
    parts = [
        f"Latest commit on {commit.branch or 'this branch'} is {commit.short_sha}: {commit.subject}.",
    ]
    if details:
        parts.append(details)
    parts.append(f"It touched {len(commit.files_changed)} file(s): {files}.")
    parts.append(f"Net change: +{commit.insertions} / -{commit.deletions}.")
    return " ".join(parts)


def format_recent_commits(commits: list[dict[str, Any]]) -> str:
    if not commits:
        return "I couldn't find any recent commits, sir."
    lines = []
    for commit in commits[:5]:
        lines.append(f"{commit['short_sha']}: {commit['subject']} by {commit['author']}")
    return "Recent commits: " + "; ".join(lines) + "."


def format_worktree_status(status: dict[str, Any]) -> str:
    branch = status.get("branch") or "unknown branch"
    changed = status.get("changed_files") or []
    if not changed:
        return f"The worktree on {branch} is clean, sir."
    files = ", ".join(changed[:6])
    return f"The worktree on {branch} has changes in {len(changed)} file(s): {files}."
