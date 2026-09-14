# Reply templates & language detection

Read this at Step 7, when writing the `message` of each thread update.

## Language detection

1. Count comment bodies that are clearly English vs. clearly French (or other language).
2. **Default to English** when uncertain or when counts are equal.
3. Write all thread replies in the detected language.

## English

| Status | Template |
|---|---|
| Resolved | `Fixed in \`<sha>\` – <brief explanation>.` |
| Unresolved – ambiguous | `Not resolved: unclear request. Could you clarify whether you mean X or Y?` |
| Unresolved – patch error | `Not resolved: \`git apply\` failed (\`<error>\`). Please review the diff manually.` |
| Not relevant | `No code change needed here. Thanks for the feedback!` |

## French

| Statut | Modèle |
|---|---|
| Résolu | `Corrigé dans \`<sha>\` – <explication courte>.` |
| Non résolu – ambigu | `Non résolu : la demande est ambiguë. Pourriez-vous préciser si vous voulez X ou Y ?` |
| Non résolu – patch échoué | `Non résolu : \`git apply\` a échoué (\`<erreur>\`). Merci de vérifier le diff manuellement.` |
| Non pertinent | `Aucun changement de code nécessaire ici. Merci pour le retour !` |
