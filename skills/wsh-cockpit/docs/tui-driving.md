# Piloter un TUI (Claude Code, REPL) — pas avec `send`

`send` est framé pour un shell : ses marqueurs `┌─[#N]`/`└─[#N]` et `wait-done`
n'ont pas de sens dans une interface qui relit le clavier caractère par
caractère. Pour un TUI, on parle directement à `tmux send-keys`.

## Entrée avalée quand le texte est long

`tmux send-keys '<texte>' Enter` en un seul appel échoue avec un texte long :

- l'Entrée est avalée, le texte reste bloqué dans l'invite `❯` ;
- les deux Entrée suivants sont avalés aussi ;
- c'est le troisième qui finit par passer.

Un texte court passe en un appel, mais ne pas s'y fier : le seuil dépend de la
taille du pane et de la célérité du TUI, pas du contenu.

## Recette en trois temps

1. `tmux send-keys -t "$SESS" '<texte>'` — sans Entrée.
2. `sleep 2`, puis `tmux send-keys -t "$SESS" Enter`. Un seul Entrée suffit
   (`Enter` et `C-m` sont équivalents ici).
3. Relire le pane : le texte a quitté `❯` et le TUI travaille. Sinon renvoyer
   `Enter`, jusqu'à 3 fois, en revérifiant à chaque fois.

Ne jamais déclarer « envoyé » sans l'étape 3 : l'état de l'invite est la seule
preuve que le TUI a pris le texte.

## Limite de longueur

Mesures observées, seuil exact non mesuré :

| Taille du texte | Résultat avec la pause de 2 s |
| --------------- | ----------------------------- |
| ~600 caractères | passe |
| ~1 600 caractères | arrivé TRONQUÉ (début perdu, seule la fin reçue) |

Au-delà de ~500 caractères, ne pas tenter la limite : écrire la consigne dans un
fichier (scratchpad ou vault) et envoyer une phrase courte du type
`Lis <chemin> et exécute-la à la lettre.`, puis relire le pane (étape 3) pour
vérifier que l'agent a bien ouvert le fichier. La règle sûre : tout ce qui n'est
pas une phrase courte passe par un fichier.
