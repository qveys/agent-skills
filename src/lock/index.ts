import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parse, stringify } from "yaml";
import { z } from "zod";

export const LockSourceSchema = z.object({
  repo: z.string(),
  ref: z.string(),
  path: z.string(),
  destination: z.string(),
  commit: z.string(),
  syncedAt: z.string().datetime(),
});

export const LockfileSchema = z.object({
  version: z.number().int(),
  sources: z.record(z.string(), LockSourceSchema),
});

export type LockSource = z.infer<typeof LockSourceSchema>;
export type Lockfile = z.infer<typeof LockfileSchema>;

export async function loadLockfile(filePath: string): Promise<Lockfile> {
  try {
    const absolutePath = resolve(process.cwd(), filePath);
    const fileContent = await readFile(absolutePath, "utf8");
    const parsedYaml = parse(fileContent);
    return LockfileSchema.parse(parsedYaml || { version: 1, sources: {} });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { version: 1, sources: {} };
    }
    if (error instanceof z.ZodError) {
      throw new Error(`Lockfile validation failed: ${error.message}`);
    }
    throw error;
  }
}

export async function saveLockfile(
  filePath: string,
  lockfile: Lockfile,
): Promise<void> {
  const absolutePath = resolve(process.cwd(), filePath);
  const yamlString = stringify(lockfile, { indent: 2 });
  await writeFile(absolutePath, yamlString, "utf8");
}
