#!/usr/bin/env python3
"""
Unit tests for pr_tool.py — stdlib unittest only, no network, no real git.

Everything that would hit the network (_http_get, _http_post, _gql) or spawn
a real git process (_git) is patched via unittest.mock. The only subprocess
actually spawned is the CLI entry-point test at the bottom, which exercises
paths that return before any network/git call is made.

Run with:
    python3 -m unittest discover -s <scripts dir> -p 'test_*.py' -v
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(SCRIPT_DIR, "pr_tool.py")


def _load_pr_tool():
    """Import pr_tool.py by path (scripts/ is not a package).

    A GITHUB_TOKEN is guaranteed to be present in the environment *before*
    import so that the module-level `_resolve_github_token()` call never
    shells out to `gh auth token` (no network / external process at import
    time).
    """
    os.environ.setdefault("GITHUB_TOKEN", "unit-test-token")
    spec = importlib.util.spec_from_file_location("pr_tool", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_tool = _load_pr_tool()


def _cp(args, returncode=0, stdout="", stderr=""):
    """Shorthand for a real subprocess.CompletedProcess, as _git would return."""
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def make_git_side_effect(
    branch="feature-branch", status="", shas=None, sig="G", apply_ok=True,
    staged=None, status_rc=0,
):
    """Build a side_effect function for a mocked `pr_tool._git`, routing on the
    leading positional args the way apply_patch actually calls it, and a
    `state` dict recording push/reset calls for assertions.
    """
    shas = list(shas or [])
    state = {"push_calls": [], "reset_calls": [], "sha_index": 0}

    def side_effect(*args, cwd, check=True):
        if args[0] == "rev-parse" and args[1] == "--is-inside-work-tree":
            return _cp(args, 0, "true\n")
        if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
            return _cp(args, 0, branch + "\n")
        if args[0] == "rev-parse" and args[1] == "HEAD":
            sha = shas[state["sha_index"]]
            state["sha_index"] += 1
            return _cp(args, 0, sha + "\n")
        if args[0] == "status" and args[1] == "--porcelain":
            return _cp(args, status_rc, status, "fatal: not a git repository" if status_rc else "")
        if args[0] == "diff" and args[1] == "--cached":
            # `git add -- <files>` stages exactly those paths; `staged`
            # overrides that to simulate an index dirtied before the run.
            names = state.get("last_add", []) if staged is None else staged
            return _cp(args, 0, "\0".join(names))
        if args[0] == "apply":
            return _cp(args, 0 if apply_ok else 1, "", "" if apply_ok else "patch does not apply")
        if args[0] == "add":
            state.setdefault("add_calls", []).append(args)
            state["last_add"] = [a for a in args[2:]]
            return _cp(args, 0, "")
        if args[0] == "commit":
            return _cp(args, 0, "")
        if args[0] == "log" and args[1] == "-1":
            return _cp(args, 0, sig + "\n")
        if args[0] == "show":
            return _cp(args, 0, "1 file changed, 1 insertion(+)")
        if args[0] == "push":
            state["push_calls"].append(args)
            return _cp(args, 0, "")
        if args[0] == "reset":
            state["reset_calls"].append(args)
            return _cp(args, 0, "")
        raise AssertionError(f"unexpected git call in test double: {args!r}")

    return side_effect, state


def _pr_data(branch="feature-branch", fork=False):
    """Minimal /pulls/{n} REST payload covering the fields apply_patch reads."""
    head_full_name = "someone/r" if fork else "o/r"
    return {
        "head": {
            "ref": branch,
            "repo": {"clone_url": "https://github.com/o/r.git", "full_name": head_full_name},
        },
        "base": {"repo": {"full_name": "o/r"}},
    }


# ---------------------------------------------------------------------------
# _redact
# ---------------------------------------------------------------------------

class TestRedact(unittest.TestCase):
    def test_masks_token_when_present(self):
        with patch.object(pr_tool, "GITHUB_TOKEN", "sekret-123"):
            text = "push failed: url contains sekret-123 in it"
            self.assertEqual(
                pr_tool._redact(text),
                "push failed: url contains *** in it",
            )

    def test_noop_when_token_empty(self):
        with patch.object(pr_tool, "GITHUB_TOKEN", ""):
            text = "nothing to redact here"
            self.assertEqual(pr_tool._redact(text), text)


# ---------------------------------------------------------------------------
# _resolve_github_token
# ---------------------------------------------------------------------------

class TestResolveGithubToken(unittest.TestCase):
    def test_returns_empty_string_when_gh_cli_missing(self):
        """No GITHUB_TOKEN in env and the `gh` binary absent (subprocess.run
        raises FileNotFoundError) → resolves to "" without raising."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            with patch.object(pr_tool.subprocess, "run", side_effect=FileNotFoundError):
                result = pr_tool._resolve_github_token()
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _check_token
# ---------------------------------------------------------------------------

