#!/usr/bin/env python3
"""Black-box tests for the portable /learn collector and state helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
COLLECT = SKILL / "collect_sessions.py"
STATE = SKILL / "state.py"
PY = sys.executable


def run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(args, capture_output=True, text=True, env=e)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def grok_session(home: Path, sid: str, cwd: str, query: str, updated: str, tool_path: str | None = None) -> None:
    sess = home / "sessions" / "%2Fworkspace%2Fdemo" / sid
    write(
        sess / "summary.json",
        json.dumps({
            "info": {"id": sid, "cwd": cwd},
            "git_root_dir": cwd,
            "generated_title": "Demo " + sid,
            "session_kind": "interactive",
            "created_at": updated,
            "updated_at": updated,
            "current_model_id": "test-model",
        }),
    )
    lines = [
        json.dumps({"type": "user", "content": [{"type": "text", "text": f"<user_query>{query}</user_query>"}]}),
    ]
    if tool_path:
        lines.append(json.dumps({
            "type": "assistant",
            "tool_calls": [{"name": "read_file", "arguments": json.dumps({"target_file": tool_path})}],
        }))
    else:
        lines.append(json.dumps({
            "type": "assistant",
            "tool_calls": [{"name": "read_file", "arguments": json.dumps({"target_file": cwd + "/src/app.py"})}],
        }))
    write(sess / "chat_history.jsonl", "\n".join(lines) + "\n")


def claude_session(home: Path, sid: str, cwd: str, query: str, ts: str, extra: list[dict] | None = None) -> None:
    slug = cwd.replace("/", "-")
    recs = [
        {"type": "user", "cwd": cwd, "timestamp": ts, "sessionId": sid, "gitBranch": "main",
         "message": {"role": "user", "content": query}},
        {"type": "assistant", "timestamp": ts, "sessionId": sid,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "name": "Read", "input": {"file_path": cwd + "/src/app.py"}},
         ]}},
    ]
    if extra:
        recs.extend(extra)
    write(
        home / "projects" / slug / f"{sid}.jsonl",
        "\n".join(json.dumps(r) for r in recs) + "\n",
    )


class CollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.learn = self.root / "learn-home"
        self.out = self.root / "out"
        self.grok = self.root / "grok"
        self.claude = self.root / "claude"
        self.cwd = "/workspace/demo"
        write(self.root / "agents" / "skills" / "foo" / "SKILL.md", "---\nname: foo\ndescription: Foo skill\n---\n# foo\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def collect(self, *extra: str) -> dict:
        args = [
            PY, str(COLLECT),
            "--home", str(self.learn),
            "--grok-home", str(self.grok),
            "--claude-home", str(self.claude),
            "--codex-home", str(self.root / "missing-codex"),
            "--cursor-home", str(self.root / "missing-cursor"),
            "--agents-home", str(self.root / "agents"),
            "--out", str(self.out),
            "--exclude-cwd", str(self.root / "never"),
            *extra,
        ]
        r = run(args)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_grok_and_claude_sessions_are_kept(self) -> None:
        grok_session(self.grok, "g1", self.cwd, "always run the tests before commit", "2026-09-01T10:00:00+00:00",
                     tool_path=str(self.root / "agents" / "skills" / "foo" / "SKILL.md"))
        claude_session(self.claude, "c1", self.cwd, "always run the tests before commit", "2026-09-02T10:00:00Z", extra=[{
            "type": "assistant", "timestamp": "2026-09-02T10:00:01Z", "sessionId": "c1",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": "foo", "args": ""}},
            ]},
        }])
        result = self.collect()
        self.assertEqual(result["kept"], 2)
        self.assertEqual(result["seen"], 2)
        manifest = json.loads((self.out / "manifest.json").read_text())
        harnesses = sorted({k["harness"] for k in manifest["kept"]})
        self.assertEqual(harnesses, ["claude", "grok"])
        usage = json.loads((self.out / "usage.json").read_text())
        foo = next(i for i in usage["items"] if i["kind"] == "skill" and i["name"] == "foo")
        self.assertGreaterEqual(foo["count"], 1)
        phrases = json.loads((self.out / "phrases.json").read_text())
        self.assertTrue(phrases["exact_prompts"])

    def test_security_review_and_smoke_are_dropped(self) -> None:
        grok_session(self.grok, "smoke", self.cwd, "hi", "2026-09-01T10:00:00+00:00")
        smoke_dir = self.grok / "sessions" / "%2Fworkspace%2Fdemo" / "smoke"
        # overwrite chat: greeting only, no tools
        write(smoke_dir / "chat_history.jsonl", json.dumps({
            "type": "user", "content": [{"type": "text", "text": "<user_query>hi</user_query>"}],
        }) + "\n")
        claude_session(
            self.claude, "sec", self.cwd,
            "Review this change for security vulnerabilities.\n\nChanged files: a.py",
            "2026-09-02T10:00:00Z",
        )
        result = self.collect()
        self.assertEqual(result["kept"], 0)
        self.assertIn(result["dropped"].get("smoke_test", 0) + result["dropped"].get("no_human_turns", 0), range(1, 10))

    def test_codex_session_is_kept(self) -> None:
        codex = self.root / "codex"
        sess = codex / "sessions" / "2026" / "rollout.jsonl"
        write(sess, "\n".join([
            json.dumps({"type": "session_meta", "payload": {"id": "cx1", "cwd": self.cwd, "timestamp": "2026-09-03T10:00:00Z"}}),
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": "please always run the tests before commit thanks"}]}}),
            json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "read_file",
                        "arguments": json.dumps({"path": self.cwd + "/src/app.py"})}}),
        ]) + "\n")
        args = [
            PY, str(COLLECT),
            "--home", str(self.learn),
            "--grok-home", str(self.root / "no-g"),
            "--claude-home", str(self.root / "no-c"),
            "--codex-home", str(codex),
            "--cursor-home", str(self.root / "no-u"),
            "--agents-home", str(self.root / "agents"),
            "--out", str(self.out),
            "--exclude-cwd", str(self.root / "never"),
        ]
        r = run(args)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(result["kept"], 1)
        self.assertEqual(result["harnesses"], ["codex"])

    def test_estimate_lists_scopes(self) -> None:
        grok_session(self.grok, "g1", self.cwd, "please always run the tests before commit thanks", "2026-09-01T10:00:00+00:00")
        r = self.collect("--estimate")
        self.assertIn("windows", r)
        self.assertIn("recommended", r)
        self.assertGreaterEqual(r["windows"]["all"]["sessions"], 1)

    def test_no_homes_is_an_error(self) -> None:
        r = run([
            PY, str(COLLECT),
            "--home", str(self.learn),
            "--grok-home", str(self.root / "no-g"),
            "--claude-home", str(self.root / "no-c"),
            "--codex-home", str(self.root / "no-x"),
            "--cursor-home", str(self.root / "no-u"),
            "--agents-home", str(self.root / "no-a"),
            "--out", str(self.out),
        ])
        self.assertEqual(r.returncode, 2)


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "learn"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_and_set(self) -> None:
        r = run([PY, str(STATE), "--home", str(self.home), "get"])
        self.assertEqual(r.returncode, 0)
        view = json.loads(r.stdout)
        self.assertEqual(view["python"], PY)
        self.assertEqual(os.path.realpath(view["learn_home"]), os.path.realpath(self.home))
        run_dir = str(Path(self.tmp.name) / "run")
        Path(run_dir).mkdir()
        r = run([PY, str(STATE), "--home", str(self.home), "set", "--run-dir", run_dir, "--status", "collected"])
        self.assertEqual(r.returncode, 0)
        r = run([PY, str(STATE), "--home", str(self.home), "get"])
        self.assertEqual(r.returncode, 3)
        self.assertEqual(json.loads(r.stdout)["pending"]["status"], "collected")


if __name__ == "__main__":
    unittest.main()
