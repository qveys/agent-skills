# Localite des surfaces Desktop selon le kind de connexion

Table de decision : quand l'app est branchee sur une gateway distante, quelle surface tourne
sur la machine de l'app et laquelle suit l'hote de la gateway.

| Surface | Local (app-managed) | Remote gateway (URL) / Cloud | SSH |
|---|---|---|---|
| Pane terminal `Ctrl+Backtick` | machine de l'app | **machine de l'app** | hote distant (`ssh -tt`) |
| Outil `terminal` de l'agent | hote gateway = meme machine | **hote gateway** | hote gateway (distant) |
| Explorateur de fichiers | filesystem local | filesystem **distant** | distant |
| `Open containing folder` | actif | **inactif** -> *Reveal in filetree* | inactif |
| Artefacts / images d'outils | lus en local | **recuperes via la gateway** | via la gateway |
| Preview navigateur (URL locale) | direct | reecrit via tunnel de la passerelle SSH, sinon URL brute | tunnel de la passerelle SSH |
| `read_terminal` / `desktop_ui` | pane local | actif mais lit le pane **local** | lit le pane distant |
| `hermes update` | backend connecte d'abord, puis toutes les passerelles eligibles (Cloud exclu) | idem | idem |
| Sessions / profils | profil de l'app | profils **decouverts sur** la gateway | idem |

## Points de code (branche amont, `apps/desktop/`)

- `electron/terminal-ipc.ts` — `hermes:terminal:start` : `nodePty.spawn(sshBinary(),
  buildInteractiveSshArgs(...))` si `sshTarget`, sinon `nodePty.spawn(shell local)`.
  `hermes:terminal:cwd` renvoie `null` quand la session porte un `sshScope`.
- `electron/main.ts` — `activeSshTerminalTarget(webContentsId)` : la seule source d'une cible SSH
  pour le pane. Refuse de retomber sur un hote SSH global quand la route de fenetre resout vers
  un backend non-SSH.
- `electron/ssh-connection.ts` — `buildInteractiveSshArgs()` : `-tt` + options du ControlMaster
  existant (donc aucune nouvelle auth), puis `exec "$SHELL" -l` dans le cwd demande. Commentaire
  de source : chemin interime en attente du websocket `/api/terminal` du dashboard.
- `electron/connection-apply.ts` — `resolveTerminalConnection()` : si la cible est `pending`,
  elle assure le backend puis relit ; toujours `pending` implique « Remote connection is not
  ready yet ».

## Signaux observables (sans lire le code)

1. Nom de shell remonte par le pane : `ssh` implique distant ; `zsh`/`bash` implique local.
2. `Open containing folder` grise sur la session courante implique session distante.
3. `hostname` / `pwd` tapes dans le pane : reponse immediate et sans ambiguite — premier reflexe
   quand l'utilisateur doute.
4. Barre d'etat : nom de la connexion enregistree, pas un port local.

## Ce qui n'est PAS une preuve

- « Le chat repond depuis le serveur » ne dit rien du pane : les deux chemins sont distincts.
- « L'explorateur de fichiers montre les fichiers du serveur » ne rend pas le pane distant.
- Un **Test** *Reachable* en kind URL prouve les jambes HTTP + WebSocket, pas la localite d'un
  pane.
