# Garder le cockpit ouvert entre les réponses

**Garder le cockpit (et le hop SSH) ouvert tant que le sujet n'est pas clos.**
Une réponse rendue n'est pas une fin de tâche : l'utilisateur relance presque
toujours sur le même hôte, et rouvrir coûte `spawn` + `--situate` + hop + `remote-init`
pour rien. Ne `stop` (ni `exit` le hop) que si l'utilisateur dit que c'est fini
ou le demande explicitement — un changement de sujet ou d'hôte ne ferme rien.
En fin de réponse, signaler simplement « cockpit `<session>` laissé ouvert ».

## Au tour suivant : cibler la session par son nom explicite

`current` et `status` ne voient que les sessions de TA propre clé
`WSH_COCKPIT_AGENT` (fichier `last-session-*` et registre des claims) : un
sous-agent avec une autre clé ne retrouvera pas le cockpit laissé ouvert. Tour
suivant, réutilise donc la session **par son nom explicite**, passé en argument
(`$L send '<cmd>' <session>`, `$L wait-done <session>`, …) avant tout nouveau
`spawn`.

## Session idle

Attends au moins 60s avant de traiter une session idle comme orpheline — elle
peut être en plein run. `gc` ferme le bloc Wave avec la session tmux ; `stop` aussi, sauf `--keep` :
il la libère (`release`), tmux et bloc restent.

