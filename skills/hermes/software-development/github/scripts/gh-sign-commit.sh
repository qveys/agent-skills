#!/usr/bin/env bash
# gh-sign-commit.sh — crée un commit SIGNÉ (verified, committer GitHub) sur une branche via
# GraphQL createCommitOnBranch. La mutation avance elle-même la ref de la branche.
#
# Pourquoi : la protection « Require signed commits » bloque les PR dont les commits sont
# « unsigned » (pushes CLI). Les comptes bot GitHub App ne peuvent PAS recevoir de clé SSH/GPG
# (403 sur POST user/ssh_signing_keys) ; le seul moyen d'avoir des commits verified pour un bot
# est de les créer via l'API (GitHub signe automatiquement, committer=GitHub).
#
# Usage :
#   REF=refs/heads/<branche> PARENT=<sha-parent> MESSAGE="titre" gh-sign-commit.sh path1 [path2 ...]
# Les fichiers sont lus depuis le répertoire courant. Affiche sha / verified / committer.
# Prérequis : gh authentifié (token de l'App), dépôt courant = repo cible, python3.
#
# Le message et les chemins sont passés comme VARIABLES GraphQL (JSON), jamais interpolés dans la
# requête : guillemets, antislash, retours à la ligne et emoji sont sans danger.
set -euo pipefail

REPO="$(git remote get-url origin | sed -E 's#.*github.com[:/]([^/]+/[^/.]+)(\.git)?$#\1#')"
REF="${REF:-refs/heads/main}"
PARENT="${PARENT:?PARENT (sha du parent, ex. main) requis}"
MESSAGE="${MESSAGE:?MESSAGE requis}"
BRANCH="${REF#refs/heads/}"
[ "$#" -ge 1 ] || { echo "au moins un chemin requis" >&2; exit 2; }

REPO_OK="$(gh api "repos/$REPO" --jq .full_name)"

BODY="$(REPO_OK="$REPO_OK" BRANCH="$BRANCH" PARENT="$PARENT" MESSAGE="$MESSAGE" python3 - "$@" <<'PY'
import base64, json, os, sys
query = """mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}"""
additions = [{"path": p, "contents": base64.b64encode(open(p, "rb").read()).decode()} for p in sys.argv[1:]]
variables = {"input": {
    "branch": {"repositoryNameWithOwner": os.environ["REPO_OK"], "branchName": os.environ["BRANCH"]},
    "message": {"headline": os.environ["MESSAGE"]},
    "expectedHeadOid": os.environ["PARENT"],
    "fileChanges": {"additions": additions},
}}
print(json.dumps({"query": query, "variables": variables}))
PY
)"

OID="$(printf '%s' "$BODY" | gh api graphql --input - --jq '.data.createCommitOnBranch.commit.oid')"
[ -n "$OID" ] || { echo "ÉCHEC : aucun oid retourné par createCommitOnBranch" >&2; exit 1; }

gh api "repos/$REPO/commits/$OID" --jq '{sha: .sha[:7], verified: .commit.verification.verified, reason: .commit.verification.reason, committer: .commit.committer.name}'
