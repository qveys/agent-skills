# Profils d'environnement (exemples à adapter)

Le noyau du skill est générique. Un profil capture ce qui est propre à UN
environnement : sondes, pièges, règles à recopier dans les briefs. Créer le sien
(un fichier par profil) plutôt que d'enrichir SKILL.md.

## Profil exemple : harnais GitHub + réseau privé

Contexte : l'accès à GitHub passe par des shims (`git`, `gh`) qui imposent une
identité de bot et interdisent le push direct ; un wrapper (`git-signed-commit`)
publie des commits signés ; les machines distantes sont jointes via un VPN
maillé (ex. tailscale) avec ssh intégré.

Sondes :
```bash
PREFLIGHT_HARNESS_DIR=/chemin/du/harnais/bin scripts/preflight.sh --profil gh-harnais \
  --tailscale-ssh HOTE
```
`--profil gh-harnais` lance `claude-gh-check`, vérifie `git-signed-commit` et
`gh auth status` ; un outil absent est ignoré sans bruit. Si le harnais n'est pas
dans le PATH de l'outil d'agent utilisé, passer son dossier via
`PREFLIGHT_HARNESS_DIR`. Pour un VPN : tester ssh ET le ssh du VPN, puis le statut
du VPN, l'utilisateur et le message d'erreur complet avant de classer HUMAIN.

Règles à imposer dans chaque brief de sous-agent : préfixe PATH du harnais pour tout
`git`/`gh`, publication via le wrapper, jamais de push direct, conventions de
commit du dépôt. Un sous-agent hérite du fichier de règles du projet, pas de la
conversation ; ailleurs (autres agents), recopier les règles.

Pièges propres à cet environnement :
- Cron/réveils : ne pas recréer un job existant (le compteur repart) ; les jobs de
  session meurent avec la session. Ne pas appliquer « N ticks calmes = stop » tant
  que la TODO n'est pas vide.
- GUI/computer-use partagé avec l'écran : s'abstenir quand l'utilisateur est devant
  la machine.
- Hôte non résolu : vérifier le nom réel (config ssh, statut du VPN) avant HUMAIN.

## Écrire un autre profil
Gabarit : contexte (qui contrôle l'accès) → sondes (commandes lecture seule) →
règles à recopier dans les briefs → pièges. Exemples : API + base + secrets dans un
`.env` ; cloud CLI avec rôles/SSO expirant ; cluster k8s avec contexte kubectl ;
CI avec runner auto-hébergé.
