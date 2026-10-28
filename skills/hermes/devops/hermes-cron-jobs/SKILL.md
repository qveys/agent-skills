---
name: hermes-cron-jobs
description: "Use when scheduling Hermes cron jobs."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [cron, hermes, scheduler, no_agent, scripts]
    related_skills: [cron-script-recovery, git-worktree-workflow]
---

# Jobs planifiés Hermes

## When to Use

- Créer, modifier, diagnostiquer ou livrer un job récurrent/one-shot du cron Hermes (`cronjob_manage`, `hermes cron`).
- Un job est `error` / `delivery_failed` / « ok mais rien reçu » ; livraison Telegram threadée ; watchdog de supervision ; format des messages livrés.
- Pour réparer un wrapper dont le chemin ou le binaire a disparu : `cron-script-recovery`.

Dans cette installation, un job récurrent se crée avec le cron Hermes, jamais via crontab, systemd, launchd ou n8n, sauf demande explicite d'un autre planificateur.

## Procedure

### 1. Inventaire

Charger `cronjob_manage` (outil différé : `tool_search` puis `tool_describe`, invoquer via `tool_call`). `action=list` avant toute création. Préférer `update` d'un job existant à un quasi-doublon.

Un outil local n'accepte qu'une invocation par `tool_call` — ne pas batcher plusieurs `cronjob_manage`.

### 2. Wrapper, pas commande inline

Le champ `script` est un **nom de fichier relatif à `$HERMES_HOME/scripts/`**. Hermes résout ce nom sous ce dossier. Une commande inline (`bash chemin --flags`) ou un chemin absolu est rejetée (`script does not exist: .../scripts/bash ...`).

1. Écrire le wrapper (bash, `set -euo pipefail`, `cd` vers le workdir réel, `exec` de la commande).
2. Le **copier** (pas de symlink : un lien est rejeté comme « traversal ») dans `$HERMES_HOME/scripts/<nom>.sh` et `chmod +x`.
3. Passer `script: "<nom>.sh"` uniquement.
4. Si le wrapper doit être versionné, le garder aussi dans le dépôt et **resynchroniser la copie Hermes à chaque changement** (le conteneur peut être recréé).

Pièges de recréation du conteneur et de relance des serveurs persistants : voir la section Pitfalls. Exemple complet d'un job de collecte/LLM (wrapper borné, recopie, relance du serveur web) : `references/veille-techno-pattern.md` ; cas « job `ok` mais plateforme vide » : `references/deploiement-stockage.md`.

### 3. Enregistrer le job

- Scripts déterministes, stdout livrable tel quel : `no_agent=true`. Le prompt est alors ignoré. Stdout vide = rien n'est livré.
- Raisonnement / filtrage / alerte conditionnelle : laisser l'agent (`no_agent=false`) et un prompt autoportant.
- `deliver` selon le canal voulu (`local` = fichier seulement).
- `workdir` = chemin absolu existant si les outils fichier doivent s'y ancrer.

### 4. Vérifier

Exécuter le wrapper à la main depuis un shell, puis `list`. Ne pas déclarer le job opérationnel tant que le wrapper n'a pas produit la sortie attendue.

**Wrapper long (collecte, LLM, traitement en lot)** : estimer la durée réelle AVANT de lancer le test — les fichiers de `cron/output/<job_id>/` sont horodatés à la FIN du run, l'écart avec l'heure du tick donne la durée typique (un cycle peut prendre 10-15 min). Lancer la vérification en `terminal background=true, notify=true` avec timeout généreux : un foreground 300 s qui expire masquerait le succès sous un faux timeout et ferait perdre 5 minutes de re-lance.

**Schéma de test de livraison : écrire sur stdout, pas appeler l'API soi-même.**

Un job `no_agent=true` livre le contenu de `stdout` verbatim via l'adaptateur Hermes — le script ne doit **jamais** faire de `curl` ou d'appel API direct vers Telegram (ou une autre plateforme). Un script qui appelle l'API directement échoue silencieusement car le process cron ne source pas `$HERMES_HOME/.env` et n'a pas `TELEGRAM_BOT_TOKEN` dans son environnement.

