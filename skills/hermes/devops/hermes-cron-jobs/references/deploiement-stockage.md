# Job cron « ok » mais plateforme vide : stores découplés

Quand un job tourne (`last_status: ok`, `last_run_at` récent) mais l'utilisateur ne voit aucune donnée nouvelle dans l'interface, suspecter que le **job écrit dans un store différent de celui que consomme le service déployé**. Le cron tourne dans le conteneur Hermes ; le site est souvent déployé à part (Docker / Dokploy sur un VPS) avec sa propre base.

## Étapes de diagnostic

1. **Localiser le store du cron.** Dans le wrapper, repérer le `cd <workdir>` et le chemin de base (variable d'env de la base, ex. `<APP>_DB`, ou `data/app.db`). C'est là que le job écrit. Noter l'absolu.
2. **Localiser le store du consommateur.** Lire le `docker-compose.yml` / `Dockerfile` du déploiement : le `volumes:` (nommé `foo:/data` vs bind-mount `./real/path:/data`) et la variable d'env de la base (`<APP>_DB`) indiquent quelle base le service lit.
3. **Comparer.** Un volume Docker **nommé** (`foo:/data`) est un stockage isolé, distinct du fichier hôte que le cron remplit — même chemin apparent (`/data/app.db`) mais deux fichiers. Un bind-mount partage le vrai fichier. Si les deux stores diffèrent, le job remplit un store que personne ne lit : c'est la cause du vide. Confirmer par un `count(*)` sur la base du consommateur (`docker exec <container> python -c "import sqlite3; print(sqlite3.connect('/data/app.db').execute('select count(*) from <table>').fetchone())"`).
4. **Isoler code vs déploiement.** Lancer le service localement contre la base que le cron remplit (`python -m <pkg>.web.app` dans le workdir du cron, ou avec `<APP>_DB=<base du cron>`), puis `curl` l'endpoint. Si les données apparaissent en local mais pas en déployé → le code est sain, le problème est le store de déploiement. Ne pas relancer le container pour « réparer » : ça redonne une base vide.
5. **Interpréter l'URL déployée.** Ouvrir l'URL publique peut tomber sur un barrage d'accès (ex. page Cloudflare Access « Unauthorized / 401 ») — ce n'est PAS l'application. Confirmer avec l'utilisateur ce qu'il voit de son navigateur (il est peut-être authentifié au-delà du barrage) avant de conclure à une app vide ou cassée.

## Corriger la cause (pas le symptôme)

- **Faire tourner le collecteur dans l'écosystème de déploiement** : ajouter un service annexe au `docker-compose` (ou un cron hôte) qui exécute le même wrapper et écrit dans le même volume que le service web. Collecte et interface partagent alors la base. C'est le fix durable ; redémarrer le service web seul ne remplit jamais la base.
- **Bind-mount** la base réelle à la place du volume nommé, si le collecteur reste sur l'hôte.

## Ne pas confondre avec

- **Collecte qui échoue en amont** (rate-limit LLM 429, source bloquée) : le job peut sortir `ok` avec un compteur `scored: 0` ou des `errors` dans son log — la base se remplit mais l'enrichissement échoue. À distinguer du vide total par un `count(*)` de la base du consommateur.
- **Service web arrêté** (rien n'écoute sur le port) : `curl` échoue en connection refused. Là le fix est de lancer / rendre durable le service, pas de toucher à la base.
