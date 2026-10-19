import { describe, expect, it } from "vitest";
import { archiveMemberPath } from "../src/upstream/index.js";

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
