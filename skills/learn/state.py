#!/usr/bin/env python3
"""Read or update LEARN_HOME/state.json for the /learn skill.

  state.py get
  state.py set --run-dir DIR --status collected|running|report_ready|curating|done [--mode M] [--scope S] [--note TEXT]
  state.py clear
  state.py trash --run-name NAME PATH [PATH ...]
  state.py restrict PATH [PATH ...]
  state.py decide --run-dir DIR --id A3 --kind skill --action delete --target NAME --path P --decision applied|rejected|deferred [--undo P]

`get` prints the state as JSON (plus `python` and `learn_home`) and exits 3 when a
run is pending (status other than done). All writes merge into the existing file.
`trash`, `restrict`, and `decide` exist so the skill never needs mkdir/mv/chmod/echo >>
and work the same in bash and PowerShell.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import stat
import sys

STATUSES = ("collected", "running", "report_ready", "curating", "done")


def state_path(home: str) -> str:
    return os.path.join(home, "state.json")


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


def allowed_roots(learn_home: str) -> list[str]:
    roots = [
        os.path.realpath(learn_home),
        os.path.realpath(os.path.expanduser("~/.agents")),
        os.path.realpath(os.path.expanduser("~/.claude")),
        os.path.realpath(os.path.expanduser("~/.grok")),
        os.path.realpath(os.path.expanduser("~/.codex")),
        os.path.realpath(os.path.expanduser("~/.cursor")),
    ]
    return [r for r in roots if os.path.isdir(r)]


def under(path: str, base: str) -> bool:
    path, base = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(base))
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def trashable(src: str, roots: list[str]) -> bool:
    real = os.path.realpath(src)
    parent = os.path.dirname(real)
    kind = os.path.basename(parent)
    in_root = any(under(real, r) for r in roots)
    project_marker = any(
        seg in real.replace("\\", "/")
        for seg in ("/.claude/skills/", "/.grok/skills/", "/.agents/skills/", "/.codex/skills/")
    )
    if os.path.isdir(real) and kind == "skills" and (in_root or project_marker):
        return True
    if os.path.isfile(real) and kind == "workflows" and (in_root or "/.grok/workflows/" in real.replace("\\", "/") or "/.claude/workflows/" in real.replace("\\", "/")):
        return True
    if os.path.isfile(real) and kind == "hooks" and in_root:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=os.environ.get("LEARN_HOME") or os.path.expanduser("~/.learn"))
    ap.add_argument("--grok-home", default=None, help="deprecated alias; extra trash root if set")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("get")
    s = sub.add_parser("set")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--status", required=True, choices=STATUSES)
    s.add_argument("--mode")
    s.add_argument("--scope")
    s.add_argument("--note")
    sub.add_parser("clear")
    t = sub.add_parser("trash")
    t.add_argument("--run-name", required=True)
    t.add_argument("paths", nargs="+")
    r = sub.add_parser("restrict")
    r.add_argument("paths", nargs="+")
    d = sub.add_parser("decide")
    for name in ("--run-dir", "--id", "--kind", "--action", "--target", "--path"):
        d.add_argument(name, required=True)
    d.add_argument("--decision", required=True, choices=("applied", "rejected", "deferred"))
    d.add_argument("--undo", default=None)
    args = ap.parse_args()

    learn_home = os.path.abspath(os.path.expanduser(args.home))
    path = state_path(learn_home)

    if args.cmd == "trash":
        if args.run_name in ("", ".", "..") or os.path.basename(args.run_name) != args.run_name:
            print(json.dumps({"error": "run-name must be a single path component", "run_name": args.run_name}))
            return 2
        dest_dir = os.path.join(learn_home, "trash", args.run_name)
        roots = allowed_roots(learn_home)
        if args.grok_home:
            roots.append(os.path.realpath(os.path.expanduser(args.grok_home)))
        for src in args.paths:
            src = os.path.abspath(os.path.expanduser(src))
            if not os.path.exists(src):
                print(json.dumps({"error": "missing", "path": src}))
                return 1
            if not trashable(src, roots):
                print(json.dumps({
                    "error": "refusing: only a skills/<name> directory, a workflows file, or a hooks file under a known agent home or project skills dir can be trashed",
                    "path": src,
                }))
                return 2
        os.makedirs(dest_dir, exist_ok=True)
        moved = []
        for src in args.paths:
            src = os.path.abspath(os.path.expanduser(src))
            dest = os.path.join(dest_dir, os.path.basename(src.rstrip("\\/")))
            if os.path.exists(dest):
                dest += "-" + dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
            shutil.move(src, dest)
            moved.append({"from": src, "to": dest})
        print(json.dumps({"moved": moved}, indent=1))
        return 0

    if args.cmd == "restrict":
        for p in args.paths:
            try:
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        print(json.dumps({"restricted": args.paths}))
        return 0

    if args.cmd == "decide":
        line = {"date": dt.datetime.now(dt.timezone.utc).date().isoformat(), "run_dir": args.run_dir, "id": args.id,
                "kind": args.kind, "action": args.action, "target": args.target, "path": args.path,
                "decision": args.decision, "undo": args.undo}
        dec_path = os.path.join(learn_home, "decisions.jsonl")
        os.makedirs(os.path.dirname(dec_path), exist_ok=True)
        with open(dec_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        print(json.dumps(line))
        return 0

    state = load(path)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    if args.cmd == "get":
        view = dict(state)
        view["python"] = sys.executable
        view["learn_home"] = learn_home
        print(json.dumps(view, indent=1))
        pending = state.get("pending") or {}
        return 3 if pending and pending.get("status") != "done" else 0

    if args.cmd == "clear":
        state.pop("pending", None)
        save(path, state)
        print(json.dumps(state, indent=1))
        return 0

    pending = state.get("pending") or {}
    if pending.get("run_dir") != args.run_dir:
        pending = {"run_dir": args.run_dir, "started_at": now}
    pending["status"] = args.status
    pending["updated_at"] = now
    pending["report_ready"] = os.path.isfile(os.path.join(args.run_dir, "report.md")) and os.path.isfile(
        os.path.join(args.run_dir, "actions.json"))
    for k in ("mode", "scope", "note"):
        v = getattr(args, k)
        if v:
            pending[k] = v
    if args.status == "done":
        state["last_completed_at"] = now
        state["last_completed_dir"] = args.run_dir
    state["pending"] = pending
    save(path, state)
    print(json.dumps(state, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
