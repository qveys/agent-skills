---
name: backup-safety-audit
description: "Use when creating or deleting a merge/sync backup. Clean up your own backup once the merge is proven."
version: 1.2.0
author: Hermes Agent
license: MIT
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [git, backup, safety, deletion, verification]
---

# Backup Safety Audit

Decide, with object-level evidence, whether a git-tracked backup or snapshot can be deleted without losing content that is not already on the authoritative remote. The output is a verdict plus the exact deletion command. The deletion runs after explicit human confirmation, except a backup this profile created itself once the audit is clean on a fresh fetch (see the common principle below).

## When to Use

Use when someone wants to reclaim space by removing an old backup, pre-sync snapshot, reconcile dump, or bundle directory, and the data is (or was) git-tracked with a known remote. Do not use for ordinary empty/rotating temp dirs with no git provenance.

## Principe commun à tous les profils : nettoyer ses propres sauvegardes

Une sauvegarde créée avant une fusion, une synchronisation ou une réconciliation est **temporaire** : elle n'existe que le temps de prouver que tout est dans le dépôt de référence. Le profil qui l'a créée la nettoie lui-même dès que la fusion est réussie, sans attendre une alerte de Vigie. Un backup oublié est un défaut du profil créateur.

- **Créateur du backup, fusion réussie et poussée, audit à 0 blob unique** (procédure ci-dessous, `fetch` frais) : supprimer sans redemander, avec un script gardé (chemin, nom et hash du distant revérifiés avant, absence revérifiée après), puis consigner la suppression.
- **Audit non concluant** (blob unique, fusion non poussée, `fetch` impossible, `modified.tar` ou `untracked.tar` non vides et absents du distant) : conserver, signaler avec les chiffres, ne rien supprimer.
- **Un seul backup par opération** : réutiliser le dossier ou supprimer le précédent avant d'en créer un autre. Ne pas empiler un backup par tentative.
- **Backup d'un autre profil ou d'origine inconnue** : ne pas le supprimer de sa propre initiative ; appliquer le Standing Gate ci-dessous.

## Standing Gate

S'applique à tout backup que le profil courant n'a pas créé lui-même, et au profil `vigie` (qui détecte et ne corrige jamais seul) : ne jamais supprimer avant une confirmation explicite ("GO", "supprime", "je confirme"). Une observation ("sûrement encore un backup inutile") est une hypothèse, pas un ordre : restituer le verdict et la commande, puis attendre. Annoncer la suppression comme faite seulement après qu'elle a eu lieu et été revérifiée.

## Procedure

### 1. Inventory the backup before touching anything

List the top level and size each component. A backup is usually a mix of: a nested git repo (`integration/`, `split/`), one or more `*.bundle` files, loose `*.tar`/`*.tar.gz` archives, and an `index`. Note mtimes — a backup created minutes ago by a sync script is a different risk than one left for months.

```bash
ls -la <backup>; du -sh <backup>/*; stat -c '%n %y' <backup>
```

Check no process is using it (`ps aux | grep <backup-name>`) and whether any script references it (`grep -rl <backup-name> /opt/data/cron/jobs.json /opt/data/profiles/*/cron/jobs.json /opt/data/scripts /opt/data/profiles/*/scripts`; chaque profil a ses propres `cron/jobs.json` et `scripts/`, ne pas se limiter à `$HERMES_HOME`). A backup created by a sync script right before a push is redundant once the push succeeds; a backup that is the only copy of unpushed work is not.

### 2. Pin the authoritative remote

Fetch the remote branch fresh and record its hash. This hash is your safety claim — everything below is measured against it, and the deletion step re-checks it is unchanged.

```bash
git -C <repo> fetch --no-tags origin
git -C <repo> rev-parse refs/remotes/origin/main   # record this hash
```

If the fetch fails (no credentials in this environment), pin the cached remote ref, state that caveat in the report, and treat the verdict as needing an explicit GO even for a backup you created: the autonomous-deletion principle requires a fresh fetch.

Build the remote's object set once: `git rev-list --objects <remote-ref>` gives `oid path` lines; the first token of each is the object id. Everything reachable from the remote (all history, not just the tip tree) counts as "safe".

### 3. Enumerate what the backup actually holds, then compare object sets

For every ref inside the backup — branches in the nested repo (`git -C <backup>/integration for-each-ref`), and every head in each bundle (`git bundle list-heads <bundle>`) — run `git rev-list --objects <tip>` and union the oids. Subtract the remote's object set. Classify what is left by type with `git cat-file -t`.

To enumerate a bundle without touching the vault repo, import it into a throwaway bare repo in the scratch dir (`git init --bare`, then `git fetch <bundle> 'refs/heads/*:refs/heads/*'`), run `rev-list --objects` there, and delete it afterwards. Drive git from Python with an argv list and `-C <repo>` (`["git","-C",repo,"rev-list","--objects",ref]`); a single command string with spaces is treated as the executable name and fails.

