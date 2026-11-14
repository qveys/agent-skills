#!/usr/bin/env bash
# Sondes lecture seule avant autonomie. Sortie : PASS|FAIL|WARN<TAB>libellé<TAB>détail.
# Code retour = nombre de FAIL ; 64 = erreur d'usage. Ne jamais afficher de valeur secrète.
set -u

T="${PREFLIGHT_TIMEOUT:-8}"
FAILS=0

usage() {
  cat <<'USAGE'
Usage: preflight.sh [--http URL]... [--git-remote] [--cli NOM]...
                    [--ssh HOST]... [--tailscale-ssh HOST]... [--env FILE KEY]...
                    [--cmd "libellé::commande"]... [--profil gh-harnais]
Env: PREFLIGHT_TIMEOUT (secondes par sonde, défaut 8)
Sans option : aucune sonde. Tout est à la demande. Code retour = nombre de FAIL (63 = 63 ou plus), 64 = erreur d'usage.
--http : GET avec timeout, 2xx/3xx PASS, 401/403 WARN (joignable, auth à vérifier), reste FAIL.
--git-remote : git ls-remote --heads origin (dépôt courant).
--cli : binaire présent dans le PATH.
--cmd (« :: » obligatoire) est exécuté via bash -c : entrée de confiance uniquement ;
  sa sortie est affichée (seuls les identifiants d'URL sont masqués) et peut contenir des secrets.
--no-auto : accepté, sans effet (déprécié, plus aucune sonde automatique).
Les URL avec identifiants sont masquées dans les sorties.
Pas de chemin ni de query dans les libellés http. Un hôte ne peut pas commencer par « - », une URL doit commencer par http(s)://.
--profil gh-harnais : opt-in, voir references/profils.md.
USAGE
}

# run_t : exécute avec timeout (timeout/gtimeout, sinon perl alarm)
run_t() {
  if command -v timeout >/dev/null 2>&1; then timeout "$T" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$T" "$@"
  elif command -v perl >/dev/null 2>&1; then perl -e 'my $t = shift; my $p = fork; if (!$p) { setpgrp(0, 0); exec @ARGV or exit 127 } $SIG{ALRM} = sub { kill "TERM", -$p; kill "KILL", -$p; exit 124 }; alarm $t; waitpid($p, 0); exit($? >> 8 || ($? & 127 ? 128 + ($? & 127) : 0))' "$T" "$@"
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
  # identifiants intégrés aux URL masqués dans toute sortie d'outil externe
  out=$(printf '%s' "$out" | tr '\n\t' '  ' | sed -e 's#://[^ ]*@#://#g' | cut -c1-160)
  if [ "$rc" -eq 0 ]; then emit PASS "$label" "${out:-ok}"
  elif [ "$rc" -eq 124 ] || [ "$rc" -eq 142 ]; then emit "$bad" "$label" "timeout ${T}s"
  else emit "$bad" "$label" "rc=$rc ${out}"; fi
}

env_probe() { # FILE KEY : jamais la valeur
  local file=$1 key=$2 line val
  if [ ! -f "$file" ]; then emit FAIL "env $key" "ABSENT (fichier $file introuvable)"; return; fi
  line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n1) # clé validée (^[A-Za-z_][A-Za-z0-9_]*$)
  if [ -z "$line" ]; then emit FAIL "env $key" "ABSENT"; return; fi
  val=${line#*=}
  val=$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//" -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
  if [ -n "$val" ]; then emit PASS "env $key" "SET"; else emit FAIL "env $key" "EMPTY"; fi
}

ok_host() { case $1 in -*|''|*[[:cntrl:]]*) return 1 ;; esac; } # cntrl (\n \r tab) : forgerait une ligne TSV
ok_key() { printf '%s' "$1" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*$'; }

ok_url() { case $1 in *[[:cntrl:]]*) return 1 ;; http://*|https://*) return 0 ;; *) return 1 ;; esac; }
ok_cli() { printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_][A-Za-z0-9._+-]*$'; }

http_probe() { # URL : code HTTP seul, URL affichée sans userinfo ni query
  local url=$1 label code
  # libellé = scheme://host[:port] seulement (le chemin ou le fragment peuvent porter un jeton)
  label=$(printf '%s' "$url" | sed -e 's#://[^ ]*@#://#' | sed -E 's#^([a-z]+://)([^/?\#]*).*#\1\2#')
  if ! command -v curl >/dev/null 2>&1; then emit FAIL "http $label" "curl absent"; return; fi
  # URL passée par stdin (config curl) : un jeton en query n'apparaît pas dans argv/ps
  code=$(printf 'url = "%s"\n' "$(printf '%s' "$url" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')" |
    run_t curl -s -o /dev/null -w '%{http_code}' --max-time "$T" -K - 2>/dev/null)
  case $code in
    2??|3??) emit PASS "http $label" "$code" ;;
    401|403) emit WARN "http $label" "$code joignable, auth à vérifier" ;;
    *) emit FAIL "http $label" "${code:-000} injoignable ou erreur" ;;
  esac
}

