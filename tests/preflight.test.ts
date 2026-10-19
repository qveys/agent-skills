import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const script = join(
  process.cwd(),
  "skills/preflight-autonome/scripts/preflight.sh",
);

function run(
  args: string[],
  stubs: Record<string, string> = {},
  timeout = "3",
) {
  const dir = mkdtempSync(join(tmpdir(), "preflight-"));
  for (const [name, body] of Object.entries(stubs)) {
    const p = join(dir, name);
    writeFileSync(p, `#!/bin/sh\n${body}\n`);
    chmodSync(p, 0o755);
  }
  const r = spawnSync("bash", [script, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${dir}:${process.env.PATH}`,
      PREFLIGHT_TIMEOUT: timeout,
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
      expect(r.code).toBe(64);
      expect(r.out).not.toContain("CALLED");
    }
  });

  it("clé --env invalide (regex) : rejetée, code 2", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, "API_KEY=x\n");
    expect(run(["--env", f, "API.KEY"]).code).toBe(64);
  });

  it("valeur faite de blancs (même entre guillemets) : EMPTY", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, 'A="   "\nB=   \n');
    const r = run(["--env", f, "A", "--env", f, "B"]);
    expect(r.out).toMatch(/FAIL\tenv A\tEMPTY/);
    expect(r.out).toMatch(/FAIL\tenv B\tEMPTY/);
  });

  it("défaut : aucune sonde, aucun outil propre à un environnement appelé", () => {
    const stub = "echo CALLED; exit 0";
    const r = run([], {
      "claude-gh-check": stub,
      "git-signed-commit": stub,
      gh: stub,
      sudo: stub,
      tailscale: stub,
    });
    expect(r.out).toBe("");
    expect(r.code).toBe(0);
  });

  it("--profil gh-harnais : opt-in, outil absent = silence", () => {
    const r = run(["--profil", "gh-harnais"], {
      "claude-gh-check": "exit 0",
      gh: "exit 0",
    });
    expect(r.out).toMatch(/^PASS\tclaude-gh-check\t/);
    expect(r.out).not.toMatch(/WARN/);
    expect(run(["--profil", "autre"]).code).toBe(64);
  });

  it("PREFLIGHT_HARNESS_DIR est préfixé au PATH : son gh passe avant un gh existant", () => {
    const harness = mkdtempSync(join(tmpdir(), "harness-"));
    writeFileSync(join(harness, "gh"), "#!/bin/sh\necho SHIM; exit 1\n");
    chmodSync(join(harness, "gh"), 0o755);
    const dir = mkdtempSync(join(tmpdir(), "preflight-"));
    writeFileSync(join(dir, "gh"), "#!/bin/sh\nexit 0\n");
    chmodSync(join(dir, "gh"), 0o755);
    const r = spawnSync("bash", [script, "--profil", "gh-harnais"], {
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${dir}:${process.env.PATH}`,
        PREFLIGHT_HARNESS_DIR: harness,
      },
    });
    expect(r.stdout).toMatch(/FAIL\tgh auth status\t.*SHIM/);
  });

  it("entrée avec saut de ligne / retour chariot / tab : rejetée, aucune ligne forgée", () => {
    for (const bad of [
      "https://a.test/x\nPASS\tforge\tok",
      "https://a.test/\r",
      "https://a.test/\t",
    ]) {
      const r = run(["--http", bad], { curl: "printf 200" });
      expect(r.code).toBe(64);
      expect(r.out).not.toContain("forge");
    }
    expect(run(["--ssh", "h\nPASS\tforge\tok"], { ssh: "exit 0" }).code).toBe(
      64,
    );
  });

  it("--http : 2xx PASS, 401 WARN, 500 FAIL, userinfo et query masqués", () => {
    const curl = (code: string) => ({ curl: `printf ${code}` });
    expect(run(["--http", "https://a.test/h"], curl("200")).out).toMatch(
      /^PASS\thttp https:\/\/a.test\t200/,
    );
    expect(run(["--http", "https://a.test/h"], curl("401")).out).toMatch(
      /^WARN/,
    );
    const r = run(
      [
        "--http",
        ["https://", "u", ":", "pw", "@a.test/h?token=SECRET"].join(""),
      ],
      curl("500"),
    );
    expect(r.out).toMatch(/^FAIL\thttp https:\/\/a.test\t500/);
    expect(r.out).not.toContain("SECRET");
    expect(r.out).not.toContain("pw");
    expect(r.code).toBe(1);
  });

  it("--http : URL non http(s) ou commençant par - rejetée, code 2", () => {
    expect(run(["--http", "-oX"], { curl: "echo CALLED" }).code).toBe(64);
    expect(run(["--http", "file:///etc/passwd"]).code).toBe(64);
  });

  it("--cli : présent PASS, absent FAIL ; nom invalide rejeté", () => {
    const r = run(["--cli", "montool", "--cli", "introuvable-xyz"], {
      montool: "exit 0",
    });
    expect(r.out).toMatch(/PASS\tcli montool\t/);
    expect(r.out).toMatch(/FAIL\tcli introuvable-xyz\t/);
    expect(run(["--cli", "-x"]).code).toBe(64);
  });

  it("--git-remote : git ls-remote origin, FAIL si injoignable", () => {
    expect(run(["--git-remote"], { git: "exit 0" }).out).toMatch(
      /^PASS\tgit remote origin/,
    );
    const r = run(["--git-remote"], { git: "echo no access >&2; exit 128" });
    expect(r.out).toMatch(/FAIL\tgit remote origin\trc=128 no access/);
  });

  it("scénario API + base + secret manquant : un FAIL n'empêche pas les autres sondes", () => {
    const dir = mkdtempSync(join(tmpdir(), "env-"));
    const f = join(dir, ".env");
    writeFileSync(f, "DATABASE_URL=db-secret-value-placeholder\n");
    const r = run(
      [
        "--http",
        "https://api.test/health",
        "--cmd",
        "db::exit 0",
        "--env",
        f,
        "DATABASE_URL",
        "--env",
        f,
        "API_TOKEN",
      ],
      { curl: "printf 200" },
    );
    expect(r.out).toMatch(/PASS\thttp /);
    expect(r.out).toMatch(/PASS\tdb\t/);
    expect(r.out).toMatch(/PASS\tenv DATABASE_URL\tSET/);
    expect(r.out).toMatch(/FAIL\tenv API_TOKEN\tABSENT/);
    expect(r.out).not.toContain("db-secret-value-placeholder");
    expect(r.code).toBe(1);
  });

  it("--git-remote / --cmd : identifiants d'URL jamais affichés", () => {
    const url = ["https://u", "ser:s3cr", "3t@example.com/x.git/"].join("");
    const r = run(["--git-remote", "--cmd", `c::echo ${url}; exit 1`], {
      git: `echo "fatal: unable to access '${url}'" >&2; exit 128`,
    });
    expect(r.out).toMatch(/FAIL\tgit remote origin\trc=128 fatal/);
    expect(r.out).toMatch(/FAIL\tc\t/);
    expect(r.out).not.toContain("s3cr3t");
    expect(r.out).not.toContain("user:");
  });

  it("--http : libellé = scheme://host, sans chemin ni fragment", () => {
    const tok = ["tok", "en-x"].join("");
    const r = run(["--http", `https://a.test:8443/v1/${tok}?q=${tok}#${tok}`], {
      curl: "printf 200",
    });
    expect(r.out).toMatch(/^PASS\thttp https:\/\/a.test:8443\t200/);
    expect(r.out).not.toContain(tok);
  });

  it("--cmd sans :: refusé (code 64) ; --no-auto accepté sans effet", () => {
    expect(run(["--cmd", "ok"]).code).toBe(64);
    const r = run(["--no-auto"]);
    expect(r.out).toBe("");
    expect(r.code).toBe(0);
  });

  it("timeout : un pipeline qui bloque est interrompu", () => {
    const t0 = Date.now();
    const r = run(["--cmd", "p::sleep 30 | cat"], {}, "2");
    expect(r.out).toMatch(/FAIL\tp\ttimeout/);
    expect(Date.now() - t0).toBeLessThan(10000);
  });

  it("identifiants d'URL avec / ou @ dans le mot de passe : masqués", () => {
    const a = ["https://u:pa", "/ss", "@h/x"].join("");
    const b = ["https://u:p", "@ss", "@h/x"].join("");
    const r = run(["--cmd", `x::echo ${a}`, "--cmd", `y::echo ${b}`], {});
    expect(r.out).toContain("https://h/x");
    for (const leak of ["pa/ss", "ss@", "u:p"])
      expect(r.out).not.toContain(leak);
    const h = run(["--http", a], { curl: "printf 200" });
    expect(h.out).toMatch(/^PASS\thttp https:\/\/h\t200/);
  });

  it("--http : l'URL passe par stdin, pas par argv", () => {
    const r = run(["--http", "https://a.test/p?k=SECRETQ"], {
      curl: 'case "$*" in *SECRETQ*) echo ARGV; exit 1;; esac; grep -q SECRETQ && printf 200',
    });
    expect(r.out).toMatch(/^PASS\thttp https:\/\/a.test\t200/);
  });

  it("code retour plafonné à 63 (64 = usage)", () => {
    const cmds = Array.from({ length: 70 }, (_, i) => [
      "--cmd",
      `f${i}::exit 1`,
    ]);
    expect(run(cmds.flat()).code).toBe(63);
  });
});