The decision rests on **blobs**, not commits or trees. See `references/git-object-comparison.md` for the exact recipes and a helper script.

### 4. Apply the decision rule

- **0 missing blobs** → every file content in the backup is on the remote. Safe on content grounds. Historical branch commits that are not ancestors of the remote are fine as long as they carry no unique blob.
- **Missing blobs present** → for each, map it to a path in the backup tree (`git ls-tree -r <tip>`), then check whether the same content exists on the remote at that path or another. "Old version / superseded" (remote has the path at a newer blob, or the content exists elsewhere) is acceptable; a blob whose content appears nowhere on the remote is a real loss and needs an explicit user decision before deleting.
- **Ancestry shortcut:** `git merge-base --is-ancestor <backup-head> <remote>` — if true, the entire committed tree of the backup head is on the remote. This covers the committed part; still check stash and untracked archives separately (steps 5–6).

### 5. Check the stash and local archives separately

A stash and loose `.tar`/`*.tar.gz` archives are not covered by branch refs. For the stash, diff each changed path's blob against the remote by path: identical, or the remote is newer, is safe; an older unique version needs a decision. For a loose archive, hash each file with `git hash-object --stdin` and test the oid against the remote object set — a file present by name may be an older version, so compare content oid, not just path.

### 6. Confirm the remote did not rewind

If you have a prior known remote hash, verify it is still an ancestor of the current one (`git merge-base --is-ancestor <old> <new>`). If the remote moved backward, the backup may be the only copy of content that fell off — re-audit before deleting.

### 7. Report, then delete only on confirmation

Report concisely: the verdict, the object-level numbers (missing blobs, bytes), the single caveat (usually "historical working-branch commits not on the remote, but their content is"), and the exact deletion command. Ask for GO. On confirmation, delete with a guarded script that re-checks the path, name, and remote hash, then re-verifies absence:

```python
import shutil, subprocess, pathlib
p = pathlib.Path('<backup>')
assert p.parent == pathlib.Path('<backups-dir>') and p.name == '<backup-name>'
assert p.exists() and p.is_dir() and not p.is_symlink()
assert subprocess.run(['git','-C','<repo>','rev-parse','refs/remotes/origin/main'],
                      capture_output=True,text=True).stdout.strip() == '<pinned-hash>'
shutil.rmtree(p)
assert not p.exists()
```

The assertions fail closed: a wrong name, a moved remote, or a symlink all abort before any deletion.

## Pitfalls

- **Judge by missing blobs, not missing commits.** A backup can hold historical working branches (split/reconcile/vps-wip) whose commits are not ancestors of the remote while their file content fully is. "All commits are ancestors" is the wrong test; "0 blobs absent from remote history" is the right one.
- **Filter invalid oids before `cat-file`.** `rev-list --objects` can surface reflog artifacts or refs whose objects were pruned; `cat-file -t` on them raises. Wrap in try/except and count by type instead of crashing, or one bad oid aborts the whole audit.
- **Bundle heads may name temporary refs** (e.g. `sync-upload-2026-10-19`) that were never pushed. Their absence from the remote is expected, not data loss — do not flag them as a gap.
- **Compute loose-archive oids with `git hash-object --stdin` on the raw bytes.** A hand-built `sha1("blob N\0" + data)` easily gets the header wrong and reports every file as missing or present by accident.
- **When a user asks to inspect further, go to the object level and stop at a verdict.** A report that ends on "cannot certify" with unexplained counts forces another round; classify every remaining object (commit, tree, invalid, blob) and say which classes carry content.
- **Re-pin the remote hash right before deleting.** The remote can advance (or rewind) between audit and deletion; asserting the pinned hash is unchanged guarantees you delete against the safety claim you actually verified.
- **A file present by name on the remote is not the same file.** Compare content oids. An archive entry can be an older version of a path the remote now holds at a newer blob; name-match would falsely certify it.
- **A conditional confirmation binds the scope.** "Delete if it is only the old version / the obsolete report" authorizes deletion only when the audit shows exactly that: map each remaining blob or archive file to the condition, say which part is old/superseded, and delete only if all of it fits. Anything outside the stated condition goes back to the user.
- **Pre-sync snapshots recur.** A sync script that dumps a backup before each push will refill the space you just freed unless something purges old ones. If none does, flag it and offer to add a retention step rather than assuming they self-clean.

## Report Format

Lead with the verdict in one line. Then: what the backup is and its size, the object-level numbers (missing blobs + bytes, ancestry result), the single real caveat, the exact deletion command, and what is left untouched (active data like `state.db`, `checkpoints/`). End by asking for GO. Keep it short — this is a go/no-go, not a narrative.
