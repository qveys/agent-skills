# Instructions for AI Agents

When operating within this repository, follow these critical rules:

## 1. Do Not Modify Vendored Skills
**NEVER manually customize, edit, or refactor any file located inside the `vendor/` directory.**
- The `vendor/` directory is exclusively managed by the automated sync tool.
- Changes to `vendor/` must come from upstream repositories via the synchronization mechanism (`npm run skills:sync`).
- If a skill in `vendor/` requires modification or customization, copy the skill to the `skills/` directory and apply the changes there.

## 2. Proprietary Skills
Any new skills created specifically for this project, or modified copies of vendored skills, should be placed in the `skills/` directory.

## 3. Sync Mechanisms
Do not run fetched scripts during the synchronization process to prevent accidental execution of untrusted upstream code. Use `npm run skills:check` and `npm run skills:sync` to manage upstream skills.

## 4. Documentation
When creating a new skill, follow the structure demonstrated in `skills/_template/`.
