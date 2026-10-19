---
name: tailscale-vps
description: Accéder aux VPS (vps-openclaw, vps-dokploy) depuis un agent — toujours `tailscale ssh <hôte>`, jamais `ssh` direct ; méthode cockpit wsh. À utiliser dès qu'il faut se connecter à un VPS, lancer `docker exec` sur les conteneurs d'agent des VPS, ou quand `ssh vps-*` échoue.
---

# Accès aux VPS via Tailscale SSH

## Règle

`tailscale ssh <hôte>`, **jamais** `ssh <hôte>` : depuis le shell d'un agent, le ssh direct échoue (`Permission denied (publickey)`, vérifié le 2026-10-19) car la clé SK (`id_ed25519_sk_mac`, FIDO2) est servie par l'agent 1Password, absent du shell. Un agent ne peut pas saisir la passphrase.

## Hôtes

Contenu vérifié le 2026-10-19 par `docker ps` ; les conteneurs changent, revérifier avant de s'y fier.

- **`vps-openclaw`** (srv1453980, tailnet `100.100.10.60`) : `paperclip`, `squid-proxy-squid-1`, `traefik-traefik-1`, `traefik-cloudflared-1`, `gitea-runner-vps-openclaw`. **Pas** de hermes ni opencode. Détails Paperclip : skill `paperclip-vps`.
- **`vps-dokploy`** (srv766743) : `hermes-agent`, `hermes-webui`, `hermes-voice-bridge`, `myopencode-server-6vnn4o-opencode-1`, plus Dokploy, omniroute, rustdesk, myhousekeeper, etc.
  - Dépôt brain : `/opt/workspace/brain` sur l'hôte = `/workspace/brain` dans les conteneurs (remote Gitea).
  - `sudo` refusé. Une crontab hôte existe (sync-client dans `hermes-agent`) : ne pas la supposer vide.

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

`hermes-agent` : `docker exec` y entre en root (uid 0, vérifié le 2026-10-19).
