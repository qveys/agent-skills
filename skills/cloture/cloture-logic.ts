// Logique pure du mod `cloture` (sans API `claude-code`) : testable sous vitest.

export type Msg = {
  role: string;
  text: string;
  toolUses: {
    tool: string;
    input: Record<string, unknown>;
    isError?: boolean;
  }[];
  toolResults?: unknown[];
};
export type Task = { name: string; status: string };
export type Reply = { state: string; n?: number; wait?: boolean };

// ---------- confidentialité ----------
// Aucun texte libre (objectif, message utilisateur, noms de tâches, commandes, contenus) ne part vers le modèle :
// un masquage heuristique laisse passer les secrets courts (« Mot de passe : azerty »). Haiku ne reçoit que des
// compteurs et des booléens. Conséquence, limite assumée : sans liste de tâches, la ligne finale n'a ni noms d'étapes
// ni phrase libre (« ~n étapes », « non mesurable », « bloqué »). Les noms de tâches ne sont affichés que localement.
// Affichage local : seuls caractères de contrôle/format retirés (séquences ANSI, retours ligne) ; pas d'autre altération.
const clean = (s: string, max = 60) =>
  s
    .replace(/[\p{Cc}\p{Cf}]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);

// ---------- détection de tour modifiant ----------
// ponytail: parseur shell minimal (guillemets, `;` `&&` `||` `|` `&`, sous-shell/accolades/backticks) ; ignore
// heredocs, `$(…)` entre guillemets doubles, alias, fonctions. Biais volontaire : un faux positif coûte un appel
// Haiku de plus, un faux négatif masque une clôture. Évolution : vrai parseur (ex. shell-quote / tree-sitter-bash).
const KNOWN_TOOLS = new Set([
  "Bash",
  "Read",
  "Edit",
  "Write",
  "NotebookEdit",
  "MultiEdit",
  "Agent",
  "Task",
  "Glob",
  "Grep",
  "WebFetch",
  "WebSearch",
  "TodoWrite",
  "TaskCreate",
  "TaskUpdate",
  "TaskGet",
  "TaskList",
  "TaskOutput",
  "TaskStop",
  "Skill",
  "ToolSearch",
  "LSP",
  "Monitor",
  "AskUserQuestion",
  "ExitPlanMode",
  "EnterWorktree",
  "ExitWorktree",
  "SendMessage",
  "ScheduleWakeup",
  "Artifact",
]);
const WRITE_TOOLS = new Set([
  "Edit",
  "Write",
  "NotebookEdit",
  "MultiEdit",
  "Agent",
  "Task",
]);
const WRITE_CMDS = new Set([
  "rm",
  "mv",
  "cp",
  "mkdir",
  "rmdir",
  "touch",
  "tee",
  "ln",
  "chmod",
  "chown",
  "chgrp",
  "install",
  "dd",
  "truncate",
  "unlink",
  "rsync",
  "scp",
  "wget",
]);
const RUNNERS = new Set([
  "python",
  "python3",
  "node",
  "ruby",
  "perl",
  "bash",
  "sh",
  "zsh",
  "tsx",
  "deno",
  "bun",
  "npx",
  "uvx",
]);
const GIT_MUT = new Set([
  "commit",
  "push",
  "add",
  "merge",
  "rebase",
  "reset",
  "checkout",
  "switch",
  "restore",
  "mv",
  "rm",
  "apply",
  "tag",
  "cherry-pick",
  "revert",
  "clean",
  "pull",
  "am",
  "init",
  "clone",
  "stash",
  "worktree",
  "submodule",
]);
const GH_MUT: Record<string, string[]> = {
  pr: [
    "create",
    "merge",
    "edit",
    "close",
    "reopen",
    "comment",
    "review",
    "ready",
  ],
  issue: ["create", "edit", "close", "reopen", "comment", "delete"],
  release: ["create", "delete", "edit", "upload"],
  repo: ["create", "delete", "edit", "fork", "rename", "archive"],
};
const PKG_MUT = new Set([
  "install",
  "i",
  "add",
  "remove",
  "uninstall",
  "update",
  "upgrade",
  "ci",
  "publish",
  "reinstall",
  "run",
  "run-script",
  "exec",
  "dlx",
  "build",
  "test",
]);
const DOCKER_MUT = new Set([
  "rm",
  "run",
  "build",
  "push",
  "pull",
  "create",
  "start",
  "stop",
  "restart",
  "kill",
  "rmi",
  "prune",
  "up",
  "down",
  "exec",
]);
const OPTS_WITH_VALUE = new Set([
  "-C",
  "-c",
  "-R",
  "--repo",
  "--git-dir",
  "--work-tree",
  "--namespace",
  "-H",
  "--host",
  "-f",
  "--file",
  "-p",
  "--project-name",
]);

