# Garder le cockpit ouvert entre les réponses

**Garder le cockpit (et le hop SSH) ouvert tant que le sujet n'est pas clos.**
Une réponse rendue n'est pas une fin de tâche : l'utilisateur relance presque
toujours sur le même hôte, et rouvrir coûte `spawn` + `--situate` + hop + `remote-init`
pour rien. Ne `stop` (ni `exit` le hop) que si l'utilisateur dit que c'est fini
ou le demande explicitement — un changement de sujet ou d'hôte ne ferme rien.
En fin de réponse,
signaler simplement « cockpit `<session>` laissé ouvert ». Tour suivant : réutiliser
la même session (`current`/`status`) avant tout nouveau `spawn`.

## Session idle

Attends au moins 60s avant de traiter une session idle comme orpheline — elle
peut être en plein run. `stop` et `gc` ferment le bloc Wave avec la session tmux (avertissement stderr si échec).
