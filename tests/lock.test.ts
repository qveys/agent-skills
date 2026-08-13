import { describe, expect, it } from "vitest";
import { LockfileSchema } from "../src/lock/index.js";

describe("Lockfile Validation", () => {
  it("should accept a valid lockfile", () => {
    const validLockfile = {
      version: 1,
      sources: {
        "test-skill": {
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo/test-skill",
          commit: "abc123def456",
          syncedAt: "2026-08-13T12:00:00Z",
        },
      },
    };

    expect(() => LockfileSchema.parse(validLockfile)).not.toThrow();
  });

  it("should reject lockfile with invalid date", () => {
    const invalidLockfile = {
      version: 1,
      sources: {
        "test-skill": {
          repo: "author/repo",
          ref: "main",
          path: "skills/test-skill",
          destination: "vendor/author-repo/test-skill",
          commit: "abc123def456",
          syncedAt: "not-a-date",
        },
      },
    };

    const result = LockfileSchema.safeParse(invalidLockfile);
    expect(result.success).toBe(false);
  });
});
