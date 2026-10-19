---
name: tailscale-vps
description: Accéder aux VPS (vps-openclaw, vps-dokploy) depuis un agent — toujours `tailscale ssh <hôte>`, jamais `ssh` direct ; méthode cockpit wsh. À utiliser dès qu'il faut se connecter à un VPS, lancer `docker exec` sur les conteneurs d'agent des VPS, ou quand `ssh vps-*` échoue.
---

# Accès aux VPS via Tailscale SSH

## Règle

`tailscale ssh <hôte>`, **jamais** `ssh <hôte>` : le ssh direct n'est pas la voie prévue. Une passphrase FIDO2 demandée en ssh direct : non vérifié.

## Hôtes

Listes de conteneurs : voir `docker ps` sur l'hôte (non vérifié ici, elles changent).

- **`vps-openclaw`** : conteneurs : voir `docker ps`.
- **`vps-dokploy`** : conteneurs : voir `docker ps`.

## Méthode cockpit (skill `wsh-cockpit`)

```bash
L=<base du skill wsh-cockpit>/scripts/wsh-live.sh
$L spawn <nom> --situate                # --situate obligatoire après spawn
$L remote-init --pre <hôte> <session>   # AVANT le hop (recommandé par wsh-cockpit)
$L send 'tailscale ssh <hôte>' <session>
$L remote-init <session> <hôte>         # après le hop
$L step-run <id> '<label>' '<cmd> 2>&1' <session>
$L output <session>
$L send 'exit' <session>
$L wait-done <session>               # jamais de send avant le footer exit
$L local-init <session>                 # au retour en local
```

Pièges :
- Non vérifié pour ces hôtes : `wsh conn status` et `wsh-rexec.sh` ; utiliser le mode `live` décrit ci-dessus.
- Les règles de wsh-cockpit (bannières, `wait-done`, `2>&1`) restent valables.

## Conteneurs

Pour descendre dans un conteneur (`docker exec` / `docker compose exec`) depuis le pane, suivre la section « Descendre d'une couche — conteneur » du skill `wsh-cockpit` (`remote-init --container`, résolution du nom du conteneur).
