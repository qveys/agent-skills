import { execFile } from "node:child_process";
import { createWriteStream } from "node:fs";
import { cp, mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pipeline } from "node:stream/promises";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface UpstreamInfo {
  sha: string;
}

export async function getLatestCommit(
  repo: string,
  ref: string,
): Promise<string> {
  const url = `https://api.github.com/repos/${repo}/commits/${ref}`;
  const response = await fetch(url, {
    headers: {
      "User-Agent": "qveys-agent-skills-cli",
      Accept: "application/vnd.github.v3+json",
    },
  });

  if (!response.ok) {
    throw new Error(
      `Failed to fetch commit info for ${repo}@${ref}: ${response.statusText}`,
    );
  }

  const data = await response.json();
  return data.sha;
}

export async function downloadAndExtract(
  repo: string,
  ref: string,
  sourcePath: string,
  destination: string,
): Promise<void> {
  const tempDir = await mkdtemp(join(tmpdir(), "agent-skills-sync-"));
  const tarballPath = join(tempDir, "repo.tar.gz");
  const extractDir = join(tempDir, "extracted");

  try {
    // 1. Download tarball
    const url = `https://api.github.com/repos/${repo}/tarball/${ref}`;
    const response = await fetch(url, {
      headers: {
        "User-Agent": "qveys-agent-skills-cli",
      },
      redirect: "follow",
    });

    if (!response.ok || !response.body) {
      throw new Error(
        `Failed to download tarball for ${repo}@${ref}: ${response.statusText}`,
      );
    }

    await mkdir(extractDir, { recursive: true });

    // We can't directly pipe from fetch body to fs in all Node versions easily without converting to node stream
    // Using Node 22 native fetch body as an async iterable
    const fileStream = createWriteStream(tarballPath);
    for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
      fileStream.write(chunk);
    }
    fileStream.end();

    await new Promise((resolve) => fileStream.on("finish", resolve));

    // 2. Extract tarball
    // GitHub tarballs have a root directory named owner-repo-sha.
    // We first find this root directory name.
    const { stdout: tarList } = await execFileAsync("tar", [
      "-tf",
      tarballPath,
    ]);
    const rootDir = tarList.split("\n")[0].split("/")[0];

    if (!rootDir) {
      throw new Error("Could not determine root directory from tarball");
    }

    const exactPathToExtract = `${rootDir}/${sourcePath}`;

    // Extract only the specific path
    await execFileAsync("tar", [
      "-xzf",
      tarballPath,
      "-C",
      extractDir,
      exactPathToExtract,
    ]);

    // 3. Move to destination
    const extractedSourcePath = join(extractDir, exactPathToExtract);
    await rm(destination, { recursive: true, force: true });
    await mkdir(dirname(destination), { recursive: true });
    await cp(extractedSourcePath, destination, { recursive: true });
  } catch (error) {
    throw new Error(
      `Failed to extract ${sourcePath} from ${repo}: ${(error as Error).message}`,
    );
  } finally {
    // 4. Cleanup
    await rm(tempDir, { recursive: true, force: true });
  }
}
