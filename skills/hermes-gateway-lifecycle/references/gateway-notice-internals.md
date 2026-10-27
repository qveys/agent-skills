# Notices de cycle de vie : cheminement exact

Complète la règle centrale du SKILL.md. Éviter de re-dériver ces points en lisant l'arborescence
`gateway/` à chaque fois.

## Les deux chemins d'avis

| | Arrêt | Démarrage |
|---|---|---|
| Déclencheur | tout arrêt, adaptateurs connectés | boot **avec** marqueur, ou hook de boot |
| Module | `gateway/run_shutdown.py` | `gateway/run_notifications.py` |
| Destinataire | sessions actives + canal principal | demandeur du `/restart`, ou canaux principaux |
| Condition | aucune | `.restart_notify.json` **ou** `.restart_pending.json` |
| Message | « Hermes is shutting down / restarting… » | « Gateway restarted successfully… » / « Gateway online — Hermes is back and ready. » |

## Qui écrit et qui efface les marqueurs

- `.restart_notify.json`
  - **écrit** par le chemin `/restart` en chat (le payload porte la plateforme, le chat et le fil à
    renotifier) ;
  - **lu puis effacé** par l'avis de démarrage du boot suivant.
- `.restart_pending.json`
  - **écrit** à la persistance de fin d'arrêt, uniquement quand un redémarrage a été demandé **et**
    qu'aucune source de chat n'est associée (redémarrage programmatique) ;
  - **lu puis effacé** quand tous les canaux principaux dus ont été atteints ; s'il reste des cibles
    injoignables (plateforme en panne, opt-out), le marqueur survit et est rejoué à la reconnexion.
- Un `SIGTERM` externe ne satisfait aucune des deux conditions d'écriture.
- Un marqueur `suppress_notification` (drain externe, mises à jour de flotte) supprime la diffusion
  **canal principal** de l'avis d'arrêt — mais pas l'avis de démarrage, et pas les pings de session.
  C'est le seul cas où le log dit explicitement `suppressed`.

## Ordre de la séquence de boot (pourquoi la garde anti-doublon est fiable)

1. démarrage du process, connexion des adaptateurs ;
2. services post-connexion → **émission de `gateway:startup`** (les handlers de hook s'exécutent ici) ;
3. envoi différé des avis de boot natifs (avis de redémarrage / rejeu des canaux principaux dus) ;
4. reprise des sessions interrompues, puis services de fond.

Un hook de boot s'exécute donc **avant** l'avis natif, marqueurs encore présents : tester leur
présence dans le handler est un filtre exact, pas une heuristique. L'ordre inverse n'existe pas.

## Supervision s6 d'un conteneur Hermes

- Un seul gateway par conteneur : slot racine `gateway-default`, commande `gateway run --replace`.
  Les slots de profils nommés (`gateway-<profil>`) sont enregistrés à l'arrêt : leur présence dans
  les processus de supervision ne signifie pas qu'ils tournent.
- Répertoires : `/run/service/gateway-<slot>/{run,finish,log,supervise}`. Le script `finish`
  traduit le code de sortie du `run` : `0` → arrêt définitif, `125` → arrêt définitif,
  tout le reste (dont `75`, code de redémarrage de service) → relance.
- Binaires hors `PATH` d'une session : `/command/s6-svc`, `/command/s6-svstat`.
- Conséquence : `hermes gateway restart` et un `SIGTERM` externe aboutissent tous deux à une relance
  par s6 — mais seul le premier écrit `.restart_pending.json`.

## Signatures de log utiles

| Ligne | Ce qu'elle prouve |
|---|---|
| `Sent shutdown notification to home channel <plateforme>:<chat>` | avis d'arrêt livré |
| `Shutdown notification suppressed for <plateforme>` | `gateway_restart_notification=false` sur cette plateforme |
| `Sent home-channel startup notification to <plateforme>:<chat>` | avis natif de démarrage livré |
| `Sent restart notification to <plateforme>:<chat>` | avis natif après `/restart` en chat |
| `Restart notification skipped: no live transport for <plateforme>` | marqueur présent mais adaptateur absent |
| `Received SIGTERM` + `Exiting with code 1 (signal-initiated shutdown…)` | arrêt externe, aucun marqueur posé |
| `[hooks] Loaded hook '<nom>' for events: [...]` | hook de gateway chargé |
| `[hooks] Error in handler for '<event>'` | handler en exception (non fatal) |

## Où vit la configuration de destination

`platforms.<plateforme>.home_channel` (`chat_id`, `thread_id`, `user_id`) définit le canal principal.
`hermes send --to <plateforme>` **nu** n'en retient que le `chat_id` : `_home_chat_id()`
(`tools/send_message_tool.py`) ne renvoie pas le `thread_id`. L'avis d'arrêt, lui, passe le fil
explicitement (origine de session). Sur un canal principal organisé en topics, les deux messages d'une
paire ne se suivent donc **que** si l'avis de boot vise la cible explicite
`<plateforme>:<chat>:<thread>` — jamais la plateforme nue.

Le `thread_id` se lit sans parser de YAML depuis le process du gateway :
`load_gateway_config().get_home_channel(Platform("<plateforme>"))`.
