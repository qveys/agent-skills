import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const script = join(
  process.cwd(),
  "skills/preflight-autonome/scripts/preflight.sh",
);

function run(args: string[], stubs: Record<string, string> = {}) {
  const dir = mkdtempSync(join(tmpdir(), "preflight-"));
  for (const [name, body] of Object.entries(stubs)) {
    const p = join(dir, name);
    writeFileSync(p, `#!/bin/sh\n${body}\n`);
    chmodSync(p, 0o755);
  }
  const r = spawnSync("bash", [script, "--no-auto", ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${dir}:${process.env.PATH}`,
      PREFLIGHT_TIMEOUT: "3",
    },
  });
  return { dir, out: r.stdout, code: r.status };
}

describe("preflight.sh", () => {
  it("PASS : sonde ssh stub OK, code 0", () => {
    const r = run(["--ssh", "h"], { ssh: "exit 0" });
    expect(r.out).toMatch(/^PASS\tssh h\t/);
    expect(r.code).toBe(0);
  });

  it("FAIL : sonde --cmd en échec, code = nombre de FAIL", () => {
    const r = run(["--cmd", "a::exit 1", "--cmd", "b::exit 0"]);
    expect(r.out).toMatch(/FAIL\ta\t/);
    expect(r.out).toMatch(/PASS\tb\t/);
    expect(r.code).toBe(1);
  });

  it("FAIL tailscale ssh : ajoute le diagnostic de statut", () => {
    const r = run(["--tailscale-ssh", "h"], {
      tailscale:
        '[ "$1" = status ] && echo "100.1.1.1 up" && exit 0; echo denied >&2; exit 1',
    });
    expect(r.out).toMatch(/FAIL\ttailscale ssh h\t.*denied/);
    expect(r.out).toMatch(/WARN\ttailscale status\t100.1.1.1/);
    expect(r.code).toBe(1);
  });

  it("secrets : SET / EMPTY / ABSENT sans jamais la valeur", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, 'FULL="s3cr3t-value"\nEMPTY=\n');
    const r = run([
      "--env",
      f,
      "FULL",
      "--env",
      f,
      "EMPTY",
      "--env",
      f,
      "NOPE",
    ]);
    expect(r.out).toMatch(/PASS\tenv FULL\tSET/);
    expect(r.out).toMatch(/FAIL\tenv EMPTY\tEMPTY/);
    expect(r.out).toMatch(/FAIL\tenv NOPE\tABSENT/);
    expect(r.out).not.toContain("s3cr3t-value");
    expect(r.code).toBe(2);
  });

  it("timeout : sonde lente = FAIL", () => {
    const r = run(["--cmd", "slow::sleep 10"]);
    expect(r.out).toMatch(/FAIL\tslow\ttimeout/);
  });

  it("hôte commençant par - : rejeté, usage, code 2, ssh jamais appelé", () => {
    for (const flag of ["--ssh", "--tailscale-ssh"]) {
      const r = run([flag, "-oProxyCommand=touch /tmp/pwn"], {
        ssh: "echo CALLED",
        tailscale: "echo CALLED",
      });
      expect(r.code).toBe(2);
      expect(r.out).not.toContain("CALLED");
    }
  });

  it("clé --env invalide (regex) : rejetée, code 2", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, "API_KEY=x\n");
    expect(run(["--env", f, "API.KEY"]).code).toBe(2);
  });

  it("valeur faite de blancs (même entre guillemets) : EMPTY", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, 'A="   "\nB=   \n');
    const r = run(["--env", f, "A", "--env", f, "B"]);
    expect(r.out).toMatch(/FAIL\tenv A\tEMPTY/);
    expect(r.out).toMatch(/FAIL\tenv B\tEMPTY/);
  });
});