const positional = (toks: string[]) => {
  const out: string[] = [];
  for (let i = 0; i < toks.length; i++) {
    if (OPTS_WITH_VALUE.has(toks[i])) i++;
    else if (!toks[i].startsWith("-")) out.push(toks[i]);
  }
  return out;
};

type Seg = { text: string; toks: string[] };

/** Découpe en segments (`;` `&&` `||` `|` `&` newline, sous-shells, accolades, backticks) en respectant les guillemets.
 * `text` = segment avec le contenu entre guillemets masqué (pour repérer les redirections), `toks` = mots désquotés. */
function parse(cmd: string): Seg[] {
  const segs: Seg[] = [];
  let text = "";
  let tok = "";
  let has = false;
  let toks: string[] = [];
  let q = "";
  const endTok = () => {
    if (has) toks.push(tok);
    tok = "";
    has = false;
  };
  const endSeg = () => {
    endTok();
    if (toks.length) segs.push({ text, toks });
    text = "";
    toks = [];
  };
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];
    if (q) {
      if (c === q) q = "";
      else {
        if (c === "\\" && q === '"') i++;
        tok += cmd[i] ?? "";
        text += "x";
      }
    } else if (c === '"' || c === "'") {
      q = c;
      has = true;
      text += "x";
    } else if (c === "\\") {
      tok += cmd[++i] ?? "";
      has = true;
      text += "x";
    } else if (
      c === "\n" ||
      c === ";" ||
      c === "(" ||
      c === ")" ||
      c === "`" ||
      c === "{" ||
      c === "}"
    )
      endSeg();
    else if (c === "&" || c === "|") {
      if (cmd[i + 1] === c) {
        i++;
        endSeg();
      } else if (c === "&" && (cmd[i - 1] === ">" || cmd[i + 1] === ">")) {
        tok += c;
        text += c;
        has = true; // 2>&1, &>f
      } else endSeg();
    } else if (/\s/.test(c)) {
      endTok();
      text += " ";
    } else {
      tok += c;
      text += c;
      has = true;
    }
  }
  endSeg();
  return segs;
}

// Wrappers transparents -> options à valeur (les autres options sont des drapeaux simples, y compris attachées : -uroot).
const WRAPPERS: Record<string, Set<string>> = {
  sudo: new Set([
    "-u",
    "-g",
    "-h",
    "-p",
    "-C",
    "-D",
    "-R",
    "-T",
    "-U",
    "-r",
    "-t",
  ]),
  env: new Set(["-u", "-C", "-S"]),
  exec: new Set(["-a"]),
  time: new Set(["-f", "-o"]),
  command: new Set(),
  nohup: new Set(),
};
// ponytail: `env -S 'cmd'`, `sudo -s`, `command -v`, substitutions shell ($(…)) non interprétés ; faux négatifs possibles.
const words = (t: string[]) => {
  t = [...t];
  while (t.length) {
    const w = WRAPPERS[t[0]];
    if (/^\w+=/.test(t[0])) t.shift();
    else if (w) {
      t.shift();
      while (t[0]?.startsWith("-")) if (w.has(t.shift() as string)) t.shift();
    } else break;
  }
  return t;
};

export type Git = { commit: boolean; push: boolean; pr: boolean };

/** Arguments positionnels après le binaire (options globales et leurs valeurs ignorées : git -C repo commit). */
const sub = (t: string[]): string[] => positional(t.slice(1));

