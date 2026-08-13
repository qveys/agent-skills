#!/usr/bin/env python3
"""Unit tests for conflict_tool.py — stdlib unittest, mocked git."""

from __future__ import annotations

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
SCRIPT_PATH = os.path.join(SCRIPT_DIR, "conflict_tool.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("conflict_tool", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conflict_tool = _load_module()


def _cp(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


class TestPushHead(unittest.TestCase):
    def test_refuses_dry_run_env(self):
        with patch.dict(os.environ, {"CONFLICT_RESOLVE_MODE": "dry-run"}):
            result = conflict_tool.push_head(
                {
                    "headRef": "feat",
                    "remoteHeadSha": "abc",
                    "localRepoPath": "/tmp/repo",
                }
            )
        self.assertIn("error", result)
        self.assertIn("dry-run", result["error"])

    def test_refuses_plain_force_flag(self):
        with patch.dict(os.environ, {"CONFLICT_RESOLVE_MODE": "write"}):
            result = conflict_tool.push_head(
                {
                    "headRef": "feat",
                    "remoteHeadSha": "abc",
                    "force": True,
                    "localRepoPath": "/tmp/repo",
                }
            )
        self.assertIn("error", result)
        self.assertIn("--force", result["error"])

    def test_uses_force_with_lease_not_plain_force(self):
        calls: list[tuple] = []

        def git_side_effect(*args, cwd, check=True):
            if args[0] == "rev-parse" and args[1] == "--is-inside-work-tree":
                return _cp(args, 0, "true\n")
            if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
                return _cp(args, 0, "feat\n")
            if args[0] == "rev-parse" and args[1] == "HEAD":
                return _cp(args, 0, "newsha\n")
            if args[0] == "push":
                calls.append(args)
                return _cp(args, 0, "")
            raise AssertionError(f"unexpected git: {args}")

        with patch.dict(os.environ, {"CONFLICT_RESOLVE_MODE": "write"}), patch.object(
            conflict_tool, "_git", side_effect=git_side_effect
        ):
            with tempfile.TemporaryDirectory() as tmp:
                result = conflict_tool.push_head(
                    {
                        "headRef": "feat",
                        "remoteHeadSha": "oldsha",
                        "localRepoPath": tmp,
                    }
                )

        self.assertEqual(result["pushed"], True)
        self.assertEqual(len(calls), 1)
        push_args = calls[0]
        self.assertEqual(push_args[0], "push")
        self.assertTrue(any(a.startswith("--force-with-lease=") for a in push_args))
        self.assertFalse(any(a == "--force" for a in push_args))


class TestPrepareRebase(unittest.TestCase):
    def test_returns_remote_head_sha_on_conflict(self):
        def git_side_effect(*args, cwd, check=True):
            if args[0] == "rev-parse" and args[1] == "--is-inside-work-tree":
                return _cp(args, 0, "true\n")
            if args[0] == "fetch":
                return _cp(args, 0, "")
            if args[0] == "rev-parse" and args[1] == "origin/feat":
                return _cp(args, 0, "remote123\n")
            if args[0] == "checkout":
                return _cp(args, 0, "")
            if args[0] == "rebase":
                return _cp(args, 1, "", "conflict")
            if args[0] == "rev-parse" and args[1] == "--git-dir":
                return _cp(args, 0, ".git\n")
            if args[0] == "diff":
                return _cp(args, 0, "file.ts\n")
            raise AssertionError(f"unexpected git: {args}")

        with patch.object(conflict_tool, "_git", side_effect=git_side_effect), patch.object(
            conflict_tool.os.path, "isdir", return_value=True
        ):
            with tempfile.TemporaryDirectory() as tmp:
                result = conflict_tool.prepare_rebase(
                    {
                        "localRepoPath": tmp,
                        "baseRef": "main",
                        "headRef": "feat",
                    }
                )

        self.assertEqual(result["status"], "conflicted")
        self.assertEqual(result["remoteHeadSha"], "remote123")
        self.assertEqual(result["files"], ["file.ts"])


class TestCli(unittest.TestCase):
    def test_unknown_kind_exits_1(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH, json.dumps({"kind": "nope"})],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stdout))


if __name__ == "__main__":
    unittest.main()
