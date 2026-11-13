---
name: hermes-gateway-lifecycle
description: "Use when debugging Hermes gateway lifecycle notices/hooks."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [hermes, gateway, hooks, notifications, s6, container, restart, lifecycle]
    related_skills: [multi-container-services, hermes-plugin-env-config, hermes-cron-jobs]
---

# Cycle de vie du gateway Hermes (déploiement conteneurisé)

Pour toute intervention sur le gateway **en marche** : notifications d'arrêt/démarrage, hooks
d'événements, chemins de redémarrage, supervision s6, et la vérification qui va avec.

## When to Use

- L'utilisateur signale qu'il reçoit un avis d'arrêt mais **jamais** d'avis de démarrage
  (« pourquoi tu ne me dis jamais que tu es de nouveau en ligne ? »).
- Il faut **ajouter ou déboguer un comportement au démarrage** du gateway : notification, action
  one-shot au boot, garde.
- Il faut **redémarrer** le gateway dans un conteneur supervisé par s6, ou vérifier qu'il tourne
  réellement.
- Un hook de gateway (`$HERMES_HOME/hooks/`) est chargé, ignoré, ou en erreur.

Ne couvre pas : configuration des plateformes de messagerie, plugins (`hermes-plugin-env-config`),
jobs cron (`hermes-cron-jobs`).

## Règle centrale : l'avis d'arrêt est inconditionnel, l'avis de démarrage non

- **Arrêt** — l'avis part à **chaque** arrêt, dès que les adaptateurs sont connectés (canal
  principal + sessions actives).
