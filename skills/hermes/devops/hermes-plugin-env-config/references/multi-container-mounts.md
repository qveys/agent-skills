# Plugins dashboard en déploiement Hermes multi-conteneurs

> **Note de portabilité.** Les chemins `<HOME_AGENT>` / `<HOME_WEBUI>` sont des placeholders : les anciens `/home/hermes` et `/home/hermeswebui` n'existent plus sur cette instance (vérifié par `ls`). Ici, un seul conteneur, `HERMES_HOME` racine = `/opt/data`, profils sous `/opt/data/profiles/<nom>`. Cette référence décrit un déploiement multi-conteneurs possible ; vérifier la topologie réelle (`docker inspect`, `cat $HERMES_HOME/gateway.pid`) avant d'appliquer.

Quand un plugin dashboard ne trouve pas son chemin (vault, dossier, fichier), la cause est souvent
un montage absent, pas une variable mal écrite. Ce fichier donne les montages usuels et les
commandes qui tranchent le diagnostic.

## Montages usuels (compose 3 conteneurs)

| Service | HERMES_HOME | Monte le workspace ? | Notes |
|---|---|---|---|
| `hermes-agent` (gateway) | `<HOME_AGENT>/.hermes` | non | volumes : `hermes-home`, `hermes-agent-src` |
| `hermes-dashboard` (`hermes dashboard`) | `<HOME_AGENT>/.hermes` | non | monte **seulement** `hermes-home` : c'est lui qui sert l'API des plugins |
| `hermes-webui` | `<HOME_WEBUI>/.hermes` | oui (`/workspace`) | outils déclenchés depuis la WebUI s'exécutent ici (limitation #681), pas dans le conteneur agent |

Les trois partagent le **même volume nommé** `hermes-home`, monté à des chemins différents :
éditer `<home-webui>/.hermes/.env` est visible par le gateway/dashboard sous
`<HOME_AGENT>/.hermes/.env`, et inversement. Mais les montages projet/workspace/vault sont
**par service** : un chemin présent dans un conteneur peut être totalement absent dans un autre.

## Commandes décisives

Identifier les montages réels du conteneur qui sert le dashboard :

```bash
docker inspect hermes-dashboard --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Vérifier que le chemin pointé par la variable existe bien **dans ce conteneur** :

```bash
docker exec hermes-dashboard ls -d /chemin/pointe/par/la/variable 2>&1
```

Repérer quel conteneur sert le dashboard (HERMES_HOME réel du process) :

```bash
cat "$HERMES_HOME/gateway.pid"          # {"pid": ..., "hermes_home": "<HOME_AGENT>/.hermes", ...}
ps aux | grep -E 'gateway run|dashboard' | grep -v grep
```

## Confirmer que deux chemins sont le même volume

Dans un déploiement multi-conteneurs, deux chemins absolus peuvent désigner le même volume.
Le confirmer par un marqueur plutôt que le supposer :

```bash
touch "$A/.probe_$(date +%s)" && ls "$B"/.probe_* 2>&1
```

## Règle

Choisir la valeur de la variable en fonction du conteneur qui **sert le plugin**, pas du
conteneur où l'agent travaille. Si le volume du vault n'est monté nulle part dans ce conteneur,
aucune valeur de `.env` ne compensera : il faut ajouter le montage au service dashboard
(ex. Dokploy : service -> Advanced -> File Mount, Save avant Deploy), puis redémarrer.
