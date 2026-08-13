import { describe, expect, it } from "vitest";
import {
  ManifestSchema,
  validateManifestLogic,
} from "../src/manifest/index.js";

describe("Manifest Validation", () => {
  it("should accept a valid manifest", () => {
    const validManifest = {
      version: 1,
      sources: [
        {
          id: "test-skill",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo/test-skill",
          enabled: true,
        },
      ],
    };

    expect(() => ManifestSchema.parse(validManifest)).not.toThrow();
  });

  it("should reject manifest with duplicate IDs", () => {
    const manifest = {
      version: 1,
      sources: [
        {
          id: "test-skill",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo/test-skill",
          enabled: true,
        },
        {
          id: "test-skill",
          repo: "author/repo2",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo2/test-skill",
          enabled: true,
        },
      ],
    };

    expect(() => validateManifestLogic(manifest as any)).toThrow(
      /Duplicate source ID found/,
    );
  });

  it("should reject manifest with duplicate destinations", () => {
    const manifest = {
      version: 1,
      sources: [
        {
          id: "test-skill-1",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo/test-skill",
          enabled: true,
        },
        {
          id: "test-skill-2",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill-2",
          destination: "vendor/author-repo/test-skill",
          enabled: true,
        },
      ],
    };

    expect(() => validateManifestLogic(manifest as any)).toThrow(
      /Duplicate destination found/,
    );
  });

  it("should reject destination outside vendor/", () => {
    const invalidManifest = {
      version: 1,
      sources: [
        {
          id: "test-skill",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "skills/author-repo/test-skill",
          enabled: true,
        },
      ],
    };

    const result = ManifestSchema.safeParse(invalidManifest);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.message).toMatch(
        /Destination must start with vendor\//,
      );
    }
  });

  it("should reject path traversal in destination", () => {
    const invalidManifest = {
      version: 1,
      sources: [
        {
          id: "test-skill",
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/../../skills/malicious",
          enabled: true,
        },
      ],
    };

    const result = ManifestSchema.safeParse(invalidManifest);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.message).toMatch(/Path traversal not allowed/);
    }
  });
});
