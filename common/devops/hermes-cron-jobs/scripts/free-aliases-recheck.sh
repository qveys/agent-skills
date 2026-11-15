#!/usr/bin/env bash
# free-aliases-recheck.sh — re-sonde les alias « *-free » (endpoint gratuit opencode.ai/inference)
# et retire de model_aliases ceux qui restent bloqués (429 quota gratuit, ou modèle indisponible).
#
# 200            -> alias sain, conservé
# 429            -> quota gratuit encore épuisé -> retiré
# 400/404        -> modèle inexistant -> retiré
# 5xx / réseau   -> transitoire -> conservé (on ne casse pas un alias sur une panne passagère)
#
# Sortie télégraphique sur stdout (cron no_agent). DRY=1 pour ne rien modifier.
set -uo pipefail

PY=/opt/hermes/.venv/bin/python
ROOT="${RECHECK_ROOT:-/opt/data}"
DRY="${DRY:-0}"

HOMES=("$ROOT")
for d in "$ROOT"/profiles/*/; do
  [ -f "$d/config.yaml" ] && HOMES+=("${d%/}")
done

# 1) Alias à sonder : base_url sur l'endpoint gratuit.
mapfile -t FREE_ALIASES < <("${PY_SYS:-python3}" - <<'PY'
import os, yaml
al = yaml.safe_load(open(os.path.join(os.environ.get('ROOT', '/opt/data'), 'config.yaml'))).get('model_aliases') or {}
for name, v in al.items():
    if 'opencode.ai/inference' in (v.get('base_url') or ''):
        print(f"{name} {v.get('model')} {v.get('base_url')}")
PY
)

if [ "${#FREE_ALIASES[@]}" -eq 0 ]; then
  echo "📡 ALIAS FREE · aucun alias gratuit restant à sonder"
  exit 0
fi

REMOVE=()
KEEP=()
DETAIL=()

for row in "${FREE_ALIASES[@]}"; do
  name="${row%% *}"; rest="${row#* }"
  model="${rest%% *}"; url="${rest#* }"
  code=$(curl -s --max-time 30 -o /tmp/freealias.json -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"dis OK\"}],\"max_tokens\":8}" \
    "$url/chat/completions" 2>/dev/null || echo 000)
  case "$code" in
    200) KEEP+=("$name"); DETAIL+=("· $name · ok") ;;
    429) REMOVE+=("$name"); DETAIL+=("· $name · 429 quota gratuit") ;;
    400|404) REMOVE+=("$name"); DETAIL+=("· $name · $code modèle indisponible") ;;
    *)   KEEP+=("$name"); DETAIL+=("· $name · $code transitoire, conservé") ;;
  esac
done

if [ "${#REMOVE[@]}" -gt 0 ] && [ "$DRY" != "1" ]; then
  for home in "${HOMES[@]}"; do
    # Les alias sont passés en argv (pas d'eval) : seule la config Hermes est touchée.
    HERMES_HOME="$home" "$PY" - "${REMOVE[@]}" <<'PY' >/dev/null 2>&1
import sys
from hermes_cli.config import unset_config_value
for name in sys.argv[1:]:
    try:
        unset_config_value("model_aliases." + name)
    except SystemExit:
        pass
PY
  done
fi

total=$(( ${#KEEP[@]} + ${#REMOVE[@]} ))
if [ "${#REMOVE[@]}" -eq 0 ]; then
  echo "📡 ALIAS FREE · $total sondés · tous conservés"
  printf '%s\n' "${DETAIL[@]}"
elif [ "$DRY" = "1" ]; then
  echo "📡 ALIAS FREE · $total sondés · ${#REMOVE[@]} à retirer (DRY, rien modifié)"
  printf '%s\n' "${DETAIL[@]}"
else
  echo "🧹 ALIAS FREE · $total sondés · ${#REMOVE[@]} retiré(s) de ${#HOMES[@]} config(s)"
  printf '%s\n' "${DETAIL[@]}"
fi
