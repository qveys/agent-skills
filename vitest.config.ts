import { configDefaults, defineConfig } from "vitest/config";

// Les worktrees vivent dans .worktrees/ : ne pas y collecter les tests d'autres branches.
export default defineConfig({
  test: { exclude: [...configDefaults.exclude, ".worktrees/**"] },
});
