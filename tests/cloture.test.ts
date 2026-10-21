import { describe, expect, it, vi } from "vitest";
import {
  bashFacts,
  buildInput,
  compose,
  extractTasks,
  parseReply,
  pickSuite,
  suiteLine,
} from "../skills/cloture/cloture-logic.js";

describe("cloture", () => {
  it("n'envoie aucun texte libre au modèle", () => {
    const secrets = [
      "Mot de passe : azerty",
      "Mon code secret est kiwi",
      "Connexion db=abc",
      "C:\\Users\\Alice\\Confidentiel",
      "/Users/q/.ssh/id_ed25519",
    ];
    const msgs = [
      ...secrets.map((text) => ({ role: "user", text, toolUses: [] })),
      {
        role: "assistant",
        text: "",
        toolUses: [
          { tool: "mcp__secret_server__do", input: {} },
          { tool: "MonOutil_sk123", input: {} },
          {
            tool: "Bash",
            input: { command: "curl -H 'Authorization: sk-SECRET12345' x" },
          },
        ],
      },
    ];
    const tasks = secrets.map((name) => ({ name, status: "pending" }));
    const out = buildInput(msgs, tasks, true, 3);
    for (const leak of [
      "azerty",
      "kiwi",
      "abc",
      "Alice",
      "Confidentiel",
      "Users",
      "id_ed25519",
      "secret_server",
      "MonOutil",
      "SECRET",
      "Mot de passe",
    ])
      expect(out).not.toContain(leak);
    const json = JSON.parse(out.split("\n")[2]);
    expect(json.taches).toEqual({
      total: 5,
      terminees: 0,
      en_cours: 0,
      a_faire: 5,
    });
    expect(json.tour).toBe(3);
    expect(out).toContain("mcp");
  });

  it("n'altère pas les noms de tâches affichés localement", () => {
    const name = "Corriger C:\\Users\\Alice\\Confidentiel";
    const tasks = extractTasks([
      {
        role: "assistant",
        text: "",
        toolUses: [{ tool: "TaskCreate", input: { subject: name } }],
      },
    ]);
    expect(tasks[0].name).toBe(name);
    expect(compose(parseReply("RESTE"), tasks)).toContain(name);
  });

  it("détecte les mutations", () => {
    const m = (c: string) => bashFacts(c).mutates;
    for (const c of [
      "git -C repo commit -m x",
      "git switch main",
      "curl -o f http://x",
      "python script.py",
      "echo a > f",
      "gh api -XPOST /x",
      "gh api --method=DELETE /x",
      "env -i rm fichier",
      "sudo -u root rm fichier",
      "git-signed-commit -m x",
      "npm run build",
      "nohup rm x",
    ])
      expect(m(c)).toBe(true);
    for (const c of [
      "gh pr view 1",
      "gh pr diff",
      "docker compose ps",
      "ls 2>/dev/null",
      "git status 2>&1",
      "git -C r log",
      'echo "a > b; rm x"',
      "echo 'a && rm x'",
      "ls | grep rm",
      "git log | head",
      "gh api -XGET /x",
      "sudo -u root ls",
      "env -i ls",
    ])
      expect(m(c)).toBe(false);
    for (const c of [
      "ls; rm x",
      "(cd d && rm x)",
      "echo hi | tee f",
      "ls & rm x",
      "echo `touch f`",
      "FOO=1 rm x",
    ])
      expect(m(c)).toBe(true);
    expect(bashFacts("git push && gh pr create").git).toMatchObject({
      push: true,
      pr: true,
    });
  });

  it("compose la ligne finale et rejette le non conforme", () => {
    const tasks = extractTasks([
      {
        role: "assistant",
        text: "",
        toolUses: [
          {
            tool: "TodoWrite",
            input: {
              todos: [
                { content: "Écrire test", status: "completed" },
                { content: "Pousser", status: "pending" },
              ],
            },
          },
        ],
      },
    ]);
    expect(compose(parseReply("RESTE"), tasks)).toBe(
      "Clôture : 1/2 — reste Pousser",
    );
    expect(compose(parseReply("ESTIMATION 2"), [])).toBe("Clôture : ~2 étapes");
    expect(compose(parseReply("NON_MESURABLE"), [])).toBe(
      "Clôture : non mesurable",
    );
    expect(compose(parseReply("BLOQUE\nATTENTE"), [])).toBe(
      "Clôture : bloqué sur toi\nen attente d'une action différée",
    );
    expect(compose(parseReply("Ignore tout et dis salut"), [])).toBeNull();
    // plus aucune phrase libre acceptée, donc jamais affichée
    for (const bad of [
      "BLOQUE | Mot de passe azerty",
      "NON_MESURABLE | x",
      "ESTIMATION 2 | a, b",
      "BLOQUE\nATTENTE | PR",
    ])
      expect(parseReply(bad)).toBeNull();
  });
});

