# Identifiants Git depuis 1Password (helper shell)

Usage : un dépôt HTTPS (ex. Gitea) doit s'authentifier au push/fetch sans fichier
`.git-credentials` en clair. Le helper est un script shell qui lit l'item via `op`.

## Forme attendue du helper

- Ne répond qu'à l'action `get` : `[ "$1" = get ] || exit 0`.
- Émet deux lignes : `username=...` et `password=...`, lues via `op read op://<Vault>/<Item>/<field>`.
- Le fichier est exécutable et appartient à un uid lisible par le processus Git.

## Vérifications sans afficher le secret

```bash
op account list                                  # session 1Password active
out=$(<helper> get </dev/null); printf '%s\n' "$out" | sed -E 's/^password=.*/password=<masque>/'
```

Attendu : deux lignes, `username=` non vide, `password=` non vide. Si `op` renvoie une erreur
d'authentification, le gestionnaire est verrouillé : le faire déverrouiller par l'utilisateur,
ne jamais demander le mot de passe maître dans le chat.

## Usage

Voir `git-worktree-workflow` (pitfall « Credential helpers that fail silently ») pour la
commande de push qui force le helper voulu, sans modifier la configuration globale.
