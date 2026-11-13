# Diagnostic des jobs cron Hermes : exécution et livraison

## Lire `cronjob_manage action=list`

- `last_status` : `ok`, `error` (échec du script/agent), `delivery_failed` (le run a réussi, l'envoi a échoué).
- `last_error` : erreur d'exécution (stderr du script, code de sortie).
- `last_delivery_error` : erreur d'envoi, avec la cible entre parenthèses.
- `state` / `enabled` : `scheduled` = encore planifié ; `completed` + `enabled: false` = one-shot déjà tiré.
- `next_run_at` / `last_run_at` en UTC.

## Où sont les preuves

- `$HERMES_HOME/channel_directory.json` : chaque plateau/canal/enregistrement Telegram y apparaît avec son `thread_id` dans le champ `id` (format `<chat_id>:<thread_id>`). Utile pour retrouver le thread_id d'un topic/forun sans passer par un job de test.
- `$HERMES_HOME/logs/agent.log` et `$HERMES_HOME/logs/errors.log` : lignes `cron.scheduler: Job '<job_id>': ...`. Les deux fichiers portent la même ligne pour un même incident.
  - `grep -n "<job_id>" $HERMES_HOME/logs/agent.log` puis `grep -rn "<message d'erreur>" $HERMES_HOME/logs/` pour compter les occurrences réelles.
- `$HERMES_HOME/cron/` : `jobs.json` (définition des jobs), `executions.db` (historique avec `delivery_outcome`), `output/<job_id>/` (prompt incluant la sortie du wrapper et réponse finale). Comparer ces trois niveaux sur le même run : condition du script, décision de l'agent, résultat de livraison. Une sortie `[SILENT]` est `suppressed` et peut laisser `last_status: ok` et `last_delivery_error: null` ; ne pas la diagnostiquer comme panne Telegram.
- Verdict d'envoi réussi : `Job '<id>': delivered to <platform>:<chat_id> via live adapter thread=<t> message_id=<n>`.

## Deux voies de livraison

1. **Live adapter** : l'adapter plateforme tourne dans le gateway → envoi via la session déjà ouverte. C'est la voie normale ; aucune dépendance d'import à suspecter.
2. **Expéditeur direct** (repli) : quand l'adapter n'est pas joignable (restart du gateway, mode standalone), `tools/send_message_senders.py` importe la lib plateforme dans le process du venv Hermes.

Conséquence : un échec de livraison daté d'une fenêtre de restart (`logs/gateway-shutdown-diag.log`, `gateway-exit-diag.log`) ne décrit pas l'état courant. Vérifier un run postérieur avant de conclure à une panne.

## Vérifier une dépendance plateforme

- L'interpréteur de Hermes est `/opt/hermes/.venv/bin/python3` (root-owned) — pas le `python3` du PATH.
- `ls /opt/hermes/.venv/lib/python3*/site-packages/ | grep -i <lib>` puis `/opt/hermes/.venv/bin/python3 -c "import <lib>"`.
- Vérifier aussi la chaîne d'imports du chemin d'envoi, pas seulement la lib : `gateway.platforms.base`, `plugins.platforms.telegram.<module>`, `telegram.ext`.

## Faux diagnostic connu

`_send_telegram()` enveloppe tout son corps dans `except ImportError` et renvoie « python-telegram-bot not installed » pour n'importe quel `ImportError` du chemin d'envoi. Le message est donc trompeur : un paquet présent et importable peut coexister avec cette erreur. Ne rien installer avant d'avoir constaté l'absence réelle du paquet dans le venv.

## Validation directe de l'envoi (quand la vérification venv ne tranche pas)

Utiliser cette procédure seulement après avoir constaté le paquet présent dans le venv — l'objectif est de distinguer un faux-positif de la passerelle cron d'un vrai problème d'envoi. Pour un test discrétionnaire, un job `no_agent=true` temporaire qui écrit sur stdout reste préférable : pas de token à manipuler, pas de risque d'envoyer un message inutile.

1. Extraire le token depuis `$HERMES_HOME/.env` **en Python, pas avec `source`** : un subprocess cron non-interactif ne source pas le .env et n'a pas `TELEGRAM_BOT_TOKEN` dans son environnement.

   ```python
   import re
   env_path = os.path.join(os.environ["HERMES_HOME"], ".env")  # .env du profil qui porte le job
   token = None
   with open(env_path) as f:
       for line in f:
           m = re.match(r'^TELEGRAM_BOT_TOKEN=(.*)$', line.strip())
           if m:
               token = m.group(1).strip().strip('"').strip("'")
               break
   ```

2. Appeler `bot.send_message` directement depuis le venv Hermes (`/opt/hermes/.venv/bin/python`) avec le chat cible du job.

   ```python
   from telegram import Bot
   bot = Bot(token=token)
   bot.send_message(chat_id="<chat_id_du_job>", text="TEST LIVRAISON — <raisonCourte>")
   print("OK sent")
   ```

3. **Envoi passé** → le problème est dans la passerelle cron (faux-positif), pas dans l'infra Telegram. Relancer le job avec `action=run` pour confirmer ; le re-tiré est asynchrone, son résultat revient plus tard — ne pas attendre ni boucler.
4. **Envoi échoué** → vrai problème d'envoi (token invalide, réseau, bot désactivé). Traiter comme tel.

## Réparer un wrapper en échec (chemin codé en dur)

Quand plusieurs jobs échouent avec `cd: <chemin>: No such file or directory` (exit 1, pas 127) : montage déplacé, procédure complète dans la skill `cron-script-recovery` (variante « répertoire déplacé »). Rappel des trois pièges : corriger le `cd` du wrapper **et** le `workdir` de `jobs.json` (Python `json.load`/`json.dump`, pas `sed`) ; grepper tous les wrappers pour l'ancien chemin (les jobs hebdo/mensuels sont latents) ; rafraîchir `last_status` après vérification manuelle du wrapper.