Bon schéma (celui de `cron-telegram-test.sh` existant) :

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "=========================================="
echo "TEST THREADED CRON — $(date)"
echo "=========================================="
echo ""
echo "Si tu lis ceci dans le thread : ✅ le routement marche."
```

Mauvais schéma (ne pas faire) :

```bash
# NE PAS FAIRE : l'envoi direct échoue car .env non source
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" ...
# ou
python3 -c "from telegram import Bot; Bot(token=os.environ['TELEGRAM_BOT_TOKEN']).send_message(...)  # token absent
```

La livraison threadée se teste de la même façon : créer un job temporaire `no_agent=true` avec `deliver: "telegram:<chat_id>:<thread_id>"`, écrire le message sur stdout, et vérifier dans le chat Telegram que le message arrive dans le topic attendu.

### 5. Diagnostic d'un job en erreur ou non livré

Recettes et chemins exacts : `references/diagnostic-livraison.md`. Cas « le job est `ok` mais la plateforme reste vide » (stores découplés : le cron écrit dans un fichier/volume que le service consommé ne lit pas) : `references/deploiement-stockage.md`.

1. `action=list` d'abord : lire `last_status`, `last_error` (échec du script/agent), `last_delivery_error` (échec de l'envoi), `state` et `enabled`. `state: completed` + `enabled: false` = one-shot déjà tiré, pas une panne. Pour un audit en lecture seule (sans charger l'outil), `hermes cron list` et `$HERMES_HOME/cron/jobs.json` exposent les mêmes champs par job (schedule, workdir, script, `last_run_at`, `last_status`, `next_run_at`).
2. Chercher l'ID du job dans `$HERMES_HOME/logs/agent.log` et `$HERMES_HOME/logs/errors.log` (lignes `cron.scheduler: Job '<id>': ...`). Compter les occurrences : une seule trace = incident isolé, pas une panne systémique.
3. Si le job est `ok` mais que l'utilisateur n'a rien reçu, comparer le résultat du wrapper, la réponse finale enregistrée dans `cron/output/<job_id>/`, `executions.db.delivery_outcome` et la trace `agent returned [SILENT]` ou `delivered to ... message_id=<n>` dans `agent.log`. `ok` signifie que l'exécution a réussi, pas qu'un message a été livré ; `[SILENT]` donne une suppression normale même si le wrapper concluait qu'un rappel était nécessaire. Ne pas re-tirer un vrai rappel pour tester : préférer les traces d'un run antérieur ou un job temporaire `no_agent`.
4. Si l'échec date d'une fenêtre de restart du gateway, ne pas le traiter comme un état courant : vérifier un run postérieur avant de conclure. Pour un rappel conditionnel, ne jamais assimiler un échec de lecture distante à une revue faite : consulter l'état local fiable du jour, puis, si aucune preuve de revue ou de refus n'existe, conserver le rappel plutôt que de rendre `[SILENT]`.
5. **Un `last_status: error` peut dater d'avant la correction** : comparer `last_run_at` au mtime des fichiers que le job contrôle. Si les entrées ont été modifiées après le run en échec, l'erreur enregistrée est de l'histoire, pas un état courant. Lancer le contrôle à la main, puis rafraîchir le statut par `action='run'` — anodin quand `deliver: local` (rien n'est envoyé à l'utilisateur). Le run manuel est asynchrone : son résultat revient plus tard, ne pas attendre ni boucler.

## Pitfalls

- **`hermes cron remove` nettoie aussi `cron/output/<job_id>/`** du job supprimé : le répertoire d'historique disparaît avec le job, on ne peut pas le déplacer à la main après coup. S'il doit survivre à la suppression (migration de profil, archivage), le copier avant le `remove`.
- **Recréation du conteneur = perte des scripts dans `$HERMES_HOME/scripts/`**. Le wrapper vit dans le dépôt mais le cron l'exécute depuis `$HERMES_HOME/scripts/`. Après recréation du conteneur, le dossier scripts est vidé. **Toujours recopier le wrapper après recréation** avant de recréer le job cron.
- **Changement de chemins de travail** : le conteneur peut être recréé avec des montages différents (ex: `/opt/data/workspace` → `/workspace` ; `ls` les deux avant de corriger — ils existent tous les deux sur cette instance). Le wrapper et le `workdir` du job dans `jobs.json` doivent être mis à jour. Vérifier `HERMES_HOME` et le chemin du repo après recréation.
- **Serveur web à relancer après modification du code** : le serveur uvicorn tourne en persistant (`background=true, persist_on_release=true`). Après modification du code Python, le serveur doit être relancé (kill + redémarrage) pour prendre en compte les changements. Ne pas oublier de vérifier que le port répond (HTTP 200).
- **Un `last_status: ok` n'exclut pas « l'utilisateur ne voit rien ».** Quand le job écrit dans un store (fichier SQLite, stdout) et qu'un service déployé à part (Docker/Dokploy, autre hôte) consomme un AUTRE store, le job réussit mais la plateforme reste vide. Un volume Docker nommé (`foo:/data`) est isolé du fichier hôte que le cron remplit — le job remplit un store que personne ne lit ; redémarrer le service ne change rien. Vérifier que le chemin de la base du wrapper (`workdir` / variable d'env de la base) et celui du service consommé pointent vers le même volume ; sinon corriger la cause (faire tourner le collecteur dans l'écosystème de déploiement, ou bind-mount), pas en relançant. Voir `references/deploiement-stockage.md`.
- **`hermes` n'est pas toujours sur le PATH de la session** (`command not found`) : dans ce déploiement le binaire est `/opt/hermes/.venv/bin/hermes`. Utiliser le chemin absolu ou `export PATH=/opt/hermes/.venv/bin:$PATH` — ne pas conclure qu'Hermes n'est pas installé.
- **Ne pas installer un paquet sur la foi d'un message de livraison « <lib> not installed ».** L'expéditeur direct (`tools/send_message_senders.py`) enveloppe tout son corps dans `except ImportError` et renvoie ce message pour n'importe quel `ImportError` du chemin d'envoi, imports internes compris : le message ne prouve pas que le paquet manque. Vérifier d'abord le paquet dans le venv Hermes.
- **Ne pas oublier `python-multipart` dans `pyproject.toml`** : requis par FastAPI pour les endpoints `Form(...)` (ex: `@app.post("/feedback")` avec `tid: int = Form(...)`). Sans lui, l'app crash au démarrage avec `RuntimeError: Form data requires "python-multipart" to be installed.`.
- **Ne pas supposer qu'un service reste joignable après recréation du conteneur** : les montages et réseaux peuvent changer, recopier les wrappers cron, relancer les services persistants.
- **Vérifier les dépendances dans `/opt/hermes/.venv`, pas avec le `python3` du PATH.** Le `python3` système n'est pas l'interpréteur de Hermes et n'a pas ses paquets ; ce venv appartient à root et serait écrasé à la mise à jour de l'image, donc constater qu'un paquet y est déjà présent avant d'envisager une installation.
- **Ne pas traiter un crontab vide comme « pas de planificateur ».** Le planificateur ici est Hermes ; `crontab -l` vide ne dit rien sur `cronjob_manage`.
- **Ne pas inventer un script cité seulement dans un README amont.** Vérifier que le fichier existe dans le pin local et sur le dépôt distant avant de le planifier ; une référence orpheline n'est pas un livrable.
- **Ne pas coder en dur un binaire hors PATH dans le wrapper versionné** si le binaire est local à une machine. Le wrapper repo reste portable ; la copie sous `$HERMES_HOME/scripts/` peut résoudre le binaire de *cette* machine. Voir `cron-script-recovery` si un tick sort en 127.
- **Ne pas compter un `.gitkeep` comme contenu métier** dans un job d'alerte d'inbox : le garder hors du compteur, sinon une inbox vide alerte en permanence.
- **Vérifier que le gateway Hermes est démarré avant de déclarer un job opérationnel.** `cronjob_manage action=list` retourne `gateway_running: false` → les jobs sont enregistrés mais ne tireront pas. Lancer `hermes gateway install` / `hermes gateway start` si la session doit exécuter des jobs. Ne pas confondre `state: scheduled` avec `state: running`.
- **Dans un job `no_agent`, seul stdout est livré.** Une ligne d'avertissement doit être écrite sur stdout et laisser le code de sortie à 0 : stderr n'apparaît que dans le rapport d'échec. Ajouter une ligne de seuil (marge, quota) au contrôle plutôt que de découvrir la limite par un échec.
- **Le warning « Scheduler is not ready: no gateway or no fresh profile heartbeat » n'est pas une panne à lui seul.** Des jobs avec `last_run_at` récent et `last_status: ok` prouvent que le planificateur tourne. Croiser le warning avec les exécutions réelles avant de conclure dans un sens ou dans l'autre.
- **Reformater l'affichage d'un watchdog sans toucher aux clés.** L'empreinte de dédup ne hache que les clés stables ; le format du message est purement cosmétique et peut changer librement, mais modifier le FORMAT d'une clé (`disque:/>=88%`) change l'empreinte et fait réémettre à tort (ou masquer une anomalie réelle). Ne retoucher que le second élément des tuples `(clé, message)`.
- **Tester un changement de format sur script dédupliqué sans toucher à l'état réel.** Le run réel sort à vide tant que l'état n'a pas changé, et les sondes réseau/psutil n'ont rien à faire dans un test de format. Importer le module, rediriger `STATE_FILE` vers un fichier tmp, neutraliser les fonctions de détection et injecter des trouvailles synthétiques, capturer stdout : les deux branches (vert / anomalies) se rendent alors sans supprimer l'état de prod ni attendre une vraie anomalie.
- **La détection de fuite de chemin/URL dans un test matche des patterns réels, pas des mots nus.** `"http" in sortie` matche le légitime `HTTP 503` d'une ligne de statut ; chercher `https?://`, une IP, un chemin filesystem — sinon le test crie au faux positif sur un status code valide.
- **Plusieurs jobs en erreur avec la même signature = cause partagée, pas N pannes indépendantes.** Un `cd: <chemin>: No such file or directory` sur plusieurs wrappers signale un montage déplacé : corriger la cause une fois pour toute la classe (procédure dans `cron-script-recovery`), pas job par job.
- **Le chemin codé en dur vit à deux endroits : le `cd` du wrapper et le `workdir` du job dans `jobs.json`.** Réparer les wrappers sans relire `jobs.json` laisse les jobs ancrés sur l'ancien chemin.
- **Rafraîchir `last_status` après une correction de wrapper.** L'erreur enregistrée survit au fix et fait ré-alerter un watchdog dont l'empreinte inclut la clé `job-error:` — repasser le statut à `ok` et vider `last_error` une fois le wrapper vérifié à la main depuis le shell.