- **Démarrage** — l'avis de boot n'existe que pour un redémarrage **initié par Hermes**, parce
  qu'il est conditionné à un marqueur sur disque : `.restart_notify.json` (écrit uniquement par un
  `/restart` **en chat**) ou `.restart_pending.json` (écrit uniquement pour un redémarrage
  programmatique, c'est-à-dire sans source de chat).

Conséquence : un `SIGTERM` **externe** (docker stop/restart, `s6-svc`, reboot hôte, OOM) ne pose
aucun marqueur → le boot suivant sort en silence. L'utilisateur reçoit « je m'arrête » et jamais
« me revoici ». Ne pas chercher une option de configuration : il n'y en a pas ; il faut un hook.

## Diagnostic

```bash
L="$HERMES_HOME/logs/gateway.log"
grep -c "Sent shutdown notification"                        "$L"  # avis d'arrêt émis
grep -cE "Sent (home-channel startup|restart) notification" "$L"  # avis de démarrage émis
grep -E "Received SIGTERM|Exiting with code 1 .signal-initiated" "$L" | tail -20
```

- `signal=SIGTERM … parent_name=s6-supervise` suivi de
  `Exiting with code 1 (signal-initiated shutdown without restart request)` = arrêt **externe** :
  aucun avis de démarrage ne suivra.
- Zéro ligne `startup notification` **et** zéro ligne `Home-channel startup notification
  suppressed` = le chemin n'a jamais été atteint. Ne pas conclure à une suppression par config.

Détail des deux chemins, sémantique des marqueurs et ordre de la séquence de boot :
`references/gateway-notice-internals.md`.

## Étendre le gateway : Gateway Event Hooks

Point d'extension supporté pour réagir au cycle de vie, sans patcher l'arborescence d'installation.

```
$HERMES_HOME/hooks/<nom>/
  HOOK.yaml    # name, description, events: [gateway:startup, ...]
  handler.py   # async def handle(event_type: str, context: dict) -> None
```

- Poser les **deux** fichiers *est* l'opt-in (trusted-by-placement) : il n'y a pas de liste
  d'activation à tenir. Un `events` vide ou un manifeste invalide fait ignorer le dossier.
- `gateway:startup` est émis **une fois par boot**, après connexion des adaptateurs et **avant**
  l'envoi de l'avis natif de redémarrage — donc les marqueurs sont encore sur disque à cet instant,
  ce qui rend la garde anti-doublon fiable.
- Chargement visible dans le log : `[hooks] Loaded hook '<nom>' for events: [...]`. Une exception
  dans un handler est loggée (`[hooks] Error in handler for '<event>'`) et n'est jamais fatale.
- **Les handlers sont awaités séquentiellement sur la boucle d'événements.** Un `def handle` +
  `subprocess.run(...)` bloque la séquence de démarrage : écrire un `async def` et lancer le
  sous-processus via `asyncio.create_subprocess_exec` + `asyncio.wait_for(...)` borné.

## Notifier depuis un hook : `hermes send`

```bash
"$(dirname "$PYTHON")"/hermes send --to telegram --quiet "message"
```

- Fonctionne **sans gateway en marche** pour les plateformes à bot-token : appel REST direct avec
  les identifiants de `$HERMES_HOME/.env` + `config.yaml`. Ni gateway, ni LLM.
- Un nom de plateforme **nu** (`telegram`) ne vise que le **chat** du canal principal : `_home_chat_id()`
  (`tools/send_message_tool.py`) retourne `home.chat_id` et **jette `thread_id`**. Sur un canal principal
  organisé en topics, l'avis atterrit donc à la racine du chat, pas dans le topic que l'avis d'arrêt
  utilise (celui-ci part de l'origine de session, thread compris). **Toujours construire la cible
  explicite `platform:chat:thread`** quand le canal principal a un `thread_id`.
- Pour connaître ce `thread_id` depuis un hook : `gateway.config.load_gateway_config().get_home_channel(
  Platform("telegram"))` — même résolution que le reste du gateway (surcharges d'env incluses), aucun
  sous-processus. Repli : variables `TELEGRAM_HOME_CHANNEL` / `TELEGRAM_HOME_CHANNEL_THREAD_ID`, puis nom nus.
- Codes de sortie : `0` livré, `1` échec plateforme, `2` usage/config.
- Dans un hook, dériver le lanceur de l'interpréteur courant : `Path(sys.executable).parent / "hermes"`.
  Ne pas compter sur `hermes` dans le `PATH` d'une session conteneur.

## Redémarrer le gateway selon le chemin voulu

- **Initié par Hermes** (notice native) : `hermes gateway restart`. Sans source de chat, il écrit
  `.restart_pending.json` → l'avis natif partira et un hook de boot **doit se taire**.
- **Externe** (reproduit le motif réel des conteneurs) : `s6-svc -r /run/service/gateway-default`
  — SIGTERM, aucun marqueur → c'est le hook qui parle.
- Les outils s6 sont **hors `PATH`** : `/command/s6-svc`, `/command/s6-svstat`. Les répertoires de
  service sont sous `/run/service/gateway-<slot>`.
- Un seul gateway vit par conteneur : le slot racine `gateway-default` (`gateway run --replace`).
  Les slots de profils nommés sont enregistrés mais laissés à l'arrêt — ne pas en déduire plusieurs
  sources d'événements.
- Un redémarrage est une action de **production** : préparer la commande exacte et attendre le GO
  (elle interrompt la session en cours).

## Pièges

- **Garde anti-doublon obligatoire** avant tout avis de boot émis par un hook : si
  `.restart_notify.json` ou `.restart_pending.json` existe, l'avis natif couvre ce boot → se taire.
  Ajouter une fenêtre de temps courte (quelques dizaines de secondes) contre les boucles de respawn.
- **Ne pas se fier au seul verdict `hermes gateway status`** : sous supervision s6 il peut annoncer
  « not running » alors que le processus tourne. Confirmer avec `ps`/`pgrep` avant d'agir — relancer
  un gateway déjà vivant crée un conflit de polling sur le bot.
- **`/proc/<pid>/environ` ne reflète que l'environnement d'`exec`** : les variables chargées depuis
  `$HERMES_HOME/.env` après le démarrage (dont `TELEGRAM_HOME_CHANNEL[_THREAD_ID]`) n'y figurent
  jamais. Une absence dans `/proc` ne prouve pas qu'elles manquent au process.
- **Ne pas patcher l'installation pour ce besoin** : un correctif dans le code du gateway est perdu
  au rebuild d'image, alors qu'un hook sous `$HERMES_HOME` survit avec le volume.
- **Ne pas parser `config.yaml` à la main dans un hook** : le venv du gateway n'a pas `yaml`
  (`ModuleNotFoundError`), et l'erreur est avalée par un `except Exception` — le hook retombe alors
  silencieusement sur le nom de plateforme nu, donc hors topic. Utiliser le chargeur du gateway.
- **Aucun secret dans un handler** : passer par `hermes send`, qui lit `$HERMES_HOME/.env`. Ne jamais
  recopier un token dans un hook, un log ou un commit.

## Vérification : ce qui compte comme preuve

1. **Chargement réel** — exécuter le vrai `HookRegistry` sur le dossier et lire `loaded_hooks` :
   `scripts/probe_gateway_hook.py`, aucun redémarrage requis.
2. **Envoi réel** — déclencher l'événement et confirmer le code de sortie `0` de `hermes send`.
   C'est la preuve que la chaîne handler → CLI → plateforme fonctionne.
3. **Garde-fous** — tester explicitement les deux branches (marqueur présent / absent, fenêtre de
   temps) **sans** envoyer de message.
4. **Cycle réel** — seul un vrai boot prouve que Hermes émet l'événement. Tant qu'il n'a pas eu
   lieu, déclarer l'intégration **vérifiée en lecture** (appel présent dans la séquence de
   démarrage) et non prouvée. Ne jamais présenter un envoi manuel comme un test end-to-end.

Dernière étape de tout rapport : dire ce qui est PROUVÉ, ce qui est vérifié en lecture, et la
commande exacte qui reste à exécuter — L'utilisateur attend un correctif appliqué et testé, pas un plan.

## Références

- `references/gateway-notice-internals.md` — emplacements exacts, sémantique des marqueurs, ordre
  de la séquence de boot, signatures de log.
- `scripts/probe_gateway_hook.py` — sonde re-jouable : découverte d'un hook + déclenchement réel.
- `templates/gateway_startup_notify_handler.py` — handler de boot éprouvé (async borné, garde de
  marqueur natif, fenêtre anti-doublon, cible topic résolue par la config) : copier, adapter, poser
  à côté de son `HOOK.yaml`.
