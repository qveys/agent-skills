import { configDefaults, defineConfig } from "vitest/config";

// Les worktrees vivent dans .worktrees/ : ne pas y collecter les tests d'autres branches.
// vendor/ est une copie immuable de l'upstream : ses tests (node:test, .cjs) ne sont pas
// exécutables par vitest et relèvent du dépôt d'origine.
export default defineConfig({
  test: { exclude: [...configDefaults.exclude, ".worktrees/**", "vendor/**"] },
});