### Watchdog « alerte au changement d'état » (job de supervision)

Pour un contrôle récurrent qui ne doit déranger l'utilisateur qu'aux transitions : le script compare une empreinte des trouvailles à celle du passage précédent et n'écrit sur stdout qu'en cas de différence. Stdout vide = tick silencieux, donc rien de livré — la dédup est entièrement dans le script, `no_agent=true` suffit.

- **L'empreinte porte sur des CLÉS stables, jamais sur les valeurs.** `load1=8.8` puis `load1=8.4` sont la même anomalie : hasher les mesures ré-alerte à chaque tick. Chaque trouvaille se modélise en `(clé, message)` — clé = nature + seuil franchi (`disque:/>88%`), message = les chiffres du moment. Pour un processus fugitif, la clé est la cmdline, pas le PID (il change à chaque respawn) ni le %CPU.
- **Le retour au vert est un changement d'état** : trouvailles vides après des trouvailles non vides → émettre une ligne « RAS » explicite, puis silence les ticks suivants.
- **Fichier d'état dans le cache du profil** (`profiles/<nom>/cache/<job>-state.json`). Le supprimer force une ré-alerte complète au tick suivant — c'est le levier pour re-tester la livraison sans attendre une vraie anomalie.
- **Cycle de validation en trois passages** avant de déclarer le watchdog opérationnel : (1) état supprimé → alerte émise, (2) immédiatement après → sortie vide, (3) état falsifié → comportement conforme. Valider aussi le retour au vert en neutralisant les contrôles.
- **Borner le tick** : un passage qui dure 20 s est acceptable à 30 min d'intervalle, un passage qui dure 5 min ne l'est pas. Timeouts sur chaque appel shell et chaque sonde HTTP ; `psutil` est disponible dans `/opt/hermes/.venv`.
- **Le premier passage d'un watchdog trouve toujours du vrai.** Un contrôle bien réglé remonte des erreurs préexistantes que personne ne regardait (jobs cron cassés, disque presque plein). Les rapporter comme découvertes hors périmètre, distinctes du livrable.

