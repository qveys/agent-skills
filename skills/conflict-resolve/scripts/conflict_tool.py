#!/usr/bin/env python3
"""
conflict_tool.py – Git rebase / conflict resolution tool for conflict-resolve skill.

Usage:
    python scripts/conflict_tool.py '<json_input>'

JSON input must include a "kind" field:
    - "prepare_rebase"    → fetch base/head, rebase onto origin/<base>
    - "list_conflicts"    → unmerged files + conflict marker excerpts
    - "commit_resolution" → stage resolved paths and rebase --continue
    - "push_head"         → force-with-lease push (never plain --force)
    - "abort_rebase"      → git rebase --abort

See SKILL.md for full input/output schemas.

Environment (injected by Housekeeper runner):
    OWNER, REPO, PR_NUMBER, BASE_REF, HEAD_REF, CONFLICT_RESOLVE_MODE
    GITHUB_TOKEN (optional — falls back to `gh auth token`)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

CONFLICT_MARKER_RE = re.compile(r"^(<<<<<<<|=======|>>>>>>>)")


def _resolve_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    try:
        gh_r = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=False
        )
    except (FileNotFoundError, OSError):
        return ""
    if gh_r.returncode == 0:
        return gh_r.stdout.strip()
    return ""


GITHUB_TOKEN: str = _resolve_github_token()


def _exit_error(message: str) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def _redact(text: str) -> str:
    if GITHUB_TOKEN and GITHUB_TOKEN in text:
        return text.replace(GITHUB_TOKEN, "***")
    return text


def _git(*args: str, cwd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true"},
    )
    if check and result.returncode != 0:
        message = (
            f"git {' '.join(args)} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
        if result.stdout.strip():
            message += f"\n{result.stdout.strip()}"
        raise RuntimeError(_redact(message))
    return result


def _resolve_repo_path(inp: dict) -> str:
    path = inp.get("localRepoPath") or os.getcwd()
    if not os.path.isdir(path):
        return path
    is_repo = _git("rev-parse", "--is-inside-work-tree", cwd=path, check=False)
    if is_repo.returncode != 0 or is_repo.stdout.strip() != "true":
        raise ValueError(f"localRepoPath {path!r} is not a git repository.")
    return path


def _env_ref(name: str, inp: dict, key: str) -> str:
    value = inp.get(key) or os.environ.get(name, "")
    if not value:
        raise ValueError(f"{key} or env {name} is required.")
    return value


def _resolve_mode(inp: dict) -> str:
    mode = inp.get("mode") or os.environ.get("CONFLICT_RESOLVE_MODE", "write")
    normalized = str(mode).strip().lower()
    if normalized not in ("write", "dry-run"):
        raise ValueError(f"Invalid mode {mode!r}; expected write or dry-run.")
    return normalized


def _is_rebase_in_progress(cwd: str) -> bool:
    git_dir = _git("rev-parse", "--git-dir", cwd=cwd).stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(cwd, git_dir)
    return os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(
        os.path.join(git_dir, "rebase-apply")
    )


def _head_signature_ok(cwd: str) -> tuple[bool, str]:
    sig_r = _git("log", "-1", "--format=%G?", cwd=cwd, check=False)
    sig_status = sig_r.stdout.strip()
    if sig_status in ("N", ""):
        return False, sig_status
    return True, sig_status


def _signing_error(prefix: str, detail: str) -> dict[str, str]:
    return {
        "error": _redact(
            f"{prefix}Commit signing failed – refusing to continue with an unsigned "
            "commit. Unlock the signing key or rerun outside a sandboxed shell.\n\n"
            f"{detail}"
        )
    }


def prepare_rebase(inp: dict) -> dict[str, Any]:
    """
    Fetch origin base/head, record remote head SHA, rebase onto origin/<base>.
    Returns { status, remoteHeadSha, files? }.
    """
    cwd = _resolve_repo_path(inp)
    base_ref = _env_ref("BASE_REF", inp, "baseRef")
    head_ref = _env_ref("HEAD_REF", inp, "headRef")

    _git("fetch", "origin", base_ref, head_ref, cwd=cwd)

    remote_head_r = _git("rev-parse", f"origin/{head_ref}", cwd=cwd, check=False)
    if remote_head_r.returncode != 0:
        return {
            "status": "failed",
            "error": _redact(
                f"Could not resolve origin/{head_ref} after fetch:\n"
                f"{remote_head_r.stderr.strip()}"
            ),
        }
    remote_head_sha = remote_head_r.stdout.strip()

    checkout_r = _git("checkout", head_ref, cwd=cwd, check=False)
    if checkout_r.returncode != 0:
        return {
            "status": "failed",
            "error": _redact(f"git checkout {head_ref} failed:\n{checkout_r.stderr.strip()}"),
            "remoteHeadSha": remote_head_sha,
        }

    rebase_r = _git("rebase", f"origin/{base_ref}", cwd=cwd, check=False)
    if rebase_r.returncode == 0:
        return {"status": "clean", "remoteHeadSha": remote_head_sha}

    if _is_rebase_in_progress(cwd):
        files_r = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
        files = [f for f in files_r.stdout.splitlines() if f.strip()]
        return {
            "status": "conflicted",
            "remoteHeadSha": remote_head_sha,
            "files": files,
        }

    return {
        "status": "failed",
        "remoteHeadSha": remote_head_sha,
        "error": _redact(f"git rebase failed:\n{rebase_r.stderr.strip()}"),
    }


def _conflict_excerpt(path: str, cwd: str, context: int = 3) -> str:
    try:
        with open(os.path.join(cwd, path), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as exc:
        return f"(could not read file: {exc})"

    marker_indices = [i for i, line in enumerate(lines) if CONFLICT_MARKER_RE.match(line)]
    if not marker_indices:
        return "(no conflict markers found)"

    start = max(0, marker_indices[0] - context)
    end = min(len(lines), marker_indices[-1] + context + 1)
    excerpt_lines = []
    for i in range(start, end):
        excerpt_lines.append(f"{i + 1:5d}|{lines[i].rstrip()}")
    return "\n".join(excerpt_lines)


def list_conflicts(inp: dict) -> dict[str, Any]:
    """Return unmerged files and conflict marker excerpts."""
    cwd = _resolve_repo_path(inp)
    files_r = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
    files = [f for f in files_r.stdout.splitlines() if f.strip()]

    conflicts = [
        {"path": path, "excerpt": _conflict_excerpt(path, cwd)} for path in files
    ]
    return {"conflicts": conflicts, "count": len(conflicts)}


def commit_resolution(inp: dict) -> dict[str, Any]:
    """
    Stage resolved paths and continue the rebase until done or new conflicts.
    Signed commits are required (commit.gpgsign / -S enforced by runner config).
    """
    cwd = _resolve_repo_path(inp)
    paths: list[str] = inp.get("paths") or []
    if not paths:
        return {"error": "paths is required and must be non-empty."}

    if not _is_rebase_in_progress(cwd):
        return {"error": "No rebase in progress; run prepare_rebase first."}

    _git("add", "--", *paths, cwd=cwd)

    continue_r = _git("rebase", "--continue", cwd=cwd, check=False)
    if continue_r.returncode != 0:
        if _is_rebase_in_progress(cwd):
            files_r = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
            files = [f for f in files_r.stdout.splitlines() if f.strip()]
            return {
                "status": "conflicted",
                "files": files,
                "error": _redact(
                    "rebase --continue stopped with remaining conflicts:\n"
                    f"{continue_r.stderr.strip()}"
                ),
            }
        return {"error": _redact(f"git rebase --continue failed:\n{continue_r.stderr.strip()}")}

    signed, sig_status = _head_signature_ok(cwd)
    if not signed:
        return _signing_error("", f"HEAD signature status={sig_status!r}")

    while _is_rebase_in_progress(cwd):
        step_r = _git("rebase", "--continue", cwd=cwd, check=False)
        if step_r.returncode != 0:
            if _is_rebase_in_progress(cwd):
                files_r = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
                files = [f for f in files_r.stdout.splitlines() if f.strip()]
                return {
                    "status": "conflicted",
                    "files": files,
                    "error": _redact(step_r.stderr.strip()),
                }
            return {"error": _redact(step_r.stderr.strip())}
        signed, sig_status = _head_signature_ok(cwd)
        if not signed:
            return _signing_error("", f"HEAD signature status={sig_status!r}")

    head_sha = _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
    return {"status": "complete", "headSha": head_sha}


def push_head(inp: dict) -> dict[str, Any]:
    """
    Push HEAD_REF with force-with-lease. Refuses dry-run and plain --force.
    """
    mode = _resolve_mode(inp)
    if mode == "dry-run":
        return {"error": "push_head is forbidden in dry-run mode."}

    if inp.get("force") is True or inp.get("allowPlainForce") is True:
        return {"error": "Plain git push --force is forbidden; use force-with-lease only."}

    cwd = _resolve_repo_path(inp)
    head_ref = _env_ref("HEAD_REF", inp, "headRef")
    remote_head_sha = inp.get("remoteHeadSha")
    if not remote_head_sha:
        return {"error": "remoteHeadSha is required (from prepare_rebase output)."}

    branch_r = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, check=False)
    current_branch = branch_r.stdout.strip()
    if branch_r.returncode != 0 or current_branch != head_ref:
        return {
            "error": (
                f"Refusing push: checkout is {current_branch!r}, expected HEAD_REF "
                f"{head_ref!r}."
            )
        }

    lease = f"refs/heads/{head_ref}:{remote_head_sha}"
    push_args = [
        "push",
        f"--force-with-lease={lease}",
        "origin",
        head_ref,
    ]

    if "--force" in push_args and "--force-with-lease" not in " ".join(push_args):
        return {"error": "Internal error: push would use plain --force."}

    push_r = _git(*push_args, cwd=cwd, check=False)
    if push_r.returncode != 0:
        err = push_r.stderr.strip() or push_r.stdout.strip()
        low = err.lower()
        if "stale" in low or "lease" in low or "rejected" in low or "protected" in low:
            return {
                "error": _redact(
                    "Push rejected (lease mismatch or branch protection). "
                    "Stop with needs_human.\n\n"
                    f"{err}"
                ),
                "needs_human": True,
            }
        return {"error": _redact(f"git push failed:\n{err}")}

    new_sha = _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
    return {"pushed": True, "headSha": new_sha, "headRef": head_ref}


def abort_rebase(inp: dict) -> dict[str, Any]:
    """Abort an in-progress rebase."""
    cwd = _resolve_repo_path(inp)
    if not _is_rebase_in_progress(cwd):
        return {"aborted": False, "message": "No rebase in progress."}
    _git("rebase", "--abort", cwd=cwd)
    return {"aborted": True}


OPERATIONS: dict[str, Any] = {
    "prepare_rebase": prepare_rebase,
    "list_conflicts": list_conflicts,
    "commit_resolution": commit_resolution,
    "push_head": push_head,
    "abort_rebase": abort_rebase,
}


def main() -> None:
    if len(sys.argv) < 2:
        _exit_error(
            "Usage: python scripts/conflict_tool.py '<json_input>'\n"
            f"Supported kinds: {', '.join(OPERATIONS)}"
        )

    try:
        inp = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        _exit_error(f"Invalid JSON input: {exc}")

    kind: str = inp.get("kind", "")
    handler = OPERATIONS.get(kind)
    if handler is None:
        _exit_error(
            f"Unknown kind: {kind!r}. Valid options: {', '.join(OPERATIONS)}"
        )

    try:
        result = handler(inp)
    except ValueError as exc:
        result = {"error": str(exc)}
    except RuntimeError as exc:
        result = {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc)}

    if isinstance(result, dict) and isinstance(result.get("error"), str):
        result["error"] = _redact(result["error"])

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if isinstance(result, dict) and (
        "error" in result or result.get("needs_human") is True
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
