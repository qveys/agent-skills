# Topologie Hermes à deux conteneurs et contrat des plugins

> **Note de portabilité.** Les chemins `<HOME_AGENT>` / `<HOME_WEBUI>` sont des placeholders : les anciens `/home/hermes` et `/home/hermeswebui` n'existent plus sur cette instance (vérifié par `ls`). Ici, un seul conteneur, `HERMES_HOME` racine = `/opt/data`, profils sous `/opt/data/profiles/<nom>`. Cette référence décrit un déploiement multi-conteneurs possible ; vérifier la topologie réelle (`docker inspect`, `cat $HERMES_HOME/gateway.pid`) avant d'appliquer.

Charger ceci quand un plugin dashboard ne se comporte pas comme prévu : la cause est souvent le conteneur, pas le plugin.

## Topologie typique

| | conteneur agent | conteneur WebUI |
|---|---|---|
| Rôle | gateway + dashboard officiel | interface web |
| Home Hermes | `<HOME_AGENT>/.hermes` | `<HOME_WEBUI>/.hermes` |
| Ports | API agent (ex. 8642), dashboard (ex. 9119) | port de la WebUI (ex. 8787) |
| Sert le backend des plugins | **oui** | **non** |

Le volume `hermes-home` est **partagé** mais monté à des chemins différents dans chaque conteneur. Le `.env` est donc commun, mais un chemin absolu qu'il contient n'est valide que dans un conteneur. `docker-compose` expose ces correspondances ; les vérifier plutôt que déduire.

## Contrat des plugins : dashboard officiel vs WebUI

- **Dashboard officiel** : fournit les globales `window.__HERMES_PLUGINS__` et `window.__HERMES_PLUGIN_SDK__`, monte les backends déclarés dans `dashboard/manifest.json` sous `/api/plugins/<nom>/`, et charge l'entrée `plugin.js` du manifest.
- **WebUI** : ne sert que des assets statiques. Le loader exige `dist/index.js` (entrée bâtie), et son module de plugins indique explicitement que le backend d'un plugin n'est pas utilisé. Aucune globale SDK n'y est définie : un `plugin.js` qui commence par `if (!sdk) return;` ne rend rien.

Symptômes croisés : un plugin sans répertoire `dist/` (entrée `plugin.js`) s'affiche dans le dashboard officiel mais reste vide dans la WebUI. Comparer la structure du plugin aux autres plugins qui fonctionnent sur la même surface.

### Pourquoi « porter un plugin » vers la WebUI ne peut pas marcher

Une page de plugin WebUI est servie avec `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups` — **sans `allow-same-origin`**. Le document s'exécute donc en origine opaque : son `fetch('/api/…')` part sans cookie et reçoit `401` sur toute l'API. Ajouter un `dist/index.js` n'y change rien, et la WebUI ne monte de toute façon pas le backend déclaré par le manifeste.

Ne pas promettre ce portage. Vérifier dans cet ordre avant de conclure :

1. `grep -rn "__HERMES_PLUGIN_SDK__\|__HERMES_PLUGINS__" <app>/static/` → absentes côté WebUI.
2. `grep -n "not used in WebUI MVP" <app>/api/plugins.py` → backend de plugin explicitement non utilisé.
3. `grep -n "sandbox allow-scripts" <app>/api/routes.py` → pages de plugin sandboxées (le point bloquant).
4. `grep -n "dashboard_plugins" "$HERMES_HOME"/webui/settings.json` → clé d'activation côté WebUI (`{}` = plugin désactivé).

Un onglet de plugin n'est servi que si le plugin fournit `dist/index.html`, `static/index.html` ou `dist/index.js` — l'entrée `plugin.js` seule ne suffit pas côté WebUI.

Voie viable pour une vue native **dans** la WebUI : une **extension WebUI** (manifeste avec `scripts` injectés dans le SPA, donc même origine, et `sidecar` optionnel proxifié via `/api/extensions/<id>/sidecar/*`), pas un plugin dashboard. Ses fichiers vivent sous le dossier d'état de la WebUI, pas sous `$HERMES_HOME/plugins/`.

## Sondes de vérification

Identifier le propriétaire réel du log (donc le conteneur qui monte les routes) :

```bash
grep -rn "Mounted plugin API routes" "$HERMES_HOME/logs/" | tail
```

Interroger chaque conteneur et port candidat :

```bash
for port in 8642 9119 8787; do
  printf '%s -> ' "$port"
  curl -s -m 4 -o /dev/null -w "%{http_code}\n" "http://<hote>:$port/api/plugins/<nom>/vaults"
done
```

### Piège : 401 ne prouve pas qu'une route existe

Sur ces serveurs, une barrière d'authentification globale renvoie `401` pour **toute** route `/api/*`, existante ou non, et redirige (ex. `302`) les chemins hors `/api/`. Tester un chemin volontairement inexistant avant d'interpréter un code :

```bash
for p in /api/plugins/<nom>/vaults /api/plugins/<nom>/nonsense-xyz; do
  printf '%s  %s\n' "$(curl -s -m 4 -o /dev/null -w '%{http_code}' "http://<hote>:<port>$p")" "$p"
done
```