class TestCheckToken(unittest.TestCase):
    def test_error_message_mentions_both_auth_channels(self):
        buf = io.StringIO()
        with patch.object(pr_tool, "GITHUB_TOKEN", ""), \
             self.assertRaises(SystemExit) as cm, \
             contextlib.redirect_stdout(buf):
            pr_tool._check_token()
        self.assertEqual(cm.exception.code, 1)
        data = json.loads(buf.getvalue())
        self.assertIn("GITHUB_TOKEN", data["error"])
        self.assertIn("gh auth login", data["error"])


# ---------------------------------------------------------------------------
# list_pr_comments
# ---------------------------------------------------------------------------

class TestListPrComments(unittest.TestCase):
    def _rest_comments(self):
        return [
            {
                "id": 1,
                "in_reply_to_id": None,
                "path": "a.py",
                "line": 10,
                "original_line": 10,
                "position": 3,
                "body": "root comment",
                "user": {"login": "alice"},
                "created_at": "2024-01-01T00:00:00Z",
                "diff_hunk": "@@ -1,2 +1,2 @@",
            },
            {
                "id": 2,
                "in_reply_to_id": 1,
                "path": "a.py",
                "line": 10,
                "original_line": 10,
                "position": 3,
                "body": "reply comment",
                "user": {"login": "bob"},
                "created_at": "2024-01-02T00:00:00Z",
                "diff_hunk": "@@ -1,2 +1,2 @@",
            },
            {
                "id": 3,
                "in_reply_to_id": None,
                "path": "b.py",
                "line": 5,
                "original_line": 5,
                "position": 1,
                "body": "orphan comment (no matching thread)",
                "user": {"login": "carol"},
                "created_at": "2024-01-03T00:00:00Z",
                "diff_hunk": "@@ -1,1 +1,1 @@",
            },
        ]

    def _gql_page(self, node_id, db_id, is_resolved, has_next, end_cursor):
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": node_id,
                                "isResolved": is_resolved,
                                "comments": {"nodes": [{"databaseId": db_id}]},
                            }
                        ],
                        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                    }
                }
            }
        }

    def test_maps_threads_and_paginates(self):
        page1 = self._gql_page("T1", 1, True, True, "cursor-abc")
        page2 = self._gql_page("T2", 99, False, False, None)

        with patch.object(pr_tool, "_paginate", return_value=self._rest_comments()) as m_paginate, \
             patch.object(pr_tool, "_gql", side_effect=[page1, page2]) as m_gql:
            # thread mapping is what this test covers, so opt back into the
            # comments the new defaults trim away (resolved threads, replies)
            result = pr_tool.list_pr_comments(
                {
                    "owner": "o",
                    "repo": "r",
                    "prNumber": 5,
                    "includeResolved": True,
                    "includeReplies": True,
                }
            )

        m_paginate.assert_called_once()
        self.assertEqual(m_gql.call_count, 2)
        # second page's query must carry the cursor returned by the first page
        first_call_vars = m_gql.call_args_list[0][0][1]
        second_call_vars = m_gql.call_args_list[1][0][1]
        self.assertIsNone(first_call_vars["cursor"])
        self.assertEqual(second_call_vars["cursor"], "cursor-abc")

        comments = result["comments"]
        self.assertEqual(len(comments), 3)

        root = comments[0]
        self.assertEqual(root["id"], 1)
        self.assertEqual(root["threadId"], "T1")
        self.assertTrue(root["isResolved"])
        self.assertIsNone(root["inReplyToId"])

        reply = comments[1]
        self.assertEqual(reply["id"], 2)
        self.assertEqual(reply["inReplyToId"], 1)
        # a reply inherits its root comment's thread metadata
        self.assertEqual(reply["threadId"], "T1")
        self.assertTrue(reply["isResolved"])

        orphan = comments[2]
        self.assertEqual(orphan["id"], 3)
        self.assertIsNone(orphan["threadId"])
        self.assertFalse(orphan["isResolved"])

    def test_defaults_drop_resolved_replies_and_hunks(self):
        page1 = self._gql_page("T1", 1, True, True, "cursor-abc")
        page2 = self._gql_page("T2", 99, False, False, None)

        with patch.object(pr_tool, "_paginate", return_value=self._rest_comments()), \
             patch.object(pr_tool, "_gql", side_effect=[page1, page2]):
            result = pr_tool.list_pr_comments({"owner": "o", "repo": "r", "prNumber": 5})

        comments = result["comments"]
        # comment 1 sits on a resolved thread, comment 2 is its reply: both gone.
        self.assertEqual([c["id"] for c in comments], [3])
        self.assertNotIn("diffHunk", comments[0])

    def test_hunk_lines_keeps_last_n_lines(self):
        rest = self._rest_comments()
        rest[2]["diff_hunk"] = "@@ hdr @@\nline1\nline2\nline3"
        page = self._gql_page("T2", 99, False, False, None)

        with patch.object(pr_tool, "_paginate", return_value=rest), \
             patch.object(pr_tool, "_gql", side_effect=[page]):
            result = pr_tool.list_pr_comments(
                {"owner": "o", "repo": "r", "prNumber": 5, "hunkLines": 2}
            )

        by_id = {c["id"]: c for c in result["comments"]}
        self.assertEqual(by_id[3]["diffHunk"], "line2\nline3")