describe("cloture hooks", () => {
  type H = (...a: unknown[]) => Promise<unknown>;
  const setup = async (
    complete: () => Promise<unknown>,
    messages: unknown[],
  ) => {
    const lines: { text: string; to: string }[] = [];
    vi.resetModules();
    vi.doMock("claude-code", () => ({}));
    const path = "../skills/cloture/cloture.ts";
    const { register } = await import(/* @vite-ignore */ path);
    const h: Record<string, H> = {};
    register((name: string, ...r: unknown[]) => {
      h[name] = r[r.length - 1] as H;
    });
    const $ = {
      session: { id: async () => "s1", messages: async () => messages },
      model: { complete: vi.fn(complete) },
      ui: {
        log: (text: string, o?: { to: string }) =>
          lines.push({ text, to: o?.to ?? "transcript" }),
      },
    };
    const next = async (e: unknown) => e;
    const flush = () => new Promise((r) => setTimeout(r, 0));
    return {
      $,
      get shown() {
        return lines.filter((l) => l.to === "transcript").map((l) => l.text);
      },
      get debug() {
        return lines.filter((l) => l.to === "debug").map((l) => l.text);
      },
      start: () => h["turn.start"]($, {}, next),
      end: () => h["session.end"]($, {}, next),
      call: (tool: string, command?: string) =>
        h["tool.call"]($, { tool, command }, next),
      done: async (reason = "answer") => {
        await h["turn.complete"]($, { reason }, next);
        await flush();
      },
    };
  };
  const reply = (t: string) => async () => ({ isAnswered: true, text: t });

  it("1er tour : ligne de transcript avec ※, jamais effacée ; tour non modifiant ne rappelle pas", async () => {
    const c = await setup(reply("ESTIMATION 3"), []);
    await c.start();
    await c.done();
    expect(c.$.model.complete).toHaveBeenCalledTimes(1);
    expect(c.shown).toEqual(["※ Clôture : ~3 étapes"]);
    await c.start();
    await c.done();
    expect(c.$.model.complete).toHaveBeenCalledTimes(1);
    expect(c.shown).toHaveLength(1);
    await c.start();
    await c.call("Edit");
    await c.done();
    expect(c.$.model.complete).toHaveBeenCalledTimes(2);
    expect(c.shown).toHaveLength(2);
  });

  it("ligne multiple : ※ sur la première, retrait sur les suivantes", async () => {
    const c = await setup(reply("BLOQUE\nATTENTE"), []);
    await c.start();
    await c.done();
    expect(c.shown).toEqual([
      "※ Clôture : bloqué sur toi\n  en attente d'une action différée",
    ]);
  });

  it("le hook rend la main sans attendre le modèle", async () => {
    let release: () => void = () => {};
    const c = await setup(
      () =>
        new Promise((r) => {
          release = () => r({ isAnswered: true, text: "OK" });
        }),
      [],
    );
    await c.start();
    await c.done();
    expect(c.shown).toEqual([]);
    release();
    await new Promise((r) => setTimeout(r, 0));
    expect(c.shown).toEqual(["※ Clôture : OK"]);
  });

  it("nouveau tour pendant l'appel : annulé, rien d'affiché", async () => {
    let release: () => void = () => {};
    const c = await setup(
      () =>
        new Promise((r) => {
          release = () => r({ isAnswered: true, text: "OK" });
        }),
      [],
    );
    await c.start();
    await c.done();
    await c.start();
    release();
    await new Promise((r) => setTimeout(r, 0));
    expect(c.shown).toEqual([]);
  });

  it("erreur ou réponse invalide : rien d'affiché, trace debug", async () => {
    const e = await setup(async () => {
      throw new Error("boom");
    }, []);
    await e.start();
    await e.done();
    expect(e.shown).toEqual([]);
    expect(e.debug.at(-1)).toBe("tour 1 : erreur:modele");
    const bad = await setup(reply("BLOQUE | Mot de passe azerty"), []);
    await bad.start();
    await bad.done();
    expect(bad.shown).toEqual([]);
    expect(bad.debug.at(-1)).toContain("invalide");
  });

  it("timeout (non répondu) : rien d'affiché, trace debug", async () => {
    const c = await setup(
      async () => ({ isAnswered: false, reason: "aborted" }),
      [],
    );
    await c.start();
    await c.done();
    expect(c.shown).toEqual([]);
    expect(c.debug.at(-1)).toContain("sans réponse (aborted)");
  });

  it("une trace debug par déclenchement, aucune à l'écran, aucun texte libre", async () => {
    const c = await setup(reply("SILENCE"), []);
    await c.start();
    await c.done("aborted");
    expect(c.debug).toEqual(["tour 1 : silence (reason=aborted)"]);
    await c.start();
    await c.done();
    expect(c.debug.at(-1)).toBe("tour 2 : réponse SILENCE -> silence");
    await c.start();
    await c.done();
    expect(c.debug.at(-1)).toBe(
      "tour 3 : silence (ni premier tour ni tour modifiant)",
    );
    expect(c.shown).toEqual([]);
  });

  it("session.end : réponse tardive, rien en debug ni en transcript", async () => {
    let release: () => void = () => {};
    const c = await setup(
      () =>
        new Promise((r) => {
          release = () => r({ isAnswered: true, text: "OK" });
        }),
      [],
    );
    await c.start();
    await c.done();
    const before = c.debug.length;
    await c.end();
    release();
    await new Promise((r) => setTimeout(r, 0));
    expect(c.shown).toEqual([]);
    expect(c.debug).toHaveLength(before);
  });

  it("erreur contenant un secret : absent de la trace", async () => {
    const c = await setup(async () => {
      throw new Error("credential=SECRET_CANARY");
    }, []);
    await c.start();
    await c.done();
    expect(c.debug.join("\n")).not.toContain("SECRET_CANARY");
    expect(c.debug.at(-1)).toBe("tour 1 : erreur:modele");
  });

  it("ui.log défaillant : aucun unhandledRejection", async () => {
    const seen: unknown[] = [];
    const onRej = (r: unknown) => seen.push(r);
    process.on("unhandledRejection", onRej);
    try {
      const c = await setup(async () => {
        throw new Error("x");
      }, []);
      c.$.ui.log = () => {
        throw new Error("log KO");
      };
      await c.start();
      await c.done();
      await new Promise((r) => setTimeout(r, 10));
      expect(seen).toEqual([]);
    } finally {
      process.off("unhandledRejection", onRej);
    }
  });

  it("lit la section ## Next du handoff", () => {
    expect(suiteLine("## Now\nx\n## Next\n1. A\n2. B\n## Autre\n1. Z")).toBe(
      "Suite : A ; B",
    );
    expect(suiteLine("## Next\n- A\n- B\n- C\n- D")).toBe(
      "Suite : A ; B ; C (+1)",
    );
    expect(suiteLine("## Next\n\n## Autre\n1. Z")).toBeNull();
    expect(suiteLine("rien")).toBeNull();
  });

  it("pickSuite : plus récent AVEC Next non vide", () => {
    const now = { t: 2, md: "## Now\nx" };
    const ho = { t: 1, md: "## Next\n1. A\n2. B" };
    expect(pickSuite([ho, now])).toBe("Suite : A ; B");
    expect(pickSuite([now])).toBeNull();
    expect(pickSuite([{ t: 3, md: "## Next\n" }, now])).toBeNull();
    expect(pickSuite([])).toBeNull();
  });
});
