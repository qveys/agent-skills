import { existsSync } from "node:fs";
import { parseArgs } from "node:util";
import { loadLockfile, saveLockfile } from "../lock/index.js";
import { loadManifest, validateManifestLogic } from "../manifest/index.js";
import { checkUpdates, syncSources } from "../sync/index.js";

const MANIFEST_PATH = "sources.yaml";
const LOCKFILE_PATH = "sources.lock.yaml";

async function main() {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2),
    options: {
      id: { type: "string" },
      all: { type: "boolean" },
    },
    allowPositionals: true,
  });

  const command = positionals[0];

  try {
    switch (command) {
      case "check":
        await handleCheck();
        break;
      case "sync":
        await handleSync(values);
        break;
      case "validate":
        await handleValidate();
        break;
      default:
        console.log("Usage: npm run skills:<command> [-- --id <id> | --all]");
        console.log("Commands: check, sync, validate");
        process.exit(1);
    }
  } catch (error) {
    console.error(`Error: ${(error as Error).message}`);
    process.exit(1);
  }
}

async function handleCheck() {
  const manifest = await loadManifest(MANIFEST_PATH);
  const lockfile = await loadLockfile(LOCKFILE_PATH);

  const updates = await checkUpdates(manifest, lockfile);
  let hasUpdates = false;

  for (const update of updates) {
    console.log(`\n${update.id}`);
    console.log(`installed: ${update.installed || "none"}`);
    console.log(`upstream:  ${update.upstream}`);
    console.log(`status:    ${update.status}`);

    if (update.status !== "up-to-date") {
      hasUpdates = true;
    }
  }

  if (!hasUpdates) {
    console.log("\nAll skills are up-to-date.");
  }
}

async function handleSync(options: { id?: string; all?: boolean }) {
  if (!options.id && !options.all) {
    console.log(
      "Please specify --id <id> or use --all to sync all enabled sources.",
    );
    process.exit(1);
  }

  const manifest = await loadManifest(MANIFEST_PATH);
  const lockfile = await loadLockfile(LOCKFILE_PATH);

  const hasUpdates = await syncSources(manifest, lockfile, options.id);

  if (hasUpdates) {
    await saveLockfile(LOCKFILE_PATH, lockfile);
    console.log("\nLockfile updated.");
  } else {
    console.log("\nNothing to sync.");
  }
}

async function handleValidate() {
  const manifest = await loadManifest(MANIFEST_PATH);
  validateManifestLogic(manifest);

  // Additional validations (checking destinations, SKILL.md)
  for (const source of manifest.sources) {
    if (!source.enabled) continue;

    if (!source.destination.startsWith("vendor/")) {
      throw new Error(`[${source.id}] Destination must be inside vendor/`);
    }

    if (source.destination.includes("..")) {
      throw new Error(`[${source.id}] Path traversal detected in destination`);
    }

    // Checking if SKILL.md exists in destination (if already synced)
    const skillMdPath = `${source.destination}/SKILL.md`;
    if (existsSync(source.destination) && !existsSync(skillMdPath)) {
      console.warn(
        `Warning: [${source.id}] missing SKILL.md in ${source.destination}`,
      );
    }
  }

  const lockfile = await loadLockfile(LOCKFILE_PATH);
  // Validate consistency
  for (const [id, lockEntry] of Object.entries(lockfile.sources) as [
    string,
    any,
  ][]) {
    const manifestSource = manifest.sources.find((s) => s.id === id);
    if (!manifestSource) {
      console.warn(
        `Warning: Source '${id}' exists in lockfile but not in manifest.`,
      );
    } else if (manifestSource.destination !== lockEntry.destination) {
      console.warn(
        `Warning: Destination mismatch for '${id}' between manifest and lockfile.`,
      );
    }
  }

  console.log("Validation passed.");
}

// Ignore if this is imported during tests
if (process.env.NODE_ENV !== "test") {
  main();
}
