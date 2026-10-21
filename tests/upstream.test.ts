import { afterEach, describe, expect, it, vi } from "vitest";
import { apiHeaders, archiveMemberPath } from "../src/upstream/index.js";

describe("archiveMemberPath", () => {
  it("traite '.' et '' comme la racine", () => {
    expect(archiveMemberPath("root", ".")).toBe("root");
    expect(archiveMemberPath("root", "")).toBe("root");
    expect(archiveMemberPath("root", "./")).toBe("root");
  });
  it("normalise les sous-chemins", () => {
    expect(archiveMemberPath("root", "skills/x")).toBe("root/skills/x");
    expect(archiveMemberPath("root", "./skills/x/")).toBe("root/skills/x");
  });
});

describe("apiHeaders", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("ajoute Authorization si GH_TOKEN est défini", () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    vi.stubEnv("GH_TOKEN", "abc");
    expect(apiHeaders().Authorization).toBe("Bearer abc");
  });
  it("n'ajoute rien sans jeton", () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    vi.stubEnv("GH_TOKEN", "");
    expect(apiHeaders()).not.toHaveProperty("Authorization");
  });
});