Mêmes codes sur les deux chemins = barrière d'auth, pas une preuve de présence de route. Un `404` sur un port précis reste, lui, informatif.

## Vérifier un chemin côté consommateur

Le chemin du vault (ou de toute ressource) doit exister dans le conteneur qui importe le module :

```bash
docker exec <conteneur-agent> ls -d /brain/repo/Second-Cerveau/.obsidian
```

Si le même dépôt est visible sous un autre point de montage dans le conteneur de travail, ne pas « corriger » la valeur avant d'avoir tranché qui la consomme.

## Contrat d'une extension WebUI (la seule voie viable)

Charger cette section quand il faut vraiment une vue native *dans* la WebUI. Une extension, contrairement à une page de plugin, est injectée dans le SPA : même origine, cookies présents, donc `/api/*` utilisable.

### Emplacement et manifeste

Racine : `HERMES_WEBUI_EXTENSION_DIR` si défini, sinon `STATE_DIR/extensions` (le dossier d'état de la WebUI, à côté de `settings.json`). Le manifeste accepte aussi une forme `extensions: [ {...} ]` (plusieurs entrées).

```json
{
  "id": "mon-ext",
  "name": "Mon panneau",
  "enabled": true,
  "scripts": ["plugin.js"],
  "stylesheets": ["plugin.css"],
  "sidecar": {
    "type": "loopback",
    "origin": "http://127.0.0.1:8791",
    "health_path": "/health",
    "proxy_auth": "legacy"
  },
  "permissions": {},
  "settings_schema": {}
}
```

Les assets sont résolus avec `asset_base = <id>`. Clés reconnues : `id`, `name`, `description`, `version`, `enabled`, `scripts`, `stylesheets`, `sidecar`, `permissions`, `settings_schema`.

### Sidecar : validation stricte, rejet silencieux

| Champ | Valeurs | Comportement si invalide |
|---|---|---|
| `type` | `loopback` uniquement | sidecar **rejeté** (`sidecar_type_unsupported`) |
| `origin` | origine loopback valide | rejeté (`sidecar_origin_rejected`) |
| `health_path` | défaut `/health` | une valeur invalide **rejette** le sidecar (`sidecar_health_path_rejected`) au lieu de retomber sur le défaut |
| `proxy_auth` | absent = `legacy` ; `token-v1` = jeton par extension injecté par le cœur, à valider côté sidecar | toute autre valeur rejette (`sidecar_proxy_auth_unsupported`) |

Vérifier ces noms de diagnostics avant de conclure qu'un sidecar est sain : un rejet ne casse pas la page, il prive silencieusement le panneau de son backend.

### Proxy et consentement

- Route : `GET|POST /api/extensions/<id>/sidecar/<chemin>`. Le chemin doit commencer par `/`, sans `?`, `#`, espace, ni segment `.`/`..`.
- Le proxy exige un **consentement utilisateur** enregistré côté WebUI. C'est une action de l'utilisateur dans l'interface, jamais acquise d'avance : la documenter, ne pas la supposer.

### La WebUI ne démarre pas le sidecar

Aucune clé `command`/`spawn` au manifeste : la WebUI ne fait que **sonder** (health) et **proxifier**. Livrer le processus sidecar **et** son mode de démarrage durable, documenté (y compris la relance après redémarrage du conteneur). Un sidecar qui ne tourne pas = panneau vide alors que toute la configuration est correcte.

### Ordre de vérification d'une extension

1. Manifeste listé sans diagnostic de rejet de sidecar.
2. `curl` sur `/health` du sidecar → 200.
3. Appel proxifié après consentement → liste et lecture.
4. Panneau lisible **quand le sidecar est arrêté** (message d'erreur clair, pas un écran vide muet).

## Démarrer durablement un sidecar d'extension WebUI

- **Le sidecar tourne dans le conteneur de la WebUI**, pas dans le conteneur agent : la WebUI proxifie `sidecar.origin` (loopback `127.0.0.1`) depuis *son* conteneur. Un sidecar démarré côté agent est injoignable.
- **Pidfile propre au conteneur.** Un pidfile écrit dans un conteneur ne permet pas de tuer un processus d'un autre (espaces de noms PID distincts). Un script de démarrage doit vérifier que le pid correspond bien à un processus exécutant le sidecar *dans ce conteneur*, sinon ignorer le pidfile.
- **Démarrage idempotent** : ne lancer que si aucun sidecar ne tourne. Il ne redémarre pas après un crash ; la supervision (cron `@reboot`, systemd, supervisord, s6) est à fournir côté OS du conteneur — la WebUI ne supervise pas les extensions.
- **Observabilité** : `sidecar.log` dans le répertoire de l'extension ; `curl -s http://127.0.0.1:<port>/health` (et `/status`) depuis le conteneur WebUI.
- Le conteneur WebUI peut tourner sous un uid non root : installer les dépendances Python en conséquence (`pip install --user`).
- Manifeste d'extension : `{"id": "...", "enabled": true, "scripts": ["plugin.js"], "stylesheets": ["plugin.css"], "sidecar": {"type": "loopback", "origin": "http://127.0.0.1:<port>", "health_path": "/health", "proxy_auth": "legacy"}}`.
