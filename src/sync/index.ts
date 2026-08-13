import type { Lockfile } from "../lock/index.js";
import type { Manifest } from "../manifest/index.js";
import { downloadAndExtract, getLatestCommit } from "../upstream/index.js";

export async function checkUpdates(manifest: Manifest, lockfile: Lockfile) {
  const updates: Array<{
    id: string;
    installed: string | null;
    upstream: string;
    status: "up-to-date" | "update available" | "new";
  }> = [];

  for (const source of manifest.sources) {
    if (!source.enabled) continue;

    const lockEntry = lockfile.sources[source.id];
    const latestSha = await getLatestCommit(source.repo, source.ref);

    let status: "up-to-date" | "update available" | "new" = "new";
    if (lockEntry) {
      if (lockEntry.commit === latestSha) {
        status = "up-to-date";
      } else {
        status = "update available";
      }
    }

    updates.push({
      id: source.id,
      installed: lockEntry ? lockEntry.commit : null,
      upstream: latestSha,
      status,
    });
  }

  return updates;
}

export async function syncSources(
  manifest: Manifest,
  lockfile: Lockfile,
  targetId?: string,
) {
  const sourcesToSync = targetId
    ? manifest.sources.filter((s) => s.id === targetId)
    : manifest.sources.filter((s) => s.enabled);

  if (sourcesToSync.length === 0) {
    if (targetId) {
      throw new Error(`Source with ID '${targetId}' not found or not enabled.`);
    }
    return false; // Nothing to sync
  }

  let hasUpdates = false;

  for (const source of sourcesToSync) {
    const lockEntry = lockfile.sources[source.id];
    const latestSha = await getLatestCommit(source.repo, source.ref);

    if (lockEntry && lockEntry.commit === latestSha) {
      console.log(
        `[${source.id}] is up-to-date (${latestSha.substring(0, 7)})`,
      );
      continue;
    }

    console.log(
      `[${source.id}] Fetching ${source.repo}@${latestSha.substring(0, 7)}...`,
    );
    await downloadAndExtract(
      source.repo,
      source.ref,
      source.path,
      source.destination,
    );

    lockfile.sources[source.id] = {
      repo: source.repo,
      ref: source.ref,
      path: source.path,
      destination: source.destination,
      commit: latestSha,
      syncedAt: new Date().toISOString(),
    };

    hasUpdates = true;
    console.log(`[${source.id}] Successfully synced.`);
  }

  return hasUpdates;
}
