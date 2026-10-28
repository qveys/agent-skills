# Checklist de déploiement multi-conteneurs

## Avant de créer une carte (orchestrateur)

### 1. Identifier le conteneur proxy

Qui résout `sidecar.origin` → `127.0.0.1` ? Si la WebUI proxyfie, le service doit tourner dans le conteneur WebUI.

```bash
# Dans le conteneur cible, vérifier que le port est joignable
docker exec <conteneur-cible> curl -s http://127.0.0.1:PORT/health
```

Un test depuis l'hôte ou un autre conteneur peut donner un faux positif si le port est mappé différemment.

### 2. Vérifier le namespace PID

Un pidfile écrit dans un conteneur ne peut pas tuer un processus dans un autre conteneur (PID namespaces distincts).

```bash
# Dans le conteneur cible, trouver le PID propriétaire du port
PORT_HEX=$(printf '%04X' 8788)
inode=$(awk -v port="$PORT_HEX" '$4=="0A" && ($2 ~ /:'"$PORT_HEX"'$/){print $10}' /proc/net/tcp /proc/net/tcp6 | head -1)
if [ -n "$inode" ]; then
  for f in /proc/*/fd/*; do
    target=$(readlink "$f" 2>/dev/null || true)
    if [[ "$target" == *"socket:[$inode]"* ]]; then
      echo "PID propriétaire: $(basename $(dirname $(dirname "$f")))"
    fi
  done
fi
```

### 3. Script de démarrage idempotent

Le script doit :
- vérifier le pidfile existant (et rejeter les pidfiles de pid mort ou d'un autre conteneur),
- détecter un service déjà en écoute sur le port (en vérifiant que le process propriétaire est vivant),
- ne pas démarrer si un service valide est déjà présent.

### Template de script (bash)

```bash
#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIDECAR_PY="${SCRIPT_DIR}/sidecar.py"
SIDECAR_PIDFILE="${SCRIPT_DIR}/sidecar.pid"
LOG_FILE="${SCRIPT_DIR}/sidecar.log"
PORT="${OBSIDIAN_PANE_PORT:-8788}"
PORT_HEX=$(printf '%04X' "$PORT")

VERIFIER_PIDFILE() {
  local pidfile="$1"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      local cmdline pcmd
      cmdline="$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' || true)"
      pcmd="$(basename "$(readlink -f "/proc/$pid/exe" 2>/dev/null)" 2>/dev/null || true)"
      # Vérifier que c'est bien le service attendu dans ce conteneur
      if [[ "$cmdline" == *"monse_service.py"* ]] && \
         [[ "$pcmd" == *python* ]]; then
        return 0
      fi
    fi
  fi
  return 1
}

DÉJÀ_DEMARRÉ() {
  VERIFIER_PIDFILE "$SIDECAR_PIDFILE" && return 0
  # Optionnel : détecter via port si pidfile absent
  return 1
}

if DÉJÀ_DEMARRÉ; then
  echo "[sidecar] déjà démarré — rien à faire"
  exit 0
fi

rm -f "$SIDECAR_PIDFILE"
nohup python3 "$SIDECAR_PY" >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$SIDECAR_PIDFILE"

sleep 0.5
kill -0 "$NEW_PID" 2>/dev/null || {
  echo "[sidecar] échec du lancement" >&2
  tail -n 30 "$LOG_FILE" 2>/dev/null || true
  exit 1
}

for i in $(seq 1 20); do
  if curl -s -m 2 "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -qE '"status"\s*:\s*"ok"'; then
    echo "[sidecar] démarré (pid $NEW_PID)"
    exit 0
  fi
  sleep 1.0
done

echo "[sidecar] échec health check après 20s" >&2
tail -n 30 "$LOG_FILE" 2>/dev/null || true
exit 1
```

### Notes de débogage

- Pour voir pourquoi un script de lancement échoue, vérifier dans l'ordre : pidfile valide ? process vivant ? port occupé par un autre process ? port libre mais bind échoue (adresse déjà utilisée = process en écoute) ?
- Le log du sidecar (`sidecar.log`) contient les requêtes reçues — utile pour confirmer que le service répond bien.
- `grep -E '"status"\s*:\s*"ok"'` est le pattern tolérant pour les health check JSON.

## Voir aussi

- Skill `kanban-worker-dispatch` — pour diagnostiquer les workers qui échouent silencieusement.
- Skill `kanban-orchestration` — pour router du travail vers un worker.
