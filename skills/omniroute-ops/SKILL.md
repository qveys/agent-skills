---
name: omniroute-ops
description: Operate OmniRoute (Task Router, combos, IP whitelist, cache/cost, real vs virtual models) from what is actually installed, preferring the admin UI over source changes. Use when the user mentions OmniRoute, Task Router, `omniroute connect` / `models list`, vps-dokploy OmniRoute, or says "Ne fais aucune supposition : base-toi uniquement sur ce qui est réellement installé sur ce serveur" or wants to configure a feature in the interface without modifying source.
user-invocable: true
---

# OmniRoute ops

OmniRoute is not Paperclip. Do not use `paperclip-vps` for OmniRoute on vps-dokploy.

## Triggers

- "Ne fais aucune supposition : base-toi uniquement sur ce qui est réellement installé sur ce serveur."
- "Je ne cherche pas à modifier le code source si ce n'est pas nécessaire. Je veux avant tout savoir **comment configurer cette fonctionnalité dans l'interface**."
- Task Router, combos, IP whitelist, cache/cost, real vs virtual models, `omniroute connect`, `omniroute models list`.

## Steps

1. Inspect the live install on the server (or the local CLI) before proposing anything. Do not assume features, versions, or UI labels.
2. Prefer the admin UI. Change source only when a setting is not available in the interface, and say so first.
3. If the user named a cockpit, use it via `wsh-cockpit`. Typical OmniRoute host is `vps-dokploy`, not `vps-openclaw`.
4. For Task Router work: identify the installed version, whether Task Router exists there, and the current config, then give UI path + value + why for each field.
5. For combos: prefer real (non-virtual) models; do not leave routing on slow virtuals; rotate so the same models are not always called.
6. For IP whitelist errors (`IP not in whitelist`), treat access-list changes as the job, not a code patch.
7. Local CLI: `omniroute connect` then `omniroute models list` — diagnose from actual CLI output.
