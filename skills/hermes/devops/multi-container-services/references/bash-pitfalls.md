# Pièges Bash récurrents en scripts de déploiement headless

Des patterns Bash faciles à mal écrire, avec la mécanique sous-jacente et la correction.

## Extraction de PID depuis /proc/PID/fd/N

**Problème** : extraire le PID depuis un chemin de fd socket.

```bash
# MAUVAIS — retourne "fd", pas le PID
pid=$(basename "$(dirname "$fdlink")")
# fdlink = /proc/329933/fd/3
# dirname -> /proc/329933/fd
# basename -> "fd"
```

```bash
# CORRECT — extraction par paramétrage de chaîne
pid_candidate="${fdlink#/proc/}"   # "329933/fd/3"
pid_candidate="${pid_candidate%%/*}" # "329933"
```

**Pourquoi** : `basename "$(dirname "$var")"` est sujet à une ambiguïté d'évaluation de sous-shell dans certains interprètes, et `dirname`/`basename` sur le chemin complet ne donnent pas le PID au milieu de la hiérarchie. Le paramétrage de chaîne est déterministe.

## Health check JSON avec espaces

**Problème** : matcher du JSON compact vs formaté.

```bash
# MAUVAIS — échoue sur {"status": "ok", ...} (espace après :)
curl -s http://127.0.0.1:8788/health | grep -q '"status":"ok"'
```

```bash
# CORRECT — regex tolerant
curl -s http://127.0.0.1:8788/health | grep -qE '"status"\s*:\s*"ok"'
```

**Pourquoi** : le format de sortie peut varier (compact vs jolis espaces) sans que le service change. Un pattern littéral rigide rompt le health check.

## Vérification de pidfile

**Problème** : un pidfile peut contenir un PID mort (crash non nettoyé).

```bash
# MAUVAIS — considère le pidfile comme valide sans vérifier le process
if [[ -f "$pidfile" ]]; then
  echo "sidecar déjà démarré"
  exit 0
fi
```

```bash
# CORRECT — vérifier que le PID est vivant ET correspond au bon service
if [[ -f "$pidfile" ]]; then
  pid=$(cat "$pidfile")
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    cmdline=$(cat "/proc/$pid/cmdline" | tr '\0' ' ')
    if [[ "$cmdline" == *"sidecar.py"* ]]; then
      echo "sidecar déjà démarré (pid $pid)"
      exit 0
    fi
  fi
fi
```

**Pourquoi** : un crash non nettoyé laisse un pidfile avec un PID réassigné au noyau. Tuer ce PID tue un process innocent.

## Voir aussi

- Skill `multi-container-services` — déploiement de services loopback.
- Skill `kanban-worker-dispatch` — diagnostic de workers.