# ---------------------------------------------------------------------------
# update_threads
# ---------------------------------------------------------------------------

class TestUpdateThreads(unittest.TestCase):
    def test_dry_run_makes_no_network_call(self):
        inp = {
            "owner": "o",
            "repo": "r",
            "prNumber": 1,
            "dryRun": True,
            "updates": [
                {"commentId": 1, "message": "m1", "resolved": True, "threadId": "T1"},
                {"commentId": 2, "message": "m2", "resolved": True},  # no threadId
                {"commentId": 3, "message": "m3", "resolved": False, "threadId": "T3"},
            ],
        }
        with patch.object(pr_tool, "_http_post") as m_post, patch.object(pr_tool, "_gql") as m_gql:
            result = pr_tool.update_threads(inp)

        m_post.assert_not_called()
        m_gql.assert_not_called()
        self.assertEqual(
            result,
            {
                "dryRun": True,
                "wouldPost": [
                    {"commentId": 1, "message": "m1", "wouldResolve": True},
                    {"commentId": 2, "message": "m2", "wouldResolve": False},
                    {"commentId": 3, "message": "m3", "wouldResolve": False},
                ],
            },
        )

    def test_real_pass_middle_failure_does_not_stop_others(self):
        inp = {
            "owner": "o",
            "repo": "r",
            "prNumber": 1,
            "updates": [
                {"commentId": 1, "message": "m1", "resolved": True, "threadId": "TA"},
                {"commentId": 2, "message": "m2", "resolved": True, "threadId": "TB"},
                {"commentId": 3, "message": "m3", "resolved": True, "threadId": "TC"},
            ],
        }

        def post_side_effect(url, payload, headers):
            if payload.get("in_reply_to") == 2:
                raise RuntimeError("boom")
            return {}

        with patch.object(pr_tool, "_http_post", side_effect=post_side_effect) as m_post, \
             patch.object(pr_tool, "_gql", return_value={}) as m_gql:
            result = pr_tool.update_threads(inp)

        self.assertEqual(m_post.call_count, 3)
        # update 2 raises during the reply step, so its resolve step (and
        # thus _gql) is never reached for it -> only updates 1 and 3 resolve.
        self.assertEqual(m_gql.call_count, 2)

        self.assertEqual(
            result,
            {
                "ok": False,
                "results": [
                    {"commentId": 1, "ok": True},
                    {"commentId": 2, "ok": False, "step": "reply", "error": "boom"},
                    {"commentId": 3, "ok": True},
                ],
            },
        )


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