### Format des messages livrés (préférence utilisateur)

Tout ce qu'un job cron livre à l'utilisateur (digest de supervision, alerte, récap) suit un format **télégraphique**, pas des phrases :

- **Concis, sans grammaire** : pas de tournures (« Tous les contrôles sont revenus au vert »), des segments (`✅ VIGIE · tous contrôles au vert`).
- **Un emoji par type d'anomalie** en tête de ligne : fuite 🧨, charge ⚡, RAM 🧠, swap 🌀, disque 💽, inodes 📇, service 📡, job ❌, stockage 📦, contrôle KO 🛠️, gateway 🔌, cron muet ⏰.
- **Aucun chemin, URL, IP ou cmdline brut** : afficher le basename du programme (`ffmpeg`, pas `/usr/bin/ffmpeg`), le nom court du service (`vps`, pas l'URL tRPC complète). Le détail brut reste dans les logs, pas dans le message livré.
- **Bloc d'actions en pied, en bullets** : une ligne d'intro puis un bullet par action ordonnable — pas une ligne `·`-séparée :

  ```
  ⚡ Actions possibles (réponds dans ce topic) :
  · `tuer <pid>`
  · `redémarrer gateway`
  · `purger <dossier>`
  · `relancer <job>`
  · `relancer <service>`
  ```

  La vigie alerte, l'utilisateur décide : le bloc liste ce qu'il peut ordonner en réponse dans le topic.
- En-tête avec le compte quand plusieurs anomalies (`🚨 VIGIE · 4 anomalies`, singulier/pluriel géré) ; retour au vert = une ligne `✅` courte, pas de pavé.
- Modifier ce format = retoucher **uniquement** le second élément des tuples `(clé, message)`, jamais la clé (voir pitfall ci-dessous).

### Livraison Telegram threadée (mode sujets/forums)

Pour que les notifications cron arrivent en mode threadé (dans un sujet/topic Telegram plutôt que dans le fil principal), deux mécanismes existent — ne pas les confondre avec une livraison `reply_to` qui ne crée pas de thread durable.

**Option A — Cible explicite par job** (privilégiée quand un job doit aller vers un topic précis) :

```yaml
deliver: "telegram:123456789:<thread_id>"
```

`<thread_id>` est l'ID du message ancre du topic (le message qui a créé le sujet, ou un message du topic). Sans ce troisième champ, le message est livré dans le chat général, pas dans un thread.

**Option B — Variable d'environnement par défaut** (privilégiée quand tous les cron jobs doivent aller vers un même topic dédié) :

```yaml
# $HERMES_HOME/.env  (celui du profil qui porte le job)
TELEGRAM_CRON_THREAD_ID=<topic_message_id>
```

Cette variable route tous les cron jobs vers le topic nommé. Une cible explicite `deliver: "telegram:chat_id:thread_id"` prime toujours sur la variable.

**Pour trouver un thread_id :**

1. Lire le channel directory de Hermes (`$HERMES_HOME/channel_directory.json`) : chaque topic/forum Telegram enregistré y apparaît avec son `thread_id` dans le champ `id` (format `<chat_id>:<thread_id>`). Exemple : `"id": "123456789:17032"` → thread_id = 17032.
2. Si le topic n'est pas encore enregistré, envoyer un message test manuellement dans le topic souhaité via un job `no_agent` temporaire avec `deliver: "telegram:<chat_id>:<topic_id>"` (cf. règle de test ci-dessus) : le message arrive dans le topic et les logs de livraison (`gateway.log`) affichent `delivered to telegram:<chat> thread_id=<id> via live adapter`.
3. Une fois le thread_id identifié, le passer dans le champ `deliver` du job.

**Vérification de la livraison threadée :**

- Un job livré correctement vers un topic affiche dans les logs : `delivered to telegram:<chat> thread_id=<id> via live adapter`.
- Si le champ `thread_id` est absent dans la trace (`thread=-`), le message est livré en mode plume — vérifier que le job a bien le troisième champ dans `deliver`, ou que `TELEGRAM_CRON_THREAD_ID` est défini.

**Bug connu — thread_id perdu dans la livraison cron** (Hermes Agent v0.17.0 / v0.21.3) :

- Le champ `thread_id` est parfois perdu dans la passerelle de livraison cron : le cron passe `{"thread_id": ...}` au live adapter, mais l'adapter Telegram ne rejoint pas le topic et le message atterrit dans le chat général.
- Symptôme : la trace log affiche `thread_id=<id>` quand le job est planifié, mais à la livraison le message arrive hors topic.
- Contournement : tester la livraison threadée AVANT de confier un job critique au topic. Utiliser un job `no_agent=true` temporaire avec un script qui écrit sur stdout (pas d'appel API direct), avec `deliver: "telegram:<chat_id>:<thread_id>"` et vérifier manuellement que le message arrive dans le topic (voir règle de test ci-dessus).
- Si le bug est présent, privilégier l'Option B (variable d'environnement `TELEGRAM_CRON_THREAD_ID`) après l'avoir validée par un test manuel, ou reporter la livraison threadée pour les jobs sensibles.

### Profil secondaire (satellite) : livraison gatée par `profile_routes`

Un job cron d'un profil secondaire (qui ne possède pas la plateforme, ex. `platforms.telegram.enabled: false`) ne peut livrer QUE vers une cible couverte par une entrée exacte de `gateway.profile_routes` du profil propriétaire de la plateforme (le default). Hors route, le scheduler refuse en fail-closed avec « platform '<p>' not configured/enabled » — ce n'est PAS le faux-positif ImportError, c'est un refus légitime : il ne « finira pas par marcher ».

- Deux profils peuvent livrer dans le même topic, mais la route qui l'autorise fait aussi router les messages entrants de cette cible vers le profil secondaire (le plus spécifique gagne). Poser une route = accepter ce reroutage entrant.
- **La livraison sortante d'un satellite marche dès la route posée ; le routage ENTRANT, non.** La config du gateway est chargée à son démarrage (`self.config` figé au lancement), donc une route ajoutée ensuite ne s'applique aux messages reçus qu'après un `hermes gateway restart`. Un satellite peut donc alerter dans son topic immédiatement sans pouvoir encore y dialoguer — distinguer les deux dans le compte rendu, et soumettre le restart comme opération sensible (il interrompt les workers kanban en vol et les sessions plateforme) au lieu de le lancer.
- **Tracer la livraison dans le `logs/agent.log` du profil qui porte le job**, pas seulement dans le `gateway.log` du propriétaire de la plateforme : la ligne `cron.scheduler: Job '<id>': delivered to telegram:<chat> via live adapter thread=<id> message_id=<n>` n'apparaît que là pour un satellite. Une recherche menée sur le seul `gateway.log` conclut à tort « rien n'est parti ».
- Tester la voie d'un satellite sans spammer un vrai job : `hermes cron create "in 1m" --name test --deliver "telegram:<chat>:<thread>" --script <test>.sh --no-agent --repeat 1` (script sous `$HERMES_HOME/scripts/` du profil), attendre le tick, vérifier `delivered to ... via live adapter thread=<id> message_id=<n>` dans le `logs/agent.log` du profil, puis supprimer le job.
- CLI sur un autre profil : préfixer `HERMES_HOME=<dir du profil>` (`HERMES_PROFILE` est ignoré). Le « Scheduler is not ready » du CLI peut être un faux négatif : vérifier la fraîcheur de `cron/ticker_heartbeat` du profil avant de conclure.
- Skill en double dans un profil (« deux copies existent » → skippée à chaque run) : lever l'ambiguïté en renommant une copie (le scanner est récursif : renommer le dossier ne suffit pas, renommer le fichier oui). Vérifier ensuite avec `HERMES_HOME=<profil> hermes skills list`.

### Test de livraison Telegram

Lorsqu'un job planifié avec `deliver: "telegram:<chat_id>"` échoue à livrer avec « python-telegram-bot not installed » :

1. Constaté la présence réelle du paquet dans le venv Hermes (voir règle ci-dessus).
2. Si absente, installer dans le venv Hermes : `pip install python-telegram-bot` (le venv système à `/opt/hermes/.venv` ou l'environnement actif).
3. Tester avec un job temporaire `no_agent=true` qui écrit sur stdout, pas avec un script Python qui appelle l'API directement (voir règle de test ci-dessus).

**Ne pas relancer un job CRON juste pour tester la livraison** — créer un job `no_agent=true` temporaire avec le bon `deliver`, écrire un message sur stdout, et vérifier dans le chat que le message est bien arrivé. La sortie du job (stdout) est ce qui est livré, pas l'API call du script.

### Lever l'ambiguïté d'un faux-positif livraison Telegram

Le message `python-telegram-bot not installed` est un faux-positif fréquent : l'expéditeur direct enveloppe tout son corps dans `except ImportError` et renvoie ce message pour n'importe quel `ImportError` du chemin d'envoi (imports internes compris). Un paquet présent et importable peut coexister avec cette erreur. Quand la vérification venv ne tranche pas, valider l'envoi direct avant de conclure.

Procédure de validation directe (extraction du token depuis `.env` en Python, appel `bot.send_message` depuis le venv Hermes, cas d'usage / non-usage) : `references/diagnostic-livraison.md`.

### Pipe vide et `set -euo pipefail`

Un script avec `set -euo pipefail` sort avec exit 1 si un pipe produit une sortie vide sur le côté gauche. Si le script fait `find ... | while read; do ...; done | sort | tail`, ajouter `|| true` à la fin du pipe pour éviter l'arrêt prématuré :

```bash
find ... | while read; do ...; done | sort | tail -14 || true
```

Ou remplacer par une boucle `for` explicite. Toujours vérifier le exit code après chaque pipe.

