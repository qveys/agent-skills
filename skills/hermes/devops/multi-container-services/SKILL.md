---
name: multi-container-services
description: "Deploy loopback services across container boundaries."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [multi-container, loopback-service, sidecar, health-check, deployment, verification]
    related_skills: [kanban-worker-dispatch, hermes-plugin-env-config]
---

# Services multi-conteneurs

Déployer ou vérifier un service loopback (sidecar, health endpoint, API locale) qui doit être joignable par un autre conteneur via `127.0.0.1`.

## Règle centrale

**Le conteneur qui compte est celui qui fait le proxy, pas celui qui déploie.**

Si la WebUI proxyfie `sidecar.origin` vers `127.0.0.1`, c'est dans le conteneur WebUI que le sidecar doit tourner. Un sidecar lancé dans le conteneur agent est injoignable depuis la WebUI par conception — ça « fonctionne » jusqu'à ce qu'on tente de l'utiliser.

## Checklist de déploiement

1. **Qui proxyfie ?** Identifier quel conteneur résout `sidecar.origin` vers `127.0.0.1`. C'est là que le service doit tourner.
2. **Vérifier le namespace PID.** Un pidfile écrit dans un conteneur ne peut pas tuer un processus dans un autre (PID namespaces distincts). Ne jamais faire confiance à un pidfile issu d'un autre conteneur.
3. **Le script de démarrage doit être spécifique au conteneur cible.** Documenter clairement : « ce script tourne dans `hermes-webui`, pas dans `hermes-agent` ».
4. **Tester le health check depuis le conteneur qui proxyfie.** `curl -s http://127.0.0.1:PORT/health` depuis ce conteneur, pas depuis l'hôte.
5. **Vérifier l'injection réelle.** Pas seulement la validité du manifest — vérifier que les balises sont injectées dans la page servie, que les assets sont servis sous `/extensions/`, que les endpoints API existent (`/api/extensions/status`, `/api/extensions/registry`).
6. **Vérifier le comptage.** Si le sidecar annonce N notes mais le vault en contient M, expliquer l'écart (filtrage, doublons, mesure antérieure).

## Démarrage durable

Le conteneur cible ne supervise pas les extensions. Pour qu'un sidecar survive au redémarrage du conteneur, il faut un mécanisme externe :

- **Cron @reboot** dans le conteneur cible : simple, suffisant pour la plupart des cas.
- **Superviseur système** (systemd, supervisord) : si disponible dans le conteneur.
- **Entrypoint du conteneur** : si on contrôle l'image.

Le script de lancement doit être idempotent (ne démarre que si aucun ne tourne dans ce conteneur) et détecter les pidfiles invalides.

## Pièges

- **Pidfile inter-conteneurs.** Un `sidecar.pid` écrit dans un conteneur désigne un PID sans rapport dans l'autre. Un script qui tue le pidfile hérité peut tuer un process étranger. Vérifier que le PID correspond à un process Python exécutant le bon script dans ce conteneur, sinon ignorer le pidfile.
- **Détection par port trop agressive.** Après un kill, le kernel garde le port en TIME_WAIT. Un script qui détecte le port occupé et refuse de redémarrer peut être bloqué indéfiniment. Préférer la détection par pidfile valide + vérification que le process est vivant.
- **Health check avec pattern JSON rigide.** `grep -q '"status":"ok"'` échoue sur `{"status": "ok", ...}` (espace après `:`). Utiliser `grep -qE '"status"\s*:\s*"ok"'` pour être tolerant des espaces JSON.
- **Kill d'un pidfile périmé.** Si le pidfile contient un PID mort (crash non nettoyé), le script peut tenter de killer un PID inexistant et continuer comme si tout était bon. Toujours vérifier que le PID est vivant (`kill -0`) avant de considérer le pidfile valide.

## Références

- Voir le fichier de référence `references/loopback-service-checklist.md` pour la checklist détaillée et le template de script.