class TestApplyPatch(unittest.TestCase):
    def test_empty_commits_list_returns_error_without_network_or_git(self):
        with patch.object(pr_tool, "_http_get") as m_get, \
             patch.object(pr_tool, "_git") as m_git:
            result = pr_tool.apply_patch(
                {"owner": "o", "repo": "r", "prNumber": 1, "commits": []}
            )
        self.assertEqual(result, {"error": "commits list is empty – nothing to apply."})
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_fork_deleted_head_repo_null(self):
        pr_data = {
            "head": {"ref": "feature-branch", "repo": None},
            "base": {"repo": {"full_name": "o/r"}},
        }
        with patch.object(pr_tool, "_http_get", return_value=pr_data):
            result = pr_tool.apply_patch(
                {"owner": "o", "repo": "r", "prNumber": 1, "patch": "p", "commitMessage": "m"}
            )
        self.assertEqual(
            result,
            {"error": "PR head repository is gone (fork deleted?) – cannot clone/push."},
        )

    def test_local_repo_wrong_branch_no_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(branch="some-other-branch")
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "patch": "p",
                        "commitMessage": "m",
                    }
                )
        self.assertIn("error", result)
        self.assertIn("some-other-branch", result["error"])
        self.assertIn("feature-branch", result["error"])
        self.assertEqual(state["push_calls"], [])

    def test_local_repo_dirty_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="M dirty_file.py\n"
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "patch": "p",
                        "commitMessage": "m",
                    }
                )
        self.assertIn("error", result)
        self.assertIn("not clean", result["error"])
        self.assertEqual(state["push_calls"], [])

    def test_local_repo_batch_two_commits_single_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="", shas=["initial-sha", "sha1", "sha2"], sig="G"
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [
                            {"patch": "p1", "commitMessage": "fix: one"},
                            {"patch": "p2", "commitMessage": "fix: two"},
                        ],
                    }
                )
        self.assertEqual(result, {"commitShas": ["sha1", "sha2"]})
        self.assertEqual(len(state["push_calls"]), 1)
        # a successful run must never hard-reset the user's branch
        self.assertEqual(state["reset_calls"], [])

    def test_patchless_commit_in_local_mode_never_calls_git_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            # apply_ok=False: if the code ever shelled out to `git apply`, the
            # run would fail. Succeeding proves it was skipped entirely.
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="", shas=["initial-sha", "sha1"], apply_ok=False
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [
                            {"commitMessage": "fix: edited in place", "files": ["a.py"]}
                        ],
                    }
                )
        self.assertEqual(result, {"commitShas": ["sha1"]})
        self.assertEqual(len(state["push_calls"]), 1)
        self.assertEqual(state["reset_calls"], [])
        # only the declared file is staged — never `git add -A`, which would
        # sweep the user's unrelated uncommitted work into a pushed commit
        self.assertEqual(state["add_calls"], [("add", "--", "a.py")])

    def test_patchless_commit_without_local_repo_path_errors_before_any_call(self):
        with patch.object(pr_tool, "_http_get") as m_get, \
             patch.object(pr_tool, "_git") as m_git:
            result = pr_tool.apply_patch(
                {
                    "owner": "o",
                    "repo": "r",
                    "prNumber": 1,
                    "commits": [
                        {"commitMessage": "fix: nothing to commit from a fresh clone", "files": ["a.py"]}
                    ],
                }
            )
        self.assertIn("error", result)
        self.assertIn("localRepoPath", result["error"])
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_patchless_commit_must_declare_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pr_tool, "_http_get") as m_get, \
                 patch.object(pr_tool, "_git") as m_git:
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [{"commitMessage": "fix: forgot the files key"}],
                    }
                )
        self.assertIn('"files"', result["error"])
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_cannot_mix_patch_and_patchless_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pr_tool, "_http_get") as m_get, \
                 patch.object(pr_tool, "_git") as m_git:
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [
                            {"patch": "p", "commitMessage": "one"},
                            {"commitMessage": "two", "files": ["a.py"]},
                        ],
                    }
                )
        self.assertIn("Cannot mix", result["error"])
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_patchless_rejects_pathspecs_and_directories_in_files(self):
        """`files` is an allowlist, so it must hold exact file paths: a glob, a
        directory or "." are recursive pathspecs that would stage the user's
        unrelated work under cover of the allowlist."""
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "src"))
            for bad in (".", "src", "src/*.py", "/abs/a.py", "../a.py", "./a.py"):
                with self.subTest(path=bad), \
                     patch.object(pr_tool, "_http_get") as m_get, \
                     patch.object(pr_tool, "_git") as m_git:
                    result = pr_tool.apply_patch(
                        {
                            "owner": "o",
                            "repo": "r",
                            "prNumber": 1,
                            "localRepoPath": tmp,
                            "commits": [{"commitMessage": "fix: x", "files": [bad]}],
                        }
                    )
                    self.assertIn("exact repo-relative file paths", result["error"])
                    m_get.assert_not_called()
                    m_git.assert_not_called()

    def test_patchless_refuses_to_commit_an_index_it_does_not_own(self):
        """`git add -- <files>` does not clear the index: a file staged before
        the run would ride along into the pushed commit."""
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status=" M a.py\nM  secrets.env\n",
                shas=["initial-sha"], staged=["a.py", "secrets.env"],
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [{"commitMessage": "fix: x", "files": ["a.py"]}],
                    }
                )
        self.assertIn("secrets.env", result["error"])
        self.assertEqual(state["push_calls"], [])
        # rewound with --mixed: the caller's edits stay on disk
        self.assertEqual([a[1] for a in state["reset_calls"]], ["--mixed"])

    def test_null_patch_is_classified_as_patchless(self):
        """`_run` reads the patch with `.get("patch")`, so an explicit null is
        patchless there — the guards must agree, or it slips past them."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pr_tool, "_http_get") as m_get, \
                 patch.object(pr_tool, "_git") as m_git:
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [{"patch": None, "commitMessage": "fix: x"}],
                    }
                )
        self.assertIn('"files"', result["error"])
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_non_string_patch_is_rejected(self):
        with patch.object(pr_tool, "_http_get") as m_get, \
             patch.object(pr_tool, "_git") as m_git:
            result = pr_tool.apply_patch(
                {
                    "owner": "o",
                    "repo": "r",
                    "prNumber": 1,
                    "commits": [{"patch": 42, "commitMessage": "fix: x"}],
                }
            )
        self.assertIn("unified-diff string", result["error"])
        m_get.assert_not_called()
        m_git.assert_not_called()

    def test_git_status_failure_aborts_even_in_patchless_mode(self):
        """Patchless mode skips the clean-tree *check*, not the command: an
        unreadable working tree means the safety guards cannot be trusted."""
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", shas=["initial-sha"], status_rc=1
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [{"commitMessage": "fix: x", "files": ["a.py"]}],
                    }
                )
        self.assertIn("git status failed", result["error"])
        self.assertEqual(state["push_calls"], [])

    def test_patchless_dirty_tree_allowed_and_reset_is_mixed(self):
        """A patchless run needs the tree dirty, and a failure must not delete
        the caller's edits — so it rewinds with --mixed, never --hard."""
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status=" M a.py\n", shas=["initial-sha"], sig="N"
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "commits": [{"commitMessage": "fix: in place", "files": ["a.py"]}],
                    }
                )
        # the dirty tree was accepted; the run failed later, on the signature guard
        self.assertIn("no signature", result["error"])
        self.assertEqual(state["push_calls"], [])
        self.assertEqual(state["reset_calls"], [("reset", "--mixed", "initial-sha")])

    def test_local_repo_apply_failure_resets_hard_no_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="", shas=["initial-sha-fail"], apply_ok=False
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "patch": "p",
                        "commitMessage": "m",
                    }
                )
        # apply fails both direct and --3way (make_git_side_effect's "apply"
        # branch ignores the extra flag and always fails when apply_ok=False)
        self.assertIn("error", result)
        self.assertIn("git apply failed (direct)", result["error"])
        self.assertIn("--3way also failed", result["error"])
        self.assertEqual(state["push_calls"], [])
        self.assertEqual(len(state["reset_calls"]), 1)
        self.assertEqual(state["reset_calls"][0], ("reset", "--hard", "initial-sha-fail"))

    def test_local_repo_dry_run_no_push_resets_to_initial_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="", shas=["initial-sha-000"], sig="G"
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "dryRun": True,
                        "commits": [{"patch": "p1", "commitMessage": "fix: one"}],
                    }
                )
        self.assertEqual(state["push_calls"], [])
        self.assertEqual(len(state["reset_calls"]), 1)
        self.assertEqual(state["reset_calls"][0], ("reset", "--hard", "initial-sha-000"))
        self.assertEqual(result["dryRun"], True)
        self.assertEqual(len(result["wouldPush"]), 1)
        self.assertEqual(result["wouldPush"][0]["commitMessage"], "fix: one")
        self.assertTrue(result["wouldPush"][0]["signed"])

    def test_legacy_single_patch_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_side_effect, state = make_git_side_effect(
                branch="feature-branch", status="", shas=["initial-shaX", "shaX"], sig="G"
            )
            with patch.object(pr_tool, "_http_get", return_value=_pr_data(branch="feature-branch")), \
                 patch.object(pr_tool, "_git", side_effect=git_side_effect):
                result = pr_tool.apply_patch(
                    {
                        "owner": "o",
                        "repo": "r",
                        "prNumber": 1,
                        "localRepoPath": tmp,
                        "patch": "p1",
                        "commitMessage": "fix: legacy",
                    }
                )
        self.assertEqual(result, {"commitSha": "shaX"})
        self.assertEqual(len(state["push_calls"]), 1)


# ---------------------------------------------------------------------------
# CLI entry point (exit codes)
# ---------------------------------------------------------------------------

class TestCliExitCodes(unittest.TestCase):
    def _env(self):
        # A dummy token avoids `_check_token()` failing and, more importantly,
        # avoids the module-level `gh auth token` fallback ever running.
        env = dict(os.environ)
        env["GITHUB_TOKEN"] = "dummy-token-for-cli-test"
        return env

    def test_unknown_kind_exits_1_with_error_json(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH, json.dumps({"kind": "nope"})],
            capture_output=True,
            text=True,
            env=self._env(),
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertIn("error", data)

    def test_invalid_json_exits_1_with_error_json(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH, "{not valid json"],
            capture_output=True,
            text=True,
            env=self._env(),
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
