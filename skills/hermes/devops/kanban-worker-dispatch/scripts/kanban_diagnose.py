"""Print a Kanban task's dispatch state in one shot.

Usage:  python3 kanban_diagnose.py <task_id> [--lines N] [--board <slug>]

Steps, in the order that answers the most questions first:
  1. task row            -> status, assignee, workspace, last_failure_error
  2. task_runs           -> per-attempt outcome/error/metadata (spawn_failed vs crashed)
  3. worker stdout log   -> <racine>/kanban/logs/<task_id>.log (board default)
                            ou <racine>/kanban/boards/<slug>/logs/<task_id>.log tail

Read-only. Never writes to the board.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def kanban_root() -> Path:
    """Racine du board, partagée entre profils (cf. hermes_cli.kanban_db.kanban_home)."""
    override = os.environ.get("HERMES_KANBAN_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    # HERMES_HOME d'un profil = <racine>/profiles/<nom> -> la racine est deux niveaux au-dessus
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def board_slug(argv: list[str]) -> str:
    if "--board" in argv:
        try:
            return argv[argv.index("--board") + 1]
        except IndexError:
            pass
    env = os.environ.get("HERMES_KANBAN_BOARD", "").strip()
    if env:
        return env
    cur = kanban_root() / "kanban" / "current"
    if cur.exists():
        slug = cur.read_text().strip()
        if slug:
            return slug
    return "default"


def board_db(slug: str = "default") -> Path:
    explicit = os.environ.get("HERMES_KANBAN_DB")
    if explicit:
        return Path(explicit)
    root = kanban_root()
    if slug == "default":
        return root / "kanban.db"
    return root / "kanban" / "boards" / slug / "kanban.db"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    task_id = argv[0]
    lines = 40
    if "--lines" in argv:
        try:
            lines = int(argv[argv.index("--lines") + 1])
        except (IndexError, ValueError):
            pass

    slug = board_slug(argv)
    db = board_db(slug)
    print(f"board db : {db}")
    if not db.exists():
        print("  (absent - wrong root/board; set HERMES_KANBAN_HOME, --board or HERMES_KANBAN_DB)")
        return 1

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        print("\n== task ==")
        if row is None:
            print("  not found")
        else:
            for key in ("id", "assignee", "status", "priority", "workspace_kind", "workspace_path",
                        "current_run_id", "last_failure_error", "started_at", "completed_at"):
                if key in row.keys():
                    print(f"  {key:20} {row[key]}")

        print("\n== runs (most recent first) ==")
        try:
            runs = conn.execute(
                "SELECT id, status, worker_pid, started_at, ended_at, outcome, error, metadata "
                "FROM task_runs WHERE task_id = ? ORDER BY id DESC LIMIT 8", (task_id,)
            ).fetchall()
            if not runs:
                print("  none - the task was never spawned (check assignee profile existence)")
            for r in runs:
                print(f"  run {r['id']}: status={r['status']} pid={r['worker_pid']} "
                      f"outcome={r['outcome']} started={r['started_at']} ended={r['ended_at']}")
                if r["error"]:
                    print(f"    error: {r['error']}")
                if r["metadata"]:
                    print(f"    meta : {r['metadata']}")
        except sqlite3.Error as exc:
            print(f"  (task_runs unavailable: {exc})")
    finally:
        conn.close()

    if slug == "default":
        log = kanban_root() / "kanban" / "logs" / f"{task_id}.log"
    else:
        log = kanban_root() / "kanban" / "boards" / slug / "logs" / f"{task_id}.log"
    print(f"\n== worker stdout ({log}) ==")
    if not log.exists():
        print("  (no log - the worker never produced output)")
    else:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        for line in tail:
            print(f"  {line[:400]}")

    print("\n== next checks ==")
    print("  - assignee profile: logs/errors.log and logs/agent.log (full, un-truncated tool errors)")
    print("  - gateway profile: logs/agent.log, lines mentioning 'kanban dispatcher'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
