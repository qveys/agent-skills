# Repo-owned gates

A repo that ships its own checker scripts makes those scripts the acceptance criteria for every
change to it. Run them, respect the invariants they encode, and extend them when you change what
they measure. The repo's `AGENTS.md` usually names them.

## Run both stages, self-test first

- Typical shape: `scripts/<name>-check.mjs --self-test` (unit assertions on the checker) then
  `--check` (the live repo). The self-test is the fast, hermetic stage; run it first so a live-stage
  crash is not confused with a real violation.
- A gate that CRASHES (`ENOENT`, uncaught throw) in a fresh worktree is usually a missing input,
  not a finding: unpopulated submodule (`git submodule update --init --recursive`), symlink target
  git has not restored yet, or an ignored directory that only exists in the canonical checkout.
  Populate it and re-run before reading anything into the result.
- Run the gate in the worktree where you made the change, then confirm the canonical checkout is
  untouched (`git status --porcelain` empty, `wc -c` on the file unchanged until the merge).

## Content invariants a gate may enforce

Extract the rules from the checker's source instead of guessing. The usual ones:

- **Byte budgets** on a hand-maintained file (e.g. a dispatcher under 10 000 bytes).
- **Forbidden strings or characters** (an em-dash ban, a banned legacy path).
- **Required machine-readable markers**, e.g. provenance and `SHA256` HTML comments. These often
  certify the UPSTREAM file, not your local text, so they must survive a local rewrite byte for
  byte. Re-read the checker's regex to confirm what each marker is compared against.
- **Generated files that must match their source** (projections): regenerate via the repo's own
  script, never hand-edit.
- For checks in worktrees, normalize checkout-specific absolute path prefixes before comparing a
  generated manifest, while still validating stable fields such as hashes, sizes and filenames;
  otherwise identical source trees fail only because their worktree roots differ.

### Measure before rewriting a budgeted file

Split by heading and count bytes per section, so the trim targets the fat instead of the rules:

```python
import re
from pathlib import Path
p = Path("AGENTS.md")
t = p.read_text(encoding="utf-8")
parts = re.split(r'(?m)^(#{2,3} .*)$', t)
print("total", len(t.encode()))
for i in range(1, len(parts), 2):
    print(f"{parts[i][:40]:42} {len((parts[i] + parts[i+1]).encode()):5}")
```

Then compress prose, not rules: merge redundant sentences, drop parenthetical restatements, and
keep every table row, trigger example and constraint. Re-check after writing:

```python
assert t.count("\u2014") == 0                                          # banned character
assert len([l for l in t.splitlines() if l.startswith("| `")]) == 14    # rows preserved
assert t.splitlines()[:2] == before.splitlines()[:2]                   # markers untouched
```

Report the before/after byte count and the freed margin, not just "lighter".

## When you change a gate

- Add assertions to `--self-test` for the new behaviour: boundary values on both sides of the
  threshold, the absent-file case, and a strict deep-equal on the returned object.
- Extend the stage's success line so a human reading the output sees the new coverage.
- Advisory output goes to STDOUT when the caller (scheduler, CI) delivers stdout verbatim and only
  surfaces stderr on failure; keep exit 0 for advice and non-zero for violations.
- Prefer a dedicated threshold line ("`AGENTS.md`: 8695 / 10000 octets, marge 1305") plus a warning
  line under the threshold over relying on the limit failure.

### Commit-time generated inventory checks

- Give generated inventory tools a non-mutating `--check` mode that accepts explicit source and
  manifest paths, returns non-zero for missing, malformed or stale data, and never rewrites the
  manifest. Assert byte-for-byte preservation on both success and failure.
- Trigger the gate for staged additions, copies, modifications, deletions, renames and type changes
  (`ACDMRT`) to either the source tree, manifest or generator; include every trigger in the
  early-exit condition so deletions cannot skip validation.
- Validate the commit, not the worktree: materialize all relevant indexed sources, manifests and the generator itself to a temporary snapshot with `git ls-files -z -- <paths> | git checkout-index --stdin -z --prefix="$snapshot/"`, then run the indexed checker against that snapshot using explicit paths. The worktree can retain a staged deletion or contain a later unstaged edit, so scanning it can approve or reject the wrong bytes. If the indexed checker is missing or lacks the required check mode, fail closed; never fall back to a permissive worktree copy.
- Test the installed hook via a temporary Git repository and real `git commit`. Cover stale
  additions/modifications/deletions, a staged deletion whose worktree file remains, a valid staged
  version with a later unstaged edit, an unstaged permissive checker against a strict indexed one,
  forbidden-extension renames, non-regular indexed modes, and each inventory mode when one generator
  serves multiple source trees. Invoke the hook directly only for fast unit-level checks.
- If symlinks are not part of the data model, reject index mode `120000` before scanning for every
  checked path: sources, manifests/inventories and the checker itself. `checkout-index` restores a
  symlink, while path resolution or Python execution can follow its target outside the snapshot.
  Accept only regular blob modes (`100644`/`100755`) for those paths; fail closed on gitlinks or
  other modes.
- Match scanner scope to accepted sources. If the scanner is non-recursive, reject nested staged
  source paths or teach the scanner to represent them; ensure every extension the hook admits is
  included in the matching inventory, with case handling consistent between hook and scanner.
- Normalize paths relative to the stable source root (for example `books/<filename>`), not by
  basename alone; basename-only comparison accepts manifests pointing at unrelated locations.
  Preserve stable metadata such as hashes, sizes, filenames and duplicate information.

## Editing a repo outside the write-safe root

When the repo lives outside `HERMES_WRITE_SAFE_ROOT`, the file-editing tools refuse with
`outside HERMES_WRITE_SAFE_ROOT` and `terminal` is the sanctioned path. Do not hand-type `sed`:

1. `write_file` a Python script into a writable directory (e.g. `$HERMES_REAL_HOME`).
2. In it, read the target, apply each replacement with an exact single-match assertion
   (`if src.count(old) != 1: abort`), write it back, print the new size.
3. Run it with `terminal`, then run the repo's gate to prove the result.

This keeps the edit reviewable and fails loudly on a stale anchor. It does not apply to a refusal
that reports a withheld approval (protected prompt files): that is a stop-and-ask, not a path to
route around.
