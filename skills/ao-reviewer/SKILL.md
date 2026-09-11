---
name: ao-reviewer
description: Execute Auto-Orchestrator (AO) reviewer tasks from ~/.ao/data/prompts/<job>/reviewer/requests/<id>/<id>/task.md. Use when the user says "Read and follow the AO review task", names a task.md under .ao/data/prompts, or asks to send findings back to the AO worker. Not for bundled /review (local changes, named branch, or GitHub PR subagent).
user-invocable: true
---

# AO reviewer

When the user points at an AO reviewer `task.md`, follow that file. Do not run bundled `/review`.

## Triggers

- "Read and follow the AO review task in `/Users/qveys/.ao/data/prompts/<job>/reviewer/requests/<id>/<id>/task.md`."
- "Envoie ton résultat au worker si ce n'est pas déjà fait"
- "Envoi tes findings au worker"

## Steps

1. Read the `task.md` path the user named. That file is the contract.
2. Work in the AO worktree already checked out (typically `~/.ao/data/worktrees/<job>/...`). Do not switch to another checkout.
3. Complete every review task in the queue autonomously. Do not ask whether to continue to the next PR.
4. For each PR, post a GitHub review with `gh api` POST `repos/{owner}/{repo}/pulls/{number}/reviews` as `event: COMMENT` (own-PR APPROVE/REQUEST_CHANGES is rejected). Capture the review id.
5. After GitHub posts, submit AO bookkeeping with `ao review submit --session <job> --reviews -` (JSON on stdin; never write that payload into the worktree).
6. If the user already asked to send findings, do step 5 even when GitHub posting failed (empty githubReviewId).
7. Do not treat this as bundled `review`.
