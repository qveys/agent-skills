"""Fix blocked/running cards whose workers completed the work but failed to call kanban_complete.

Finds every blocked or running card for a given assignee, checks whether the
expected artifact (fiche or synthesis) exists on disk, and either marks the
card done or unblocks it for retry.

Usage:
    python3 kanban_fix_stale_completion.py <assignee> [--fiche-dir <path>] [--syn-dir <path>]
                                           [--board <slug>] [--apply]

Examples (exemple : projet de corpus de livres, fiches nommées sha256-<hash>.md) :
    python3 kanban_fix_stale_completion.py lecteur --fiche-dir <projet>/knowledge/books
    python3 kanban_fix_stale_completion.py stratege --syn-dir <projet>/knowledge/synthesis

Assignee is required. Directories can also come from the env vars
KANBAN_FICHE_DIR / KANBAN_SYN_DIR ; sans dossier, aucun artefact n'est
trouvé et rien n'est marqué done. Le board vient de --board, sinon
HERMES_KANBAN_BOARD, sinon du board courant (<racine>/kanban/current).
Le script suppose qu'une fiche/synthèse porte le sha256 (64 hex) de la
source dans son nom et que le corps de la carte cite `sha256-<hash>`.

Read-only scan (--dry-run is the default). Pass --apply to actually write.
"""

from __future__ import annotations

import os
import re
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


def artifact_dirs(fiche_dir: str | None, syn_dir: str | None) -> tuple[set[str], set[str]]:
    fdir = Path(fiche_dir or os.environ.get("KANBAN_FICHE_DIR") or "/nonexistent-fiche-dir")
    sdir = Path(syn_dir or os.environ.get("KANBAN_SYN_DIR") or "/nonexistent-syn-dir")
    fiches = {f for f in os.listdir(fdir)
              if f.startswith("sha256-") and "_atomic" not in f} if fdir.exists() else set()
    syns = {f for f in os.listdir(sdir)
            if f.endswith(".md") and not f.startswith(".")} if sdir.exists() else set()
    return fiches, syns


def sha_from_body(body: str | None) -> str | None:
    m = re.search(r"sha256-([0-9a-f]{64})", body or "")
    return m.group(1) if m else None


def is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def fix_assignee_cards(assignee: str, fiche_dir: str | None, syn_dir: str | None,
                       dry_run: bool = True, slug: str = "default") -> dict:
    db_path = board_db(slug)
    if not db_path.exists():
        print(f"Board DB not found at {db_path} — set --board / HERMES_KANBAN_HOME / HERMES_KANBAN_DB")
        return {}

    need = fiche_dir or os.environ.get("KANBAN_FICHE_DIR") if assignee == "lecteur" else syn_dir or os.environ.get("KANBAN_SYN_DIR")
    if not need or not Path(need).is_dir():
        print("Error: dossier d'artefacts absent (--fiche-dir pour lecteur, --syn-dir sinon) — "
              "sans lui tout serait vu comme « artefact manquant » et débloqué à tort.")
        return {}
    fiches, syns = artifact_dirs(fiche_dir, syn_dir)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, status, worker_pid, consecutive_failures, body
        FROM tasks
        WHERE assignee=? AND status IN ('running', 'blocked')
    """, (assignee,))
    tasks = cur.fetchall()

    marked_done = []
    unblocked = []
    no_action = []

    for tid, title, status, pid, cf, body in tasks:
        sha = sha_from_body(body)
        if assignee == "lecteur":
            found = any(f"sha256-{sha}" in f for f in fiches) if sha else False
        else:
            found = any(sha in s for s in syns) if sha else False

        alive = is_alive(pid)

        if found and status != "done":
            if dry_run:
                print(f"  [DRY] would mark done: {tid} (sha={sha[:16] if sha else '?'}... {title[:40]})")
            else:
                cur.execute(
                    "UPDATE tasks SET status='done', consecutive_failures=0 WHERE id=?",
                    (tid,)
                )
                conn.commit()
                print(f"  ✓ done (fiche existed): {tid} {title[:40]}")
            marked_done.append(tid)
        elif status == "blocked" and not found:
            if dry_run:
                print(f"  [DRY] would unblock: {tid} (sha={sha[:16] if sha else '?'}...)")
            else:
                cur.execute(
                    "UPDATE tasks SET status='ready', consecutive_failures=0 WHERE id=?",
                    (tid,)
                )
                conn.commit()
                print(f"  → unblocked: {tid} {title[:40]}")
            unblocked.append(tid)
        else:
            no_action.append(tid)

    conn.close()
    return {"done": marked_done, "unblocked": unblocked, "no_action": no_action}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0

    assignee = None
    fiche_dir = None
    syn_dir = None
    dry_run = True

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--apply":
            dry_run = False
        elif arg == "--fiche-dir" and i + 1 < len(argv):
            fiche_dir = argv[i + 1]
            i += 1
        elif arg == "--syn-dir" and i + 1 < len(argv):
            syn_dir = argv[i + 1]
            i += 1
        elif arg == "--board" and i + 1 < len(argv):
            i += 1
        elif not arg.startswith("--"):
            assignee = arg
        i += 1

    if not assignee:
        print("Error: assignee is required")
        print(__doc__)
        return 1

    mode = "DRY RUN (pass --apply to write)" if dry_run else "APPLYING"
    print(f"\n=== Fix stale completions [{mode}] assignee={assignee} ===")
    result = fix_assignee_cards(assignee, fiche_dir, syn_dir, dry_run, board_slug(argv))
    print(f"\nSummary: {len(result.get('done', []))} marked done, "
          f"{len(result.get('unblocked', []))} unblocked, "
          f"{len(result.get('no_action', []))} left unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
