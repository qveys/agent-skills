---
name: hermes-desktop-gateway-connections
description: "Use when wiring Hermes Desktop to a remote gateway."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [hermes, desktop, gateway, remote-backend, ssh, terminal, pane-locality]
    related_skills: [multi-container-services, inspecting-hermes-desktop-dom, hermes-gateway-lifecycle]
---

# Connexions gateway de Hermes Desktop

Repondre a « ou tourne vraiment ca ? » quand l'app Desktop est branchee sur une gateway
distante, et faire en sorte que le pane terminal montre le shell du distant.

## When to Use

- L'utilisateur veut utiliser le terminal integre (`Ctrl+Backtick`) alors qu'il est connecte a
  une gateway distante et s'attend a voir le shell du distant.
- Une surface de l'app (terminal, fichiers, preview, artefacts, mise a jour) se comporte comme
  si elle etait locale alors que la session est distante, ou l'inverse.
- Il faut choisir le **kind** de connexion (Local / Remote gateway / SSH / Hermes Cloud) dans
  **Settings -> Gateways**.

## Regle centrale : le pane terminal est local, sauf connexion SSH

Le pane terminal est un PTY **local** : `node-pty` spawné dans le process Electron principal
(`apps/desktop/electron/terminal-ipc.ts`). Deux chemins de spawn seulement :

- **shell local** quand la route de fenetre ne porte pas de transport SSH ;
- **`ssh -tt` interactif** quand la connexion active du registre est de kind **SSH**
  (`activeSshTerminalTarget()` dans `apps/desktop/electron/main.ts` ne renvoie une cible que
  pour une route de fenetre adossee a une connexion SSH du registre).

Consequence : en mode **Remote gateway (URL)** ou **Hermes Cloud**, aucun reglage ne rend le
pane distant. Il faut enregistrer la machine en **SSH**.

## Deux terminaux : ne jamais les confondre

| Terminal | Ou il tourne | Portee |
|---|---|---|
| Pane integre (`Ctrl+Backtick`) | machine qui fait tourner l'app | sauf connexion SSH -> hote distant |
| Outil `terminal` de l'agent | **hote de la gateway** | toujours, quel que soit le kind |

Le second suit `terminal.backend` (local/docker/ssh/...) evalue sur l'hote de la gateway. Donc
« faire executer la commande par l'agent dans le chat » reste le contournement valide quand la
connexion est une URL et qu'aucun SSH n'est disponible.

## Procedure : shell distant dans le pane

1. **Settings -> Gateways -> Registered gateways -> Add connection -> SSH**.
2. Hote composite `user@host:22` (user et port optionnels). La cle SSH locale est utilisee ;
   l'app ouvre un ControlMaster, demarre le dashboard distant par le tunnel et adopte un token.
3. **Hermes path** (optionnel, ex. `/opt/hermes/bin/hermes`) : a remplir seulement si **Test**
   repond « Hermes is not installed on the remote host » — le shell non-interactif du distant
   n'a pas `hermes` dans son `PATH`. Laisser vide = auto-detection.
4. **Test** jusqu'a *Reachable* : la sonde couvre les **deux** jambes (HTTP **et** WebSocket).
   Un passage HTTP seul n'est pas une preuve.
5. Selectionner cette connexion dans la sidebar **Sessions**, puis `Ctrl+Backtick` : le pane
   ouvre un `ssh -tt` reutilisant le socket ControlMaster (aucune nouvelle poignee de main
   d'auth), avec `exec "$SHELL" -l` dans le cwd de la session.

Cote distant, `hermes serve --host 0.0.0.0 --port 9119` doit tourner (systemd/tmux). Un bind
non-loopback engage la porte d'auth : OAuth (Nous Portal) pour tout ce qui est expose au-dela
de sa machine, couple user/mot de passe uniquement sur LAN/VPN de confiance. Une gateway de
messagerie est un process distinct du backend.

## Comment prouver ou une surface tourne

Quand la doc ne tranche pas, ne pas inferer depuis les `.tsx` :

1. **Doc complete en local, pas l'extrait web.** `curl -s
   https://hermes-agent.nousresearch.com/docs/llms-full.txt` puis chercher par motif dedans.
   `web_extract` tronque les pages longues en head+tail et fait manquer le passage decisif ; le
   fichier complet (~5 Mo) se parcourt par recherche de motif.
2. **Source du shell Electron.** Lire `apps/desktop/electron/terminal-ipc.ts`,
   `main.ts` (`activeSshTerminalTarget`) et `ssh-connection.ts` (`buildInteractiveSshArgs`).
   Les installs packagées ne embarquent pas toujours `apps/desktop` : lire la branche amont via
   `raw.githubusercontent.com`.
3. **Signaux observables dans l'app** — preuve sans code : le nom de shell remonte par le pane
   est `ssh` (et non `zsh`/`bash`) ; `Open containing folder` est inactif sur une session
   distante (il faut *Reveal in filetree*) ; `hermes:terminal:cwd` renvoie `null` pour un pane
   adosse a un tunnel.

## Pieges

- **Ne pas affirmer qu'un pane suit une connexion URL.** Aucun reglage ne le fait aujourd'hui :
  le chemin distant du pane est l'`ssh -tt`, documenté dans la source comme interime en attente
  du websocket `/api/terminal` du dashboard. Ne pas presenter ce websocket comme livre.
- **Une surcharge de profil gagne sur une connexion SSH globale.** Un token/OAuth par profil qui
  resout vers un backend non-SSH doit empecher le pane de retomber sur l'hote SSH global : ne
  jamais renvoyer « n'importe quel » etat SSH en cache.
- **Unicite et dedoublonnage du registre.** Une seule entree *local* (geree par l'app, non
  supprimable) ; *remote* et *cloud* dedupliques sur l'URL normalisee (trim, slash final retire,
  minuscules, tous kinds confondus) ; *SSH* sur `user@host:port` + profil distant.
- **Chaque connexion exige un nom d'appareil unique**, insensible a la casse. Les profils de meme
  nom sur plusieurs gateways s'affichent en `@profile-appareil`.
- **Un `Ctrl+W` au-dessus d'un pane interactif** garde sa signification shell (effacement de
  mot), il ne ferme pas l'onglet de session.
- **Bind non-loopback + garde d'origine.** Hors `127.0.0.1`, la porte d'auth s'engage et le
  serveur refuse tout en-tete `Host` different de l'adresse liee (anti DNS-rebinding) : lier au
  nom ou a l'adresse que le client utilise reellement.
- **Le pane SSH meurt avec son tunnel.** Les panes dont le PTY voyageait sur le tunnel sont
  disposes a la deconnexion ; ce n'est pas un bug de rendu.

## Verification

- Le kind **SSH** est le seul a prouver : shell du pane = `ssh`, prompt distant, cwd aligne sur
  la session.
- En kind URL/Cloud, annoncer explicitement que le pane est local et que seul le terminal de
  l'agent est distant — l'utilisateur doit savoir lequel des deux il utilise avant de taper une
  commande.
- Toute affirmation « le pane X est distant » doit citer le point de code ou le signal
  observable ; sinon la marquer SUPPOSE.

## References

- `references/desktop-surface-locality.md` — table des surfaces Desktop (locale vs distante),
  points de code correspondants, signaux observables.
