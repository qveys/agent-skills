#!/usr/bin/env bash
# Sondes lecture seule avant autonomie. Sortie : PASS|FAIL|WARN<TAB>libellé<TAB>détail.
# Code retour = nombre de FAIL. Ne jamais afficher de valeur secrète.
set -u

T="${PREFLIGHT_TIMEOUT:-8}"
FAILS=0

usage() {
  cat <<'USAGE'
Usage: preflight.sh [--ssh HOST]... [--tailscale-ssh HOST]... [--env FILE KEY]...
                    [--cmd "libellé::commande"]... [--no-auto]
Env: PREFLIGHT_TIMEOUT (secondes par sonde, défaut 8)
USAGE
}

# run_t : exécute avec timeout (timeout/gtimeout, sinon perl alarm)
run_t() {
  if command -v timeout >/dev/null 2>&1; then timeout "$T" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$T" "$@"
  elif command -v perl >/dev/null 2>&1; then perl -e 'alarm shift; exec @ARGV or exit 127' "$T" "$@"
  else "$@"; fi
}

emit() { # statut libellé détail
  [ "$1" = FAIL ] && FAILS=$((FAILS + 1))
  printf '%s\t%s\t%s\n' "$1" "$2" "$3"
}

# probe LIBELLÉ FAIL_STATUT CMD... : PASS si rc=0, sinon FAIL_STATUT (FAIL ou WARN)
probe() {
  local label=$1 bad=$2 out rc
  shift 2
  out=$(run_t "$@" 2>&1 </dev/null)
  rc=$?
  out=$(printf '%s' "$out" | tr '\n\t' '  ' | cut -c1-160)
  if [ "$rc" -eq 0 ]; then emit PASS "$label" "${out:-ok}"
  elif [ "$rc" -eq 124 ] || [ "$rc" -eq 142 ]; then emit "$bad" "$label" "timeout ${T}s"
  else emit "$bad" "$label" "rc=$rc ${out}"; fi
}

env_probe() { # FILE KEY : jamais la valeur
  local file=$1 key=$2 line val
  if [ ! -f "$file" ]; then emit FAIL "env $key" "ABSENT (fichier $file introuvable)"; return; fi
  line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n1)
  if [ -z "$line" ]; then emit FAIL "env $key" "ABSENT"; return; fi
  val=${line#*=}
  val=$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//")
  if [ -n "$val" ]; then emit PASS "env $key" "SET"; else emit FAIL "env $key" "EMPTY"; fi
}

ssh_list=() tsh_list=() env_list=() cmd_list=() AUTO=1
while [ $# -gt 0 ]; do
  case $1 in
    --ssh) [ $# -ge 2 ] || { usage; exit 2; }; ssh_list+=("$2"); shift 2 ;;
    --tailscale-ssh) [ $# -ge 2 ] || { usage; exit 2; }; tsh_list+=("$2"); shift 2 ;;
    --env) [ $# -ge 3 ] || { usage; exit 2; }; env_list+=("$2|$3"); shift 3 ;;
    --cmd) [ $# -ge 2 ] || { usage; exit 2; }; cmd_list+=("$2"); shift 2 ;;
    --no-auto) AUTO=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [ "$AUTO" -eq 1 ]; then
  if command -v claude-gh-check >/dev/null 2>&1; then probe "claude-gh-check" FAIL claude-gh-check
  else emit WARN "claude-gh-check" "absent"; fi
  if command -v git-signed-commit >/dev/null 2>&1; then emit PASS "git-signed-commit" "présent"
  else emit WARN "git-signed-commit" "absent"; fi
  if command -v gh >/dev/null 2>&1; then probe "gh auth status" FAIL gh auth status; fi
  probe "sudo -n" WARN sudo -n true
fi

for h in ${ssh_list[@]+"${ssh_list[@]}"}; do
  probe "ssh $h" FAIL ssh -o BatchMode=yes -o "ConnectTimeout=$T" "$h" true
done
for h in ${tsh_list[@]+"${tsh_list[@]}"}; do
  before=$FAILS
  probe "tailscale ssh $h" FAIL tailscale ssh "$h" true
  if [ "$FAILS" -gt "$before" ] && command -v tailscale >/dev/null 2>&1; then
    emit WARN "tailscale status" "$(run_t tailscale status 2>&1 </dev/null | head -n3 | tr '\n\t' '  ' | cut -c1-160)"
  fi
done
for e in ${env_list[@]+"${env_list[@]}"}; do env_probe "${e%%|*}" "${e#*|}"; done
for c in ${cmd_list[@]+"${cmd_list[@]}"}; do
  case $c in
    *::*) probe "${c%%::*}" FAIL bash -c "${c#*::}" ;;
    *) probe "$c" FAIL bash -c "$c" ;;
  esac
done

exit "$FAILS"
