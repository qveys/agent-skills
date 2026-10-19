---
name: preflight-autonome
description: >-
  Preflight avant de laisser un agent travailler en autonomie : lister les items
  d'une TODO, tester par une sonde lecture seule chaque accès requis (git/GitHub,
  ssh, tailscale ssh, API, secrets, sudo, computer-use), classer PRÊT /
  CONTOURNABLE / RÉELLEMENT HUMAIN et produire un tableau AVANT de lancer la
  boucle. À utiliser dès que l'utilisateur dit « sois autonome », « laisse
  tourner », « je pars », « continue sans moi », « fais toute la TODO », parle
  d'une TODO longue, d'une session laissée ouverte, ou lance /loop ou /goal,
  même s'il ne demande pas explicitement de vérifier les accès. Pas pour une
  tâche courte et interactive où l'utilisateur répond en direct.
---

# Preflight autonome

Un agent laissé seul perd des heures sur un blocage découvert tard (ssh refusé,
secret vide, harnais GitHub oublié) et conclut « impossible » sans diagnostic.
Le preflight déplace cette découverte AVANT la boucle, avec des preuves.

## 1. Inventaire
Extraire de la TODO (fichier ou conversation) chaque item et l'accès qu'il exige :
git/GitHub, ssh / tailscale ssh, API, secrets, GUI/computer-use, sudo, services externes.

## 2. Sondes lecture seule
Une sonde = une commande, timeout court, aucun effet de bord. Lancer :
```bash
scripts/preflight.sh --ssh HOTE --tailscale-ssh HOTE --env .env CLE --cmd "libellé::commande"
```
Options répétables. Sondes automatiques : `claude-gh-check`, présence de
`git-signed-commit`, `gh auth status`, `sudo -n true` (`--no-auto` pour les couper).
Sortie : `PASS|FAIL|WARN<TAB>libellé<TAB>détail`, code retour = nombre de FAIL.
Secrets : seulement SET / EMPTY / ABSENT, jamais la valeur. Computer-use : vérifier
à la main que les outils existent (liste d'outils), sans cliquer.

Ne conclure « impossible » pour ssh qu'après diagnostic : essayer ssh ET
`tailscale ssh`, puis statut tailscale, utilisateur, mode check, message d'erreur complet. Hôte non résolu : vérifier le nom réel (`tailscale status`, config ssh) avant de classer HUMAIN.

## 3. Classement
- **PRÊT** : sonde PASS.
- **CONTOURNABLE** : sonde FAIL mais alternative existante ; l'écrire (ex. tailscale ssh au lieu de ssh).
- **RÉELLEMENT HUMAIN** : touche physique, secret absent, décision irréversible ; noter cause exacte et contournements essayés.

Un blocage humain ne stoppe JAMAIS la boucle : passer à l'item suivant. Décision à
prendre : choisir l'option recommandée RÉVERSIBLE (PR ouverte jamais fusionnée),
consigner, signaler après.

## 4. Règles permanentes
Avant de rédiger un brief de sous-agent, relire CLAUDE.md global, la mémoire et les
règles du dépôt. Si un harnais d'accès existe (ex. shims git/gh), l'imposer dans
chaque brief : un sous-agent hérite du CLAUDE.md mais pas de la conversation : y recopier les règles utiles au contrat de la tâche, dont le harnais d'accès.

## 5. Lancement
- Proposer à l'utilisateur la condition `/goal` : objectif = vider la TODO, condition vérifiable
  par les comptes-rendus, borne « ou stop après N tours ». L'agent ne peut pas taper `/goal` lui-même.
- Ne pas recréer un cron/réveil existant (le compteur repart). Les jobs de session meurent avec la session.
- Ne pas appliquer « 3 ticks calmes = stop » tant que la TODO n'est pas vide.
- Pas de GUI/computer-use quand l'utilisateur est devant la machine.

## 6. Journal
Consigner chaque preuve (OK/ÉCHEC + sortie brute) dans le fichier de suivi de la TODO.

## Sortie attendue
Tableau, avant de lancer la boucle :

| item | accès | sonde | résultat | classe | action |
|---|---|---|---|---|---|
