#!/usr/bin/env bash
# Inventaire des secrets Hermes : NOMS de variables par .env, jamais les valeurs.
#
# Usage : inventory-env-secrets.sh [HERMES_HOME]
#   ./inventory-env-secrets.sh                       # $HERMES_HOME ou ~/.hermes
#   ./inventory-env-secrets.sh /opt/data
#
# Sortie : pour chaque .env (racine + profils), le nombre total de clés, le nombre
# de secrets, le mode fichier, puis la liste des NOMS de secrets.
# Aucune valeur n'est lue, affichée ou déplacée.
#
# A lancer AVANT d'ajouter, tourner ou supprimer un credential : chaque profil a
# son propre .env, donc un secret existe souvent en N exemplaires.
set -uo pipefail

HOME_DIR="${1:-${HERMES_HOME:-/opt/data}}"

# Noms de cles reellement assignees : ignore commentaires et lignes vides, ne
# garde que la partie avant le premier '='.
list_keys() {
  awk -F= '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ { gsub(/[[:space:]]/, "", $1); print $1 }
  ' "$1" | sort -u
}

is_secret() {
  # Formes credential reconnues par Hermes lui-meme (suffixes d'alias de profil).
  case "$1" in
    *_API_KEY|*_TOKEN|*_SECRET|*_KEY|*_PASSWORD) return 0 ;;
    *) return 1 ;;
  esac
}

found=0
for envf in "$HOME_DIR/.env" "$HOME_DIR"/profiles/*/.env; do
  [ -f "$envf" ] || continue
  found=$((found + 1))

  keys="$(list_keys "$envf")"
  total="$(printf '%s' "$keys" | grep -c . || true)"

  secrets=""
  while IFS= read -r k; do
    [ -n "$k" ] || continue
    if is_secret "$k"; then secrets="${secrets}${k}
"; fi
  done <<< "$keys"
  n_secrets="$(printf '%s' "$secrets" | grep -c . || true)"

  rel="${envf#"$HOME_DIR"/}"
  [ "$rel" = ".env" ] && rel=".env (profil default)"
  printf '\n%s  cles=%s  secrets=%s  mode=%s\n' \
    "$rel" "$total" "$n_secrets" "$(stat -c '%a %U:%G' "$envf")"
  printf '%s' "$secrets" | sed '/^$/d;s/^/    /'
done

if [ "$found" -eq 0 ]; then
  echo "Aucun .env trouve sous $HOME_DIR" >&2
  exit 1
fi

echo
echo "Doublons inter-fichiers (meme secret en plusieurs exemplaires) :"
for envf in "$HOME_DIR/.env" "$HOME_DIR"/profiles/*/.env; do
  [ -f "$envf" ] || continue
  list_keys "$envf" | while IFS= read -r k; do
    is_secret "$k" && printf '%s\n' "$k"
  done
done | sort | uniq -c | sort -rn | awk '$1 > 1 { printf "    %-28s x%s\n", $2, $1 }'
