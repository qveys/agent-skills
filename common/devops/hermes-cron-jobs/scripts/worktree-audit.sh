#!/usr/bin/env bash
# Audit mensuel de la règle workspace (Quentin, 29/10/2026) :
# tout worktree Git du workspace vit dans /workspace/.worktrees/, jamais à la racine.
# Rien sur stdout = RAS = rien n'est livré (dédup par silence).
# SOURCE VERSIONNÉE dans cette skill — après recréation du conteneur, recopier
# dans $HERMES_HOME/scripts/worktree-audit.sh avant de recréer le job cron.
set -euo pipefail

WS=/workspace
WT_DIR="$WS/.worktrees"
violations=0

# Un worktree git = dossier dont .git est un FICHIER (gitdir: ...).
# Un repo canonique = dossier dont .git est un répertoire.
while IFS= read -r -d '' d; do
  base=$(basename "$d")
  [ "$d" = "$WT_DIR" ] && continue
  if [ -f "$d/.git" ]; then
    branch=$(git -C "$d" branch --show-current 2>/dev/null || echo "detached")
    printf '🏗️ worktree à la racine : %s (branche %s)\n' "$base" "$branch"
    violations=$((violations+1))
  fi
done < <(find "$WS" -maxdepth 1 -mindepth 1 -type d -print0)

if [ "$violations" -gt 0 ]; then
  printf '\n⚠️ WORKTREES · %d hors du dossier .worktrees (règle 29/10/2026)\n' "$violations"
  printf '· déplacer avec : git worktree move <wt> /workspace/.worktrees/<wt>\n'
fi
