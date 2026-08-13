import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parse } from "yaml";
import { z } from "zod";

// Regex to ensure no path traversal
const noPathTraversal = /^(?!.*\.\.).*$/;

export const SourceSchema = z.object({
  id: z.string().min(1),
  repo: z
    .string()
    .regex(
      /^[\w.-]+\/[\w.-]+$/,
      "Must be a valid GitHub repository format (owner/repo)",
    ),
  ref: z.string().min(1),
  path: z.string().regex(noPathTraversal, "Path traversal not allowed").min(1),
  destination: z
    .string()
    .regex(/^vendor\//, "Destination must start with vendor/")
    .regex(noPathTraversal, "Path traversal not allowed")
    .min(1),
  enabled: z.boolean().default(true),
});

export const ManifestSchema = z.object({
  version: z.number().int().min(1),
  sources: z.array(SourceSchema),
});

export type Source = z.infer<typeof SourceSchema>;
export type Manifest = z.infer<typeof ManifestSchema>;

export async function loadManifest(filePath: string): Promise<Manifest> {
  try {
    const absolutePath = resolve(process.cwd(), filePath);
    const fileContent = await readFile(absolutePath, "utf8");
    const parsedYaml = parse(fileContent);
    return ManifestSchema.parse(parsedYaml);
  } catch (error) {
    if (error instanceof z.ZodError) {
      throw new Error(`Manifest validation failed: ${error.message}`);
    }
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`Manifest file not found: ${filePath}`);
    }
    throw error;
  }
}

export function validateManifestLogic(manifest: Manifest) {
  const ids = new Set<string>();
  const destinations = new Set<string>();

  for (const source of manifest.sources) {
    if (ids.has(source.id)) {
      throw new Error(`Duplicate source ID found: ${source.id}`);
    }
    ids.add(source.id);

    if (destinations.has(source.destination)) {
      throw new Error(`Duplicate destination found: ${source.destination}`);
    }
    destinations.add(source.destination);
  }
}