# profil opt-in : harnais d'accès git/gh. Absent = SKIP silencieux.
profil_gh_harnais() {
  [ -n "${PREFLIGHT_HARNESS_DIR:-}" ] && [ -d "$PREFLIGHT_HARNESS_DIR" ] && PATH="$PREFLIGHT_HARNESS_DIR:$PATH"
  if command -v claude-gh-check >/dev/null 2>&1; then probe "claude-gh-check" FAIL claude-gh-check; fi
  if command -v git-signed-commit >/dev/null 2>&1; then emit PASS "git-signed-commit" "présent"; fi
  if command -v gh >/dev/null 2>&1; then probe "gh auth status" FAIL gh auth status; fi
}

# garde unique : aucun argument ne porte de caractère de contrôle (\n \r tab ESC…) ;
# message sans l'argument fautif (sinon l'ESC ressortirait). Vaut aussi pour la commande de --cmd.
for arg in "$@"; do
  case $arg in *[[:cntrl:]]*) echo "preflight.sh : argument avec caractère de contrôle refusé" >&2; exit 64 ;; esac
done

ssh_list=() tsh_list=() env_list=() cmd_list=() http_list=() cli_list=() GITREMOTE=0 PROFIL=
while [ $# -gt 0 ]; do
  case $1 in
    --ssh) { [ $# -ge 2 ] && ok_host "$2"; } || { usage; exit 64; }; ssh_list+=("$2"); shift 2 ;;
    --no-auto) shift ;;
    --tailscale-ssh) { [ $# -ge 2 ] && ok_host "$2"; } || { usage; exit 64; }; tsh_list+=("$2"); shift 2 ;;
    --env) { [ $# -ge 3 ] && ok_key "$3"; } || { usage; exit 64; }; env_list+=("$2|$3"); shift 3 ;;
    --cmd) { [ $# -ge 2 ] && case $2 in *::*) true ;; *) false ;; esac; } || { usage; exit 64; }; cmd_list+=("$2"); shift 2 ;;
    --http) { [ $# -ge 2 ] && ok_url "$2"; } || { usage; exit 64; }; http_list+=("$2"); shift 2 ;;
    --cli) { [ $# -ge 2 ] && ok_cli "$2"; } || { usage; exit 64; }; cli_list+=("$2"); shift 2 ;;
    --git-remote) GITREMOTE=1; shift ;;
    --profil) [ "${2:-}" = gh-harnais ] || { usage; exit 64; }; PROFIL=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 64 ;;
  esac
done

[ "$PROFIL" = gh-harnais ] && profil_gh_harnais
for c in ${cli_list[@]+"${cli_list[@]}"}; do
  if command -v "$c" >/dev/null 2>&1; then emit PASS "cli $c" "présent"; else emit FAIL "cli $c" "absent du PATH"; fi
done
for u in ${http_list[@]+"${http_list[@]}"}; do http_probe "$u"; done
if [ "$GITREMOTE" -eq 1 ]; then probe "git remote origin" FAIL env GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false git -c credential.helper= ls-remote --heads origin; fi
for h in ${ssh_list[@]+"${ssh_list[@]}"}; do
  probe "ssh $h" FAIL ssh -o BatchMode=yes -o "ConnectTimeout=$T" -- "$h" true
done
for h in ${tsh_list[@]+"${tsh_list[@]}"}; do
  before=$FAILS
  probe "tailscale ssh $h" FAIL tailscale ssh -- "$h" true
  if [ "$FAILS" -gt "$before" ] && command -v tailscale >/dev/null 2>&1; then
    emit WARN "tailscale status" "$(run_t tailscale status 2>&1 </dev/null | head -n3 | tr '\n\t' '  ' | sed -e 's#://[^ ]*@#://#g' | cut -c1-160)"
  fi
done
for e in ${env_list[@]+"${env_list[@]}"}; do env_probe "${e%%|*}" "${e#*|}"; done
for c in ${cmd_list[@]+"${cmd_list[@]}"}; do
  probe "${c%%::*}" FAIL bash -c "${c#*::}"
done

[ "$FAILS" -gt 63 ] && FAILS=63 # 64 = usage, et rc modulo 256
exit "$FAILS"