export function bashFacts(cmd: string): { mutates: boolean; git: Git } {
  const git: Git = { commit: false, push: false, pr: false };
  let mutates = false;
  for (const seg of parse(cmd)) {
    // redirection vers un fichier ; ignore 2>&1, >&2, /dev/null
    for (const m of seg.text.matchAll(/(?<![=\-<>])>>?\s*(&?)(\S*)/g))
      if (!m[1] && m[2] && m[2] !== "/dev/null") mutates = true;
    const t = words(seg.toks);
    const bin = (t[0] ?? "").replace(/^.*\//, "");
    const [a = "", b = ""] = sub(t);
    const flags = t.slice(1).filter((x) => x.startsWith("-"));
    if (WRITE_CMDS.has(bin)) mutates = true;
    else if (bin === "git-signed-commit") {
      // harnais GitHub : commit signé + publication
      mutates = git.commit = git.push = true;
    } else if (bin === "sed")
      mutates ||= flags.some(
        (f) => f === "--in-place" || /^-[a-zA-Z]*i/.test(f),
      );
    else if (bin === "curl")
      mutates ||= flags.some((f) =>
        /^(-o|-O|-J|--output|--remote-name)/.test(f),
      );
    else if (RUNNERS.has(bin))
      mutates ||=
        !flags.every((f) => /^(-v|-V|-h|--version|--help)$/.test(f)) ||
        sub(t).length > 0;
    else if (bin === "git") {
      if (GIT_MUT.has(a)) mutates = true;
      if (a === "commit") git.commit = true;
      if (a === "push") git.push = true;
    } else if (bin === "gh") {
      if (GH_MUT[a]?.includes(b)) mutates = true;
      if (a === "pr" && b === "create") git.pr = true;
      if (a === "api") {
        const method = t
          .map((x, i) =>
            /^(-X|--method)$/.test(x)
              ? t[i + 1]
              : /^-X(.+)$|^--method=(.+)$/.exec(x)?.slice(1).find(Boolean),
          )
          .find(Boolean);
        mutates ||=
          (method !== undefined && !/^get$/i.test(method)) ||
          flags.some((f) => /^(-[fF]|--field|--raw-field|--input)/.test(f));
      }
    } else if (
      ["npm", "pnpm", "yarn", "bun", "pip", "pip3", "brew", "cargo"].includes(
        bin,
      )
    )
      mutates ||= PKG_MUT.has(a);
    else if (bin === "docker" || bin === "docker-compose") {
      const s = bin === "docker" && a === "compose" ? b : a;
      mutates ||= DOCKER_MUT.has(s);
    }
  }
  return { mutates, git };
}

export const isModifying = (tool: string, command?: unknown) =>
  WRITE_TOOLS.has(tool) ||
  (tool === "Bash" && bashFacts(String(command ?? "")).mutates);

// ---------- liste de tâches (TodoWrite / TaskCreate / TaskUpdate) ----------
// ponytail: TodoWrite écrase la liste ; seules les entrées encore présentes comptent.
type TodoItem = { content?: string; subject?: string; status?: string };
// ponytail: TaskUpdate adresse par taskId = rang de création (1-based), comme les ids séquentiels natifs.
export function extractTasks(msgs: Msg[]): Task[] {
  let tasks: Task[] = [];
  for (const u of msgs.flatMap((m) => m.toolUses)) {
    const i = u.input;
    if (u.tool === "TodoWrite" && Array.isArray(i.todos))
      tasks = (i.todos as TodoItem[]).map((t) => ({
        name: clean(String(t?.content ?? t?.subject ?? "")),
        status: String(t?.status ?? "pending"),
      }));
    else if (u.tool === "TaskCreate")
      tasks.push({ name: clean(String(i.subject ?? "")), status: "pending" });
    else if (u.tool === "TaskUpdate") {
      const t = tasks[Number(i.taskId) - 1];
      if (t) {
        if (typeof i.status === "string") t.status = i.status;
        if (typeof i.subject === "string") t.name = clean(i.subject);
      }
    }
  }
  return tasks.filter((t) => t.name && t.status !== "deleted");
}

// ---------- entrée du modèle : métadonnées non textuelles uniquement ----------
export function buildInput(
  msgs: Msg[],
  tasks: Task[],
  isTouched: boolean,
  turn = 0,
): string {
  const tools: Record<string, { n: number; err: number }> = {};
  const git: Git = { commit: false, push: false, pr: false };
  for (const u of msgs.flatMap((m) => m.toolUses)) {
    let k: string;
    if (KNOWN_TOOLS.has(u.tool)) k = u.tool;
    else if (u.tool.startsWith("mcp__")) k = "mcp";
    else k = "autre"; // jamais de nom libre vers le modèle
    tools[k] = tools[k] ?? { n: 0, err: 0 };
    const s = tools[k];
    s.n++;
    if (u.isError) s.err++;
    else if (u.tool === "Bash") {
      const f = bashFacts(String(u.input.command ?? "")).git;
      git.commit ||= f.commit;
      git.push ||= f.push;
      git.pr ||= f.pr;
    }
  }
  const count = (st: string) => tasks.filter((t) => t.status === st).length;
  const data = {
    tour: turn,
    tour_modifiant: isTouched,
    outils: tools,
    git_reussi: git,
    taches: {
      total: tasks.length,
      terminees: count("completed"),
      en_cours: count("in_progress"),
      a_faire: tasks.length - count("completed") - count("in_progress"),
    },
  };
  return `Métadonnées de la session (compteurs uniquement) :\n<donnees_non_fiables>\n${JSON.stringify(data)}\n</donnees_non_fiables>`;
}

// ---------- réponse du modèle : validation stricte puis composition locale ----------
// Aucune phrase libre : seuls l'état, un nombre et un drapeau ATTENTE sont acceptés ; les textes affichés sont prédéfinis.
const REPLY =
  /^(SILENCE|OK|RESTE|ESTIMATION [1-9]\d?|NON_MESURABLE|BLOQUE)(\nATTENTE)?$/;

export function parseReply(raw: string): Reply | null {
  const m = REPLY.exec(raw.trim());
  if (!m) return null;
  const [word, n] = m[1].split(" ");
  return { state: word, n: n ? Number(n) : undefined, wait: !!m[2] };
}

/** Ligne finale composée localement ; null = rien à afficher. */
export function compose(r: Reply | null, tasks: Task[]): string | null {
  if (!r || r.state === "SILENCE") return null;
  const open = tasks.filter((t) => t.status !== "completed");
  let main: string | null = null;
  if (tasks.length && (r.state === "OK" || r.state === "RESTE")) {
    const names =
      open
        .slice(0, 4)
        .map((t) => t.name)
        .join(", ") + (open.length > 4 ? ` (+${open.length - 4})` : "");
    main = open.length
      ? `Clôture : ${tasks.length - open.length}/${tasks.length} — reste ${names}`
      : "Clôture : OK";
  } else if (!tasks.length && r.state === "OK") main = "Clôture : OK";
  else if (!tasks.length && r.state === "ESTIMATION" && r.n)
    main = `Clôture : ~${r.n} étapes`;
  else if (r.state === "NON_MESURABLE") main = "Clôture : non mesurable";
  else if (r.state === "BLOQUE") main = "Clôture : bloqué sur toi";
  if (!main) return null;
  return (r.wait ? `${main}\nen attente d'une action différée` : main).slice(
    0,
    400,
  );
}

/** Ligne « Suite : … » depuis la section `## Next` d'un handoff markdown ; null si absente ou vide. Affichage local seulement. */
export function suiteLine(md: string): string | null {
  const body = md.match(/^## Next[^\n]*\n([\s\S]*?)(?=^## |(?![\s\S]))/m)?.[1] ?? ''
  const items = body.split('\n').map(l => l.match(/^\s*(?:\d+[.)]|[-*])\s+(.+)/)?.[1]).filter(Boolean).map(l => clean(l as string, 80))
  if (!items.length) return null
  return `Suite : ${items.slice(0, 3).join(' ; ')}${items.length > 3 ? ` (+${items.length - 3})` : ''}`.slice(0, 400)
}

/** Suite du handoff le plus récent qui contient un `## Next` non vide (now.md sans Next est ignoré) ; null sinon. */
export function pickSuite(files: { t: number; md: string }[]): string | null {
  for (const f of [...files].sort((a, b) => b.t - a.t)) {
    const l = suiteLine(f.md)
    if (l) return l
  }
  return null
}
