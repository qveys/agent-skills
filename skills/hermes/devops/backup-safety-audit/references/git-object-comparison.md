# Git Object-Comparison Recipes

Depth for steps 3–5 of the backup safety audit. All commands run against the repo that can see both the backup's objects and the remote (usually the live vault repo; a nested backup repo shares the same object store).

## Build the remote object set

```bash
# oid list of everything reachable from the remote (all history)
git -C <repo> rev-list --objects refs/remotes/origin/main | awk '{print $1}' > "$TMPDIR"/remote_objs.txt
```

`rev-list --objects` prints `oid<space>path`; the path is optional (trees/commits have none). Everything listed is "safe" — the remote can reconstruct it.

## Union all backup refs into one object set

```python
import subprocess, pathlib

def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True).stdout.decode()

repo = '<repo>'
backup = pathlib.Path('<backup>')
nested = str(backup / 'integration')

# refs in a nested backup repo
tips = git(nested, 'for-each-ref', '--format=%(objectname)').split()

# heads declared in each bundle
gitrepo = subprocess.run(['git', 'bundle', 'list-heads', str(backup / 'refs.bundle')],
                         capture_output=True, text=True).stdout
tips += [line.split()[0] for line in gitrepo.splitlines() if line and ' refs/' in line]

# union of every reachable object, with paths
all_objs = {}
for tip in set(tips):
    for line in git(repo, 'rev-list', '--objects', tip).splitlines():
        parts = line.split(' ', 1)
        all_objs[parts[0]] = parts[1] if len(parts) > 1 else ''
```

## Classify what is missing, by type (robust to invalid oids)

```python
import os
remote = set(open(os.path.join(os.environ.get('TMPDIR','/tmp'),'remote_objs.txt')).read().split())
missing = [o for o in all_objs if o not in remote]

from collections import Counter
types = Counter()
blobs = []
for o in missing:
    try:
        t = git(repo, 'cat-file', '-t', o).strip()
    except Exception:      # reflog artifact / pruned object
        types['invalid'] += 1
        continue
    types[t] += 1
    if t == 'blob':
        size = int(git(repo, 'cat-file', '-s', o).strip())
        blobs.append((o, size))
print(types, 'missing_blobs', len(blobs), 'bytes', sum(s for _, s in blobs))
```

**Read:** `missing_blobs == 0` → content-safe. Non-zero `commit`/`tree` with zero blobs → historical structure only, no file content lost. `invalid` entries are reflog/prune artifacts, not data.

## Map a missing blob to its path and check the remote

```python
head = git(nested, 'rev-parse', 'HEAD').strip()
backup_paths = {line.split('\t', 1)[1]: line.split()[0]
                for line in git(repo, 'ls-tree', '-r', head).splitlines()}
remote_paths = {line.split('\t', 1)[1]: line.split()[0]
                for line in git(repo, 'ls-tree', '-r', 'refs/remotes/origin/main').splitlines()}

for oid, size in blobs:
    path = next((p for p, c in backup_paths.items() if c == oid), '(no path)')
    if remote_paths.get(path) == oid:
        print('SAME_ON_REMOTE', path)
    elif path in remote_paths:
        print('SUPERSEDED', path, 'backup', oid[:8], 'remote', remote_paths[path][:8])
    else:
        print('ABSENT', path, size, 'B')   # real loss -> needs user decision
```

## Ancestry shortcut

```bash
# is the whole committed tree of the backup head on the remote?
git -C <repo> merge-base --is-ancestor <backup-head> refs/remotes/origin/main && echo SAFE || echo NOT_FULLY
```

## Stash content check (stash is not a branch ref)

```python
stash = git(repo, 'rev-parse', 'refs/stash').strip()
for line in git(repo, 'diff', '--name-status', stash + '^1', stash).splitlines():
    status, path = line.split('\t', 1)
    blob = git(repo, 'rev-parse', f'{stash}:{path}').strip()
    print('STASH_SAME' if remote_paths.get(path) == blob else 'STASH_DIFF', path)
    # STASH_DIFF: remote-newer is safe; older-unique is a loss
```

## Loose archive content check

```python
import tarfile, hashlib

def blob_oid(data: bytes) -> str:
    h = hashlib.sha1(b'blob %d\x00' % len(data))
    h.update(data)
    return h.hexdigest()

with tarfile.open(str(backup / 'local-files.tar.gz'), 'r:gz') as t:
    for m in t.getmembers():
        if not m.isfile():
            continue
        data = t.extractfile(m).read()
        print('ARCHIVE', 'SAFE' if blob_oid(data) in remote else 'ABSENT', len(data), m.name)
```

`git hash-object --stdin` computes the same oid as the manual sha1; use whichever is handier.
