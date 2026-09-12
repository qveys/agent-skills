#!/usr/bin/env python3
"""Deterministic collector for the /learn skill.

Walks coding-agent homes (Claude Code, Grok Build, Codex, Cursor), keeps the
sessions a human sat at, and writes a compact run directory:

  <run>/manifest.json
  <run>/sessions/NNNN-<id>.json
  <run>/surfaces.json
  <run>/usage.json
  <run>/phrases.json
  <run>/decisions.jsonl   (copy of prior decisions, if any)

Stdlib only. Never prints or copies config values other than names.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

TURN_CAP = 2000
USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S)
SECRET_RES = [
    re.compile(r"\b(xai|sk|ghp|gho|ghu|ghs|glpat|npm)[-_](?=(?:[A-Za-z_\-]*\d){3})[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[abpsr]-\d[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-./+=]{20,}"),
    re.compile(r"(?i)\b(token|api[_-]?key|secret|password|passwd)\b\s*[:=]\s*['\"]?(?=[A-Za-z0-9_\-./+=]*\d)[A-Za-z0-9_\-./+=]{16,}"),
    re.compile(r"\b[a-f0-9]{64,}\b"),
]
SLASH_RE = re.compile(r"(?<![\w/~.])/([a-z][a-z0-9-]{1,63})\b(?!/)")
SKILL_PATH_RE = re.compile(r"[/\\]skills[/\\]([^/\\]+)[/\\]SKILL\.md$")
WORD_RE = re.compile(r"\s+")
SUBAGENT_KINDS = {"subagent", "subagent_resume", "subagent_fork"}
DEFAULT_DROP_PATTERNS = [
    r"^the user invoked `/feedback`",
    r"^Review this change for security vulnerabilities",
    r"(?i)^r[ée]ponds uniquement:\s*ok",
]
SLASH_STOP = {
    "tmp", "usr", "bin", "etc", "var", "dev", "opt", "home", "users", "private",
    "api", "v1", "v2", "src", "lib", "test", "tests", "docs", "help", "quit",
    "exit", "clear", "model", "compact", "rewind", "rename", "workflows",
    "workflow", "feedback", "btw", "loop", "resume", "status", "config",
    "init", "login", "logout", "mcp", "plugins", "skills", "memory", "diff",
    "review", "commit", "pr", "cost", "doctor", "theme", "vim", "terminal",
}
DEFAULT_EXCLUDE_SUBSTR = ["grok-e2e", "claude-e2e"]
MAP_TOKENS_PER_SESSION = {10: 110_000, 1: 250_000}
REDUCER_TOKENS = 1_300_000
VERIFIER_TOKENS = 800_000
REPORT_TOKENS = 2_500_000
FIXED_AGENTS = 4
FAN = 10
HARNESSES = ("grok", "claude", "codex", "cursor")


def estimate(n: int, batch: int = 10) -> dict:
    if n <= 0:
        return {"sessions": 0, "agents": 0, "mappers": 0, "reducers": 0, "tokens": 0, "tokens_m": 0.0, "minutes": [0, 0]}
    mappers = -(-n // batch)
    reducers, level = 0, mappers
    while True:
        groups = -(-level // FAN)
        reducers += groups
        level = groups
        if groups <= 1:
            break
    per_session = MAP_TOKENS_PER_SESSION.get(batch, MAP_TOKENS_PER_SESSION[10] * 10 // batch)
    tokens = n * per_session + reducers * REDUCER_TOKENS + 3 * VERIFIER_TOKENS + REPORT_TOKENS
    mid = 30 + n // 6
    return {"sessions": n, "agents": mappers + reducers + FIXED_AGENTS, "mappers": mappers, "reducers": reducers,
            "tokens": tokens, "tokens_m": round(tokens / 1e6, 1), "minutes": [max(15, mid - 15), mid + 20]}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_time(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def redact(text: str) -> str:
    for rx in SECRET_RES:
        text = rx.sub(lambda m: m.group(0)[:8] + "…[redacted]", text)
    return text


def frontmatter(path: str) -> dict:
    out = {"name": os.path.basename(os.path.dirname(path)), "description": ""}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return out
    if not head.startswith("---"):
        return out
    body = head.split("---", 2)
    if len(body) < 3:
        return out
    fm = body[1]
    m = re.search(r"^name:\s*(.+)$", fm, re.M)
    if m:
        out["name"] = m.group(1).strip().strip("'\"")
    m = re.search(r"^description:\s*(.*)$", fm, re.M)
    if m:
        desc = m.group(1).strip()
        if desc in (">", ">-", "|", "|-", ""):
            lines = []
            after = fm[m.end():].splitlines()
            for line in after:
                if line.startswith((" ", "\t")):
                    lines.append(line.strip())
                elif line.strip() == "":
                    continue
                else:
                    break
            desc = " ".join(lines)
        out["description"] = desc.strip("'\"")[:300]
    return out


def toml_string_array(text: str, table: str, key: str) -> list[str] | None:
    m = re.search(r"^\[" + re.escape(table) + r"\]\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^\[", rest, re.M)
    if nxt:
        rest = rest[: nxt.start()]
    km = re.search(r"^" + re.escape(key) + r"\s*=\s*\[", rest, re.M)
    if not km:
        return None
    depth, i, start = 0, km.end() - 1, km.end() - 1
    while i < len(rest):
        if rest[i] == "[":
            depth += 1
        elif rest[i] == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return re.findall(r'"([^"]+)"', rest[start : i + 1])


def toml_subtables(text: str, table: str) -> list[str]:
    names = []
    for m in re.finditer(r"^\[" + re.escape(table) + r"\.([^\].]+)\]", text, re.M):
        if m.group(1) not in names:
            names.append(m.group(1))
    return names


def git_tracked(path: str, root: str) -> bool | None:
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", "--", path],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0


def under(path: str, base: str) -> bool:
    path, base = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(base))
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def default_exclude_cwd() -> list[str]:
    return sorted({
        os.path.normcase(os.path.normpath(p))
        for p in (tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir()), "/tmp", "/private/tmp", "/var/folders")
    })


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") in ("text", "input_text", "output_text") or "text" in c:
                    parts.append(c.get("text") or "")
                elif isinstance(c.get("content"), str):
                    parts.append(c["content"])
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    if isinstance(content, dict):
        return text_of(content.get("text") or content.get("content") or "")
    return ""


def human_queries(text: str) -> list[str]:
    found = [m.strip() for m in USER_QUERY_RE.findall(text)]
    if found:
        return [t for t in found if t]
    t = text.strip()
    if not t:
        return []
    if "<user_info>" in t or "<system-reminder>" in t:
        return []
    return [t]


def cap_turn(t: str) -> str:
    r = redact(t)
    return r[:TURN_CAP] + ("…" if len(r) > TURN_CAP else "")


def note_skill_path(path: str, skill_loads: collections.Counter, skill_load_paths: dict, paths_touched: collections.Counter) -> None:
    sm = SKILL_PATH_RE.search(path)
    if sm:
        skill_loads[sm.group(1)] += 1
        skill_load_paths.setdefault(sm.group(1), path)
    else:
        paths_touched[path] += 1


def mcp_from_tool(name: str) -> str | None:
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    if "__" in name and not name.startswith("mcp"):
        return name.split("__", 1)[0]
    return None


def top_dirs(paths_touched: collections.Counter, base: str) -> dict:
    dirs: collections.Counter = collections.Counter()
    for p, n in paths_touched.items():
        rel = p
        if base and under(p, base):
            rel = os.path.relpath(p, base)
        parts = [x for x in re.split(r"[\\/]+", rel) if x]
        key = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if parts else rel)
        dirs[key] += n
    return dict(dirs.most_common(10))


def record(id_: str, harness: str, cwd: str, git_root: str, title: str, created_at, updated_at,
           model, turns, tools, skill_loads, skill_load_paths, slash, mcp_tools, paths_touched,
           subagents, workflow_launches, dropped_turns, parse_errors, trace_path, extra=None) -> dict | None:
    if not turns:
        return None
    real_tools = sum(n for name, n in tools.items() if name not in ("send_feedback",))
    smoke_test = real_tools == 0 and all(len(t.split()) < 3 for t in turns)
    rec = {
        "id": id_,
        "harness": harness,
        "cwd": cwd,
        "git_root": git_root,
        "branch": (extra or {}).get("branch") or "",
        "title": title,
        "session_kind": (extra or {}).get("session_kind"),
        "created_at": created_at,
        "updated_at": updated_at,
        "model": model,
        "human_turns": len(turns),
        "dropped_turns": dropped_turns,
        "parse_errors": parse_errors,
        "smoke_test": smoke_test,
        "turns": [cap_turn(t) for t in turns],
        "slash_commands": dict(slash.most_common()),
        "skills_loaded": dict(skill_loads.most_common()),
        "skill_load_paths": skill_load_paths,
        "mcp_servers_used": dict(mcp_tools.most_common()),
        "tools": dict(tools.most_common(25)),
        "subagent_spawns": subagents,
        "workflow_launches": workflow_launches,
        "top_dirs_touched": top_dirs(paths_touched, git_root or cwd),
        "trace_path": trace_path,
    }
    return rec


def iter_jsonl(path: str):
    parse_errors = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                parse_errors += 1
                continue
            if not isinstance(r, dict):
                parse_errors += 1
                continue
            yield r, parse_errors


# ---------------------------------------------------------------- grok


def scan_grok(sess_dir: str, summary: dict, drop_patterns: list[re.Pattern]) -> dict | None:
    chat = os.path.join(sess_dir, "chat_history.jsonl")
    if not os.path.isfile(chat):
        return None
    turns: list[str] = []
    tools = collections.Counter()
    mcp_tools = collections.Counter()
    skill_loads = collections.Counter()
    skill_load_paths: dict[str, str] = {}
    slash = collections.Counter()
    paths_touched = collections.Counter()
    subagents = 0
    workflow_launches = 0
    dropped_turns = 0
    parse_errors = 0
    for r, parse_errors in iter_jsonl(chat):
        t = r.get("type")
        if t == "user" and not r.get("synthetic_reason"):
            for q in human_queries(text_of(r.get("content"))):
                if any(p.search(q) for p in drop_patterns):
                    dropped_turns += 1
                    continue
                turns.append(q)
                for m in SLASH_RE.findall(q):
                    slash[m] += 1
        elif t == "assistant":
            for call in r.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = call.get("name") or ""
                tools[name] += 1
                try:
                    a = json.loads(call.get("arguments") or "{}")
                except ValueError:
                    a = {}
                if not isinstance(a, dict):
                    a = {}
                if name == "use_tool":
                    tn = a.get("tool_name") or ""
                    mcp_tools[tn.split("__", 1)[0] if "__" in tn else tn] += 1
                elif name == "spawn_subagent":
                    subagents += 1
                elif name == "workflow":
                    workflow_launches += 1
                target = a.get("target_file") or a.get("file_path") or a.get("path")
                if isinstance(target, str) and target:
                    note_skill_path(target, skill_loads, skill_load_paths, paths_touched)
    info = summary.get("info") or {}
    cwd = info.get("cwd") or ""
    return record(
        info.get("id") or os.path.basename(sess_dir), "grok", cwd,
        summary.get("git_root_dir") or "", summary.get("generated_title") or "",
        summary.get("created_at"), summary.get("updated_at"), summary.get("current_model_id"),
        turns, tools, skill_loads, skill_load_paths, slash, mcp_tools, paths_touched,
        subagents, workflow_launches, dropped_turns, parse_errors, chat,
        extra={"session_kind": summary.get("session_kind"), "branch": summary.get("head_branch") or ""},
    )


def collect_grok(home: str, args, cutoff, exclude_cwd, drop_patterns, only_ids) -> tuple[int, collections.Counter, list]:
    sessions_root = os.path.join(home, "sessions")
    seen = 0
    dropped: collections.Counter = collections.Counter()
    kept: list[dict] = []
    if not os.path.isdir(sessions_root):
        return seen, dropped, kept
    for enc_cwd in sorted(os.listdir(sessions_root)):
        cwd_dir = os.path.join(sessions_root, enc_cwd)
        if not os.path.isdir(cwd_dir):
            continue
        for sid in sorted(os.listdir(cwd_dir)):
            sess_dir = os.path.join(cwd_dir, sid)
            summ_path = os.path.join(sess_dir, "summary.json")
            if not os.path.isdir(sess_dir):
                continue
            seen += 1
            if not os.path.isfile(summ_path):
                dropped["no_summary"] += 1
                continue
            if only_ids and sid not in only_ids:
                dropped["not_in_session_id_list"] += 1
                continue
            try:
                summary = read_json(summ_path)
            except (OSError, ValueError):
                dropped["summary_unreadable"] += 1
                continue
            if not isinstance(summary, dict):
                dropped["summary_unreadable"] += 1
                continue
            kind = summary.get("session_kind")
            if kind in SUBAGENT_KINDS and not args.include_subagents:
                dropped["subagent"] += 1
                continue
            if kind == "headless" and not args.include_headless:
                dropped["headless"] += 1
                continue
            cwd = (summary.get("info") or {}).get("cwd") or urllib.parse.unquote(enc_cwd)
            if any(under(cwd, p) for p in exclude_cwd) or any(s in cwd for s in DEFAULT_EXCLUDE_SUBSTR):
                dropped["excluded_cwd"] += 1
                continue
            if args.cwd and not any(under(cwd, p) for p in args.cwd):
                dropped["outside_cwd"] += 1
                continue
            if cutoff is not None:
                ts = parse_time(summary.get("updated_at"))
                if ts is None or ts < cutoff:
                    dropped["older_than_window"] += 1
                    continue
            rec = scan_grok(sess_dir, summary, drop_patterns)
            if rec is None or rec["human_turns"] < args.min_turns:
                dropped["no_human_turns"] += 1
                continue
            if rec["smoke_test"]:
                dropped["smoke_test"] += 1
                continue
            kept.append(rec)
    return seen, dropped, kept


# ---------------------------------------------------------------- claude / cursor jsonl


def scan_claude_like(path: str, harness: str, drop_patterns, include_sidechains: bool) -> dict | None:
    turns: list[str] = []
    tools = collections.Counter()
    mcp_tools = collections.Counter()
    skill_loads = collections.Counter()
    skill_load_paths: dict[str, str] = {}
    slash = collections.Counter()
    paths_touched = collections.Counter()
    subagents = 0
    dropped_turns = 0
    parse_errors = 0
    cwd = ""
    git_root = ""
    branch = ""
    title = ""
    created_at = None
    updated_at = None
    sid = os.path.basename(path).removesuffix(".jsonl")
    for r, parse_errors in iter_jsonl(path):
        if isinstance(r.get("cwd"), str) and r["cwd"] and not cwd:
            cwd = r["cwd"]
        if isinstance(r.get("gitBranch"), str) and r["gitBranch"]:
            branch = r["gitBranch"]
        if isinstance(r.get("sessionId"), str) and r["sessionId"]:
            sid = r["sessionId"]
        ts = r.get("timestamp")
        if isinstance(ts, str):
            created_at = created_at or ts
            updated_at = ts
        rtype = r.get("type")
        if rtype in ("ai-title", "custom-title") and isinstance(r.get("aiTitle") or r.get("customTitle"), str):
            title = r.get("aiTitle") or r.get("customTitle")
        if r.get("isSidechain") and not include_sidechains:
            continue
        if any(r.get(flag) for flag in ("isMeta", "isCompactSummary", "isVirtual")):
            continue
        msg = r.get("message") if isinstance(r.get("message"), dict) else None
        if rtype == "user" and msg:
            for q in human_queries(text_of(msg.get("content"))):
                if any(p.search(q) for p in drop_patterns):
                    dropped_turns += 1
                    continue
                turns.append(q)
                for m in SLASH_RE.findall(q):
                    slash[m] += 1
        elif rtype == "assistant" and msg:
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            for part in blocks:
                if not isinstance(part, dict) or part.get("type") != "tool_use":
                    continue
                name = part.get("name") or ""
                tools[name] += 1
                inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                if name in ("Skill", "skill") and isinstance(inp.get("skill"), str):
                    skill_loads[inp["skill"]] += 1
                if name in ("Task", "TaskCreate", "spawn_subagent"):
                    subagents += 1
                mcp = mcp_from_tool(name)
                if mcp:
                    mcp_tools[mcp] += 1
                target = inp.get("file_path") or inp.get("target_file") or inp.get("path")
                if isinstance(target, str) and target:
                    note_skill_path(target, skill_loads, skill_load_paths, paths_touched)
    if not title and turns:
        title = turns[0][:80]
    git_root = cwd
    return record(sid, harness, cwd, git_root, title, created_at, updated_at, None,
                  turns, tools, skill_loads, skill_load_paths, slash, mcp_tools, paths_touched,
                  subagents, 0, dropped_turns, parse_errors, path, extra={"branch": branch})


def keep_filters(rec: dict | None, args, cutoff, exclude_cwd, only_ids, dropped: collections.Counter) -> dict | None:
    if rec is None:
        dropped["no_human_turns"] += 1
        return None
    if only_ids and rec["id"] not in only_ids:
        dropped["not_in_session_id_list"] += 1
        return None
    cwd = rec.get("cwd") or ""
    if cwd and (any(under(cwd, p) for p in exclude_cwd) or any(s in cwd for s in DEFAULT_EXCLUDE_SUBSTR)):
        dropped["excluded_cwd"] += 1
        return None
    if args.cwd and cwd and not any(under(cwd, p) for p in args.cwd):
        dropped["outside_cwd"] += 1
        return None
    if cutoff is not None:
        ts = parse_time(rec.get("updated_at"))
        if ts is None:
            try:
                ts = dt.datetime.fromtimestamp(os.path.getmtime(rec["trace_path"]), dt.timezone.utc)
            except OSError:
                ts = None
        if ts is None or ts < cutoff:
            dropped["older_than_window"] += 1
            return None
    if rec["human_turns"] < args.min_turns:
        dropped["no_human_turns"] += 1
        return None
    if rec["smoke_test"]:
        dropped["smoke_test"] += 1
        return None
    return rec


def collect_claude(home: str, args, cutoff, exclude_cwd, drop_patterns, only_ids) -> tuple[int, collections.Counter, list]:
    projects = os.path.join(home, "projects")
    seen = 0
    dropped: collections.Counter = collections.Counter()
    kept: list[dict] = []
    if not os.path.isdir(projects):
        return seen, dropped, kept
    for dirpath, dirnames, filenames in os.walk(projects):
        dirnames[:] = [d for d in dirnames if d not in (".git",)]
        if os.path.basename(dirpath) in ("subagents", "agent-transcripts") and not args.include_subagents:
            dirnames[:] = []
            continue
        for fn in filenames:
            if not fn.endswith(".jsonl"):
                continue
            if fn.startswith("agent-") and not args.include_subagents:
                dropped["subagent"] += 1
                seen += 1
                continue
            path = os.path.join(dirpath, fn)
            seen += 1
            rec = scan_claude_like(path, "claude", drop_patterns, args.include_subagents)
            rec = keep_filters(rec, args, cutoff, exclude_cwd, only_ids, dropped)
            if rec:
                kept.append(rec)
    return seen, dropped, kept


def collect_cursor(home: str, args, cutoff, exclude_cwd, drop_patterns, only_ids) -> tuple[int, collections.Counter, list]:
    seen = 0
    dropped: collections.Counter = collections.Counter()
    kept: list[dict] = []
    roots = [
        os.path.join(home, "projects"),
        os.path.join(home, "cli-config"),
    ]
    found = False
    for root in roots:
        if not os.path.isdir(root):
            continue
        found = True
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, fn)
                seen += 1
                rec = scan_claude_like(path, "cursor", drop_patterns, args.include_subagents)
                rec = keep_filters(rec, args, cutoff, exclude_cwd, only_ids, dropped)
                if rec:
                    kept.append(rec)
    if not found:
        return 0, dropped, kept
    return seen, dropped, kept


# ---------------------------------------------------------------- codex


def scan_codex(path: str, drop_patterns) -> dict | None:
    turns: list[str] = []
    tools = collections.Counter()
    mcp_tools = collections.Counter()
    skill_loads = collections.Counter()
    skill_load_paths: dict[str, str] = {}
    slash = collections.Counter()
    paths_touched = collections.Counter()
    subagents = 0
    dropped_turns = 0
    parse_errors = 0
    cwd = ""
    sid = os.path.basename(path).split("rollout-")[-1].removesuffix(".jsonl").removesuffix(".jsonl.zst")
    created_at = None
    updated_at = None
    title = ""
    for r, parse_errors in iter_jsonl(path):
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        rtype = r.get("type")
        if rtype == "session_meta":
            if isinstance(payload.get("id"), str):
                sid = payload["id"]
            if isinstance(payload.get("cwd"), str):
                cwd = payload["cwd"]
            ts = payload.get("timestamp") or r.get("timestamp")
            if isinstance(ts, str):
                created_at = created_at or ts
        if rtype == "response_item":
            role = payload.get("role") or (payload.get("type") if payload.get("type") in ("user", "assistant") else None)
            if role == "user" or (payload.get("type") == "message" and payload.get("role") == "user"):
                for q in human_queries(text_of(payload.get("content"))):
                    if any(p.search(q) for p in drop_patterns):
                        dropped_turns += 1
                        continue
                    turns.append(q)
                    for m in SLASH_RE.findall(q):
                        slash[m] += 1
            name = payload.get("name") or ""
            if payload.get("type") in ("function_call", "custom_tool_call") and name:
                tools[name] += 1
                args_raw = payload.get("arguments") or "{}"
                try:
                    a = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else {})
                except ValueError:
                    a = {}
                if not isinstance(a, dict):
                    a = {}
                target = a.get("path") or a.get("file_path") or a.get("target_file") or a.get("cmd")
                if isinstance(target, str) and (target.startswith("/") or target.endswith("SKILL.md")):
                    note_skill_path(target, skill_loads, skill_load_paths, paths_touched)
                mcp = mcp_from_tool(name)
                if mcp:
                    mcp_tools[mcp] += 1
        ts = r.get("timestamp") or payload.get("timestamp")
        if isinstance(ts, str):
            created_at = created_at or ts
            updated_at = ts
    if not title and turns:
        title = turns[0][:80]
    return record(sid, "codex", cwd, cwd, title, created_at, updated_at, None,
                  turns, tools, skill_loads, skill_load_paths, slash, mcp_tools, paths_touched,
                  subagents, 0, dropped_turns, parse_errors, path)


def collect_codex(home: str, args, cutoff, exclude_cwd, drop_patterns, only_ids) -> tuple[int, collections.Counter, list]:
    sessions = os.path.join(home, "sessions")
    seen = 0
    dropped: collections.Counter = collections.Counter()
    kept: list[dict] = []
    if not os.path.isdir(sessions):
        return seen, dropped, kept
    for dirpath, _, filenames in os.walk(sessions):
        for fn in filenames:
            if not (fn.endswith(".jsonl") or fn.endswith(".jsonl.zst")):
                continue
            if fn.endswith(".jsonl.zst"):
                dropped["compressed_skipped"] += 1
                seen += 1
                continue
            path = os.path.join(dirpath, fn)
            seen += 1
            rec = scan_codex(path, drop_patterns)
            rec = keep_filters(rec, args, cutoff, exclude_cwd, only_ids, dropped)
            if rec:
                kept.append(rec)
    return seen, dropped, kept


# ---------------------------------------------------------------- surfaces


def project_skill_dirs(cwd: str, git_root: str) -> list[tuple[str, str]]:
    if not cwd:
        return []
    cwd = os.path.normpath(cwd)
    if not git_root or not under(cwd, git_root):
        dirs = [cwd]
    else:
        dirs = []
        d, top = cwd, os.path.normpath(git_root)
        while True:
            dirs.append(d)
            parent = os.path.dirname(d)
            if os.path.normcase(d) == os.path.normcase(top) or parent == d:
                break
            d = parent
    out = []
    for d in dirs:
        for rel in (os.path.join(".claude", "skills"), os.path.join(".grok", "skills"),
                    os.path.join(".agents", "skills"), "skills"):
            out.append((os.path.join(d, rel), d))
    return out


def add_mcp_from_json(path: str, label: str, mcp_sources: dict) -> None:
    if not os.path.isfile(path):
        return
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    if isinstance(servers, dict):
        for n in servers:
            mcp_sources.setdefault(n, []).append(label)


def collect_surfaces(homes: dict, sessions: list[dict]) -> dict:
    skills = []

    def add_skills(glob_dir: str, source: str, extra: dict | None = None):
        if not os.path.isdir(glob_dir):
            return
        for d in sorted(os.listdir(glob_dir)):
            p = os.path.join(glob_dir, d, "SKILL.md")
            if os.path.isfile(p):
                rec = {"path": p, "source": source, **frontmatter(p)}
                if extra:
                    rec.update(extra)
                skills.append(rec)

    user_dirs: list[tuple[str, str]] = []
    for key, rel in (("agents", "skills"), ("claude", "skills"), ("grok", "skills"),
                     ("codex", "skills"), ("cursor", "skills")):
        h = homes.get(key) or ""
        if h:
            user_dirs.append((os.path.join(h, rel), key))
    seen_user = set()
    for d, src in user_dirs:
        real = os.path.realpath(d) if os.path.isdir(d) else d
        if real in seen_user:
            continue
        seen_user.add(real)
        add_skills(d, "user", {"harness": src})

    preferred = None
    for d, _src in user_dirs:
        if os.path.isdir(d):
            preferred = d
            break
    if preferred is None:
        preferred = os.path.join(homes.get("agents") or os.path.expanduser("~/.agents"), "skills")

    skill_dirs: dict[str, tuple[str, str]] = {}
    user_reals = {os.path.realpath(d) for d, _ in user_dirs if os.path.isdir(d)}
    for s in sessions:
        for d, owner in project_skill_dirs(s.get("cwd") or "", s.get("git_root") or ""):
            if os.path.isdir(d) and os.path.realpath(d) not in user_reals:
                skill_dirs.setdefault(os.path.realpath(d), (d, owner))
    project_roots = sorted({owner for _, owner in skill_dirs.values()})
    project_seen: dict[str, dict] = {}
    for d, owner in sorted(skill_dirs.values()):
        before = len(skills)
        add_skills(d, "project", {"project_roots": [owner]})
        for rec in skills[before:]:
            first = project_seen.get(rec["name"])
            if first is None:
                rec["git_tracked"] = git_tracked(rec["path"], owner)
                project_seen[rec["name"]] = rec
            elif owner not in first["project_roots"]:
                first["project_roots"].append(owner)
        del skills[before:]
    skills.extend(project_seen.values())

    grok_home = homes.get("grok") or ""
    if grok_home:
        add_skills(os.path.join(grok_home, "bundled", "skills"), "bundled", {"harness": "grok"})

    config_text = ""
    cfg = os.path.join(grok_home, "config.toml") if grok_home else ""
    if cfg and os.path.isfile(cfg):
        with open(cfg, encoding="utf-8", errors="replace") as f:
            config_text = f.read()
    enabled = toml_string_array(config_text, "plugins", "enabled") or []
    disabled = toml_string_array(config_text, "plugins", "disabled") or []
    skills_disabled = toml_string_array(config_text, "skills", "disabled") or []

    plugins = []
    plugin_root = os.path.join(grok_home, "installed-plugins") if grok_home else ""
    installed_names: set[str] = set()
    registry_names: dict[str, list[str]] = {}
    if plugin_root and os.path.isdir(plugin_root):
        reg_path = os.path.join(plugin_root, "registry.json")
        if os.path.isfile(reg_path):
            try:
                for repo in (read_json(reg_path).get("repos") or {}).values():
                    p = os.path.realpath(repo.get("path") or "")
                    if p:
                        registry_names[p] = sorted((repo.get("plugins") or {}).keys())
            except (OSError, ValueError, AttributeError):
                pass
        for d in sorted(os.listdir(plugin_root)):
            full = os.path.join(plugin_root, d)
            if not os.path.isdir(full):
                continue
            names = registry_names.get(os.path.realpath(full)) or [re.sub(r"-[0-9a-f]{8}$", "", d)]
            name = names[0]
            installed_names.update(names)
            state = "enabled" if name in enabled else "disabled" if name in disabled else "unlisted"
            before = len(skills)
            add_skills(os.path.join(full, "skills"), "plugin", {"plugin": name, "plugin_state": state, "harness": "grok"})
            plugins.append({
                "name": name, "dir": full, "state": state, "skill_count": len(skills) - before,
                "has_hooks": os.path.isdir(os.path.join(full, "hooks")),
                "has_commands": os.path.isdir(os.path.join(full, "commands")),
                "harness": "grok",
            })
    enabled_missing = sorted(n for n in enabled if n not in installed_names)
    disabled_missing = sorted(n for n in disabled if n not in installed_names)

    mcp_sources: dict[str, list[str]] = {}
    for n in toml_subtables(config_text, "mcp_servers"):
        mcp_sources.setdefault(n, []).append("grok:config.toml")
    if grok_home:
        add_mcp_from_json(os.path.join(grok_home, "settings.json"), "grok:settings.json", mcp_sources)
    claude_home = homes.get("claude") or ""
    if claude_home:
        add_mcp_from_json(os.path.join(claude_home, "settings.json"), "claude:settings.json", mcp_sources)
        add_mcp_from_json(os.path.join(os.path.dirname(claude_home), ".claude.json"), "claude:.claude.json", mcp_sources)
        add_mcp_from_json(os.path.expanduser("~/.claude.json"), "claude:~/.claude.json", mcp_sources)
    codex_home = homes.get("codex") or ""
    if codex_home:
        add_mcp_from_json(os.path.join(codex_home, "config.toml"), "codex:config.toml", mcp_sources)
        ct = ""
        cpath = os.path.join(codex_home, "config.toml")
        if os.path.isfile(cpath):
            with open(cpath, encoding="utf-8", errors="replace") as f:
                ct = f.read()
            for n in toml_subtables(ct, "mcp_servers"):
                mcp_sources.setdefault(n, []).append("codex:config.toml")
    cursor_home = homes.get("cursor") or ""
    if cursor_home:
        add_mcp_from_json(os.path.join(cursor_home, "mcp.json"), "cursor:mcp.json", mcp_sources)
    mcp = [{"name": n, "sources": srcs} for n, srcs in mcp_sources.items()]

    hooks = []
    for key in ("grok", "claude", "codex"):
        h = homes.get(key) or ""
        hd = os.path.join(h, "hooks") if h else ""
        if hd and os.path.isdir(hd):
            hooks.extend(sorted(os.listdir(hd)))

    workflows = []
    if grok_home:
        for sub, source in (("workflows", "user"), (os.path.join("bundled", "workflows"), "bundled")):
            d = os.path.join(grok_home, sub)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith(".rhai"):
                        workflows.append({"name": fn[:-5], "source": source, "path": os.path.join(d, fn)})
    for root in project_roots:
        for rel in (os.path.join(".grok", "workflows"), os.path.join(".claude", "workflows")):
            d = os.path.join(root, rel)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith((".rhai", ".md")):
                        workflows.append({"name": os.path.splitext(fn)[0], "source": "project", "path": os.path.join(d, fn)})

    mru = []
    if grok_home:
        mru_path = os.path.join(grok_home, "slash-mru.json")
        if os.path.isfile(mru_path):
            try:
                mru = sorted((read_json(mru_path).get("by_command") or {}).keys())
            except (OSError, ValueError):
                pass

    disabled_names = set(skills_disabled)
    for s in skills:
        from_enabled_source = s["source"] != "plugin" or s.get("plugin_state") == "enabled"
        s["loaded"] = from_enabled_source and s["name"] not in disabled_names
        s["disabled_by_name"] = s["name"] in disabled_names
        s["protected"] = (
            "plugin" if s["source"] == "plugin"
            else "bundled" if s["source"] == "bundled"
            else "git-tracked" if s["source"] == "project" and s.get("git_tracked") is not False
            else None
        )

    bodies = {}
    for s in skills:
        if s["loaded"] and s["source"] in ("user", "project"):
            try:
                with open(s["path"], encoding="utf-8", errors="replace") as f:
                    bodies[s["path"]] = f.read()
            except OSError:
                pass
    for s in skills:
        n = re.escape(s["name"])
        pat = re.compile(r"(`/?" + n + r"`|(?<![\w-])/" + n + r"(?![\w-])|skills/" + n + r"(?![\w-]))")
        s["referenced_by"] = sorted(
            {o["name"] for o in skills if o["loaded"] and o["path"] != s["path"]
             and o["path"] in bodies and pat.search(bodies[o["path"]])}
        )

    by_name = collections.defaultdict(list)
    for s in skills:
        if s["loaded"]:
            by_name[s["name"]].append(s["source"] + (":" + s["plugin"] if s["source"] == "plugin" else ""))
    collisions = {k: v for k, v in by_name.items() if len(v) > 1}

    return {
        "learn_home": homes.get("learn"),
        "homes": {k: v for k, v in homes.items() if v},
        "user_skills_dir": preferred,
        "user_skills_dir_realpath": os.path.realpath(preferred),
        "project_roots": project_roots,
        "skills": skills,
        "skills_disabled_by_name": skills_disabled,
        "plugins": plugins,
        "plugins_enabled_but_not_installed": enabled_missing,
        "plugins_disabled_but_not_installed": disabled_missing,
        "mcp_servers": mcp,
        "hooks": hooks,
        "workflows": workflows,
        "slash_mru": mru,
        "skill_name_collisions": collisions,
    }


def write_usage_and_phrases(out: str, kept: list[dict], surfaces: dict) -> list:
    def hit_record():
        return {"count": 0, "sessions": [], "last_used": None, "via": collections.Counter()}

    usage = collections.defaultdict(hit_record)

    def hit(key, r, n, via):
        u = usage[key]
        u["count"] += n
        if r["id"] not in u["sessions"] and len(u["sessions"]) < 8:
            u["sessions"].append(r["id"])
        if (r.get("updated_at") or "") > (u["last_used"] or ""):
            u["last_used"] = r.get("updated_at")
        u["via"][via] += n

    skill_names = {s["name"] for s in surfaces["skills"]}
    for r in kept:
        for name, n in r["skills_loaded"].items():
            hit(("skill", name), r, n, "skill_file_read")
        for name, n in r["slash_commands"].items():
            if name in skill_names or any(w["name"] == name for w in surfaces["workflows"]):
                hit(("skill" if name in skill_names else "workflow", name), r, n, "slash")
        for name, n in r["mcp_servers_used"].items():
            hit(("mcp", name), r, n, "tool")

    items = []
    for s in surfaces["skills"]:
        u = usage.get(("skill", s["name"]))
        items.append({
            "kind": "skill", "name": s["name"], "source": s["source"], "path": s["path"],
            "protected": s["protected"], "referenced_by": s["referenced_by"],
            "plugin": s.get("plugin"), "plugin_state": s.get("plugin_state"),
            "loaded": s["loaded"], "disabled_by_name": s["disabled_by_name"],
            "in_slash_mru": s["name"] in surfaces["slash_mru"],
            "count": u["count"] if u else 0, "sessions": u["sessions"] if u else [],
            "last_used": u["last_used"] if u else None, "via": dict(u["via"]) if u else {},
        })
    for p in surfaces["plugins"]:
        n = sum(i["count"] for i in items if i.get("plugin") == p["name"])
        sess = []
        for i in items:
            if i.get("plugin") == p["name"]:
                for sid in i["sessions"]:
                    if sid not in sess and len(sess) < 8:
                        sess.append(sid)
        items.append({"kind": "plugin", "name": p["name"], "state": p["state"], "path": p["dir"],
                      "skill_count": p["skill_count"], "count": n, "sessions": sess})
    for m in surfaces["mcp_servers"]:
        u = usage.get(("mcp", m["name"]))
        items.append({"kind": "mcp", "name": m["name"], "sources": m["sources"],
                      "count": u["count"] if u else 0, "sessions": u["sessions"] if u else [],
                      "last_used": u["last_used"] if u else None})
    for w in surfaces["workflows"]:
        u = usage.get(("workflow", w["name"]))
        items.append({"kind": "workflow", "name": w["name"], "source": w["source"], "path": w["path"],
                      "count": u["count"] if u else 0, "sessions": u["sessions"] if u else []})
    for h in surfaces["hooks"]:
        items.append({"kind": "hook", "name": h, "count": None, "note": "hook use is not visible in transcripts; judge by config only"})

    unknown_slash = collections.Counter()
    for r in kept:
        for name, n in r["slash_commands"].items():
            if name not in skill_names and name not in SLASH_STOP and not any(w["name"] == name for w in surfaces["workflows"]):
                unknown_slash[name] += n
    configured_mcp = {m["name"] for m in surfaces["mcp_servers"]}
    mcp_unconfigured = {k[1]: u["count"] for k, u in usage.items() if k[0] == "mcp" and k[1] not in configured_mcp}

    unused_loaded = [
        i for i in items
        if i["kind"] == "skill" and i["loaded"] and i["source"] in ("user", "project")
        and i["count"] == 0 and not i["in_slash_mru"]
    ]
    with open(os.path.join(out, "usage.json"), "w", encoding="utf-8") as f:
        json.dump({
            "kept_sessions": len(kept),
            "items": items,
            "unused_loaded": unused_loaded,
            "slash_commands_with_no_loaded_skill": dict(unknown_slash.most_common()),
            "mcp_servers_used_but_not_in_local_config": mcp_unconfigured,
            "note": "unused_loaded is user and project skills only; plugin/bundled inventories are not treated as delete candidates",
        }, f, indent=1, ensure_ascii=False)

    exact = collections.defaultdict(list)
    stems = collections.defaultdict(list)
    lines = collections.defaultdict(set)
    for r in kept:
        if r.get("repeated_single_turn"):
            continue
        for t in r["turns"]:
            n = normalize(t)
            if len(n) < 12:
                continue
            if SLASH_RE.fullmatch(t.strip()) or re.fullmatch(r"/[a-z0-9-]+(\s+\S+){0,3}", n):
                continue
            exact[n].append(r["id"])
            words = n.split(" ")
            if len(words) >= 6:
                stems[" ".join(words[:12])].append(r["id"])
            for ln in t.splitlines():
                ln_n = normalize(ln)
                if len(ln_n.split(" ")) >= 5 and len(ln_n) >= 24:
                    lines[ln_n].add(r["id"])

    def top(d, min_count, key_name, distinct_sessions=True):
        rows = []
        for k, ids in d.items():
            ids = list(ids)
            c = len(set(ids)) if distinct_sessions else len(ids)
            if c >= min_count:
                rows.append({key_name: k[:400], "sessions": c, "occurrences": len(ids), "session_ids": sorted(set(ids))[:8]})
        rows.sort(key=lambda x: (-x["sessions"], -x["occurrences"]))
        return rows[:60]

    with open(os.path.join(out, "phrases.json"), "w", encoding="utf-8") as f:
        json.dump({
            "exact_prompts": top(exact, 2, "phrase"),
            "prompt_stems_12_words": top(stems, 3, "stem"),
            "repeated_instruction_lines": top(lines, 3, "line"),
            "note": "counts are distinct sessions; single-turn sessions repeated 3+ times are excluded as likely automation",
        }, f, indent=1, ensure_ascii=False)
    return unused_loaded


def normalize(s: str) -> str:
    return WORD_RE.sub(" ", s.strip().lower())


def parse_harness_list(value: str) -> list[str]:
    if value in ("all", "", None):
        return list(HARNESSES)
    out = []
    for part in value.split(","):
        p = part.strip().lower()
        if p not in HARNESSES:
            raise argparse.ArgumentTypeError(f"unknown harness {p!r}; choose from {', '.join(HARNESSES)} or all")
        if p not in out:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=os.environ.get("LEARN_HOME") or os.path.expanduser("~/.learn"),
                    help="state/decisions/trash home (default: $LEARN_HOME or ~/.learn)")
    ap.add_argument("--grok-home", default=os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok"))
    ap.add_argument("--claude-home", default=os.environ.get("CLAUDE_HOME") or os.path.expanduser("~/.claude"))
    ap.add_argument("--codex-home", default=os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"))
    ap.add_argument("--cursor-home", default=os.environ.get("CURSOR_HOME") or os.path.expanduser("~/.cursor"))
    ap.add_argument("--agents-home", default=os.environ.get("AGENTS_HOME") or os.path.expanduser("~/.agents"))
    ap.add_argument("--harness", default="all", help="all, or comma list: grok,claude,codex,cursor")
    ap.add_argument("--out", default=None, help="run directory (default: <OS temp>/learn/<UTC timestamp>)")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--since-last", action="store_true")
    ap.add_argument("--include-headless", action="store_true")
    ap.add_argument("--include-subagents", action="store_true")
    ap.add_argument("--cwd", action="append", default=[])
    ap.add_argument("--exclude-cwd", action="append", default=None)
    ap.add_argument("--drop-pattern", action="append", default=[])
    ap.add_argument("--min-turns", type=int, default=1)
    ap.add_argument("--session-id", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()
    if args.batch < 1:
        ap.error("--batch must be at least 1")
    try:
        harnesses = parse_harness_list(args.harness)
    except argparse.ArgumentTypeError as e:
        ap.error(str(e))

    learn_home = os.path.abspath(os.path.expanduser(args.home))
    homes = {
        "learn": learn_home,
        "agents": os.path.abspath(os.path.expanduser(args.agents_home)),
        "grok": os.path.abspath(os.path.expanduser(args.grok_home)),
        "claude": os.path.abspath(os.path.expanduser(args.claude_home)),
        "codex": os.path.abspath(os.path.expanduser(args.codex_home)),
        "cursor": os.path.abspath(os.path.expanduser(args.cursor_home)),
    }

    present = []
    if "grok" in harnesses and os.path.isdir(os.path.join(homes["grok"], "sessions")):
        present.append("grok")
    if "claude" in harnesses and os.path.isdir(os.path.join(homes["claude"], "projects")):
        present.append("claude")
    if "codex" in harnesses and os.path.isdir(os.path.join(homes["codex"], "sessions")):
        present.append("codex")
    if "cursor" in harnesses and os.path.isdir(homes["cursor"]):
        present.append("cursor")
    if not present:
        log("no session stores found for " + ",".join(harnesses) +
            f" (looked in {homes['grok']}/sessions, {homes['claude']}/projects, {homes['codex']}/sessions, {homes['cursor']})")
        return 2

    if args.out:
        out = os.path.abspath(os.path.expanduser(args.out))
    else:
        stamp = "estimate" if args.estimate else dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = os.path.join(tempfile.gettempdir(), "learn", stamp)
    os.makedirs(out, exist_ok=True)
    try:
        os.chmod(out, 0o700)
    except OSError:
        pass
    if not args.estimate:
        os.makedirs(os.path.join(out, "sessions"), exist_ok=True)
        for sub in ("map", "reduce", "verify"):
            os.makedirs(os.path.join(out, sub), exist_ok=True)

    exclude_cwd = args.exclude_cwd if args.exclude_cwd is not None else default_exclude_cwd()
    drop_patterns = [re.compile(p, re.I) for p in DEFAULT_DROP_PATTERNS + args.drop_pattern]
    if args.estimate:
        args.days, args.since_last, args.limit = 0, False, 0
    cutoff = None
    if args.days > 0:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    state_path = os.path.join(learn_home, "state.json")
    if args.since_last:
        try:
            cutoff = parse_time(read_json(state_path).get("last_completed_at"))
        except (OSError, ValueError):
            cutoff = None
        if cutoff is None:
            log("--since-last: no completed run recorded; scanning everything")
    only_ids = set(args.session_id)

    seen = 0
    dropped: collections.Counter = collections.Counter()
    kept: list[dict] = []
    collectors = {
        "grok": collect_grok,
        "claude": collect_claude,
        "codex": collect_codex,
        "cursor": collect_cursor,
    }
    per_harness = {}
    for h in present:
        s, d, k = collectors[h](homes[h], args, cutoff, exclude_cwd, drop_patterns, only_ids)
        per_harness[h] = {"seen": s, "kept": len(k), "dropped": dict(d)}
        seen += s
        dropped.update(d)
        kept.extend(k)

    kept.sort(key=lambda r: r.get("updated_at") or "", reverse=True)

    if args.estimate:
        now = dt.datetime.now(dt.timezone.utc)
        try:
            st = read_json(state_path)
        except (OSError, ValueError):
            st = {}
        since = parse_time(st.get("last_completed_at"))

        def in_window(r, cut):
            ts = parse_time(r.get("updated_at"))
            return ts is not None and ts >= cut

        windows = {
            "all": kept,
            "30d": [r for r in kept if in_window(r, now - dt.timedelta(days=30))],
            "14d": [r for r in kept if in_window(r, now - dt.timedelta(days=14))],
            "quick": kept[:25],
        }
        if since is not None:
            windows["since_last"] = [r for r in kept if in_window(r, since)]
        est = {name: estimate(len(rows), args.batch) for name, rows in windows.items()}
        for name, rows in windows.items():
            est[name]["flags"] = {"all": [], "30d": ["--days", "30"], "14d": ["--days", "14"], "quick": ["--limit", "25"],
                                  "since_last": ["--since-last"]}[name]
        if since is not None and est.get("since_last", {}).get("sessions", 0) > 0:
            recommended = "since_last"
        elif len(kept) > 100:
            recommended = "14d"
        else:
            recommended = "all"
        result = {
            "learn_home": learn_home, "homes": {k: homes[k] for k in ("grok", "claude", "codex", "cursor") if k in present},
            "harnesses": present, "out": out,
            "generated_at": now.isoformat(timespec="seconds"), "sessions_seen": seen,
            "dropped": dict(dropped), "per_harness": per_harness, "batch": args.batch,
            "last_completed_at": st.get("last_completed_at"),
            "windows": est, "recommended": recommended,
            "note": "tokens are a calibrated estimate (about +/-50%); minutes grow slowly because mappers run in parallel",
        }
        with open(os.path.join(out, "estimate.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        log(f"seen={seen} kept(all)={len(kept)} harnesses={present} batch={args.batch}")
        for name in ("since_last", "quick", "14d", "30d", "all"):
            if name in est:
                e = est[name]
                log(f"  {name:<10} sessions={e['sessions']:>4} agents={e['agents']:>3} tokens~{e['tokens_m']:>5}M  minutes~{e['minutes'][0]}-{e['minutes'][1]}{'  (recommended)' if name == recommended else ''}")
        print(json.dumps(result))
        return 0

    if args.limit > 0 and len(kept) > args.limit:
        dropped["beyond_limit"] += len(kept) - args.limit
        kept = kept[: args.limit]

    single = collections.Counter(normalize(r["turns"][0]) for r in kept if r["human_turns"] == 1)
    for r in kept:
        r["repeated_single_turn"] = bool(r["human_turns"] == 1 and single[normalize(r["turns"][0])] >= 3)

    for i, r in enumerate(kept):
        r["index"] = i
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", r["id"])[:80]
        with open(os.path.join(out, "sessions", f"{i:04d}-{r['harness']}-{safe_id}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)

    surfaces = collect_surfaces(homes, kept)
    with open(os.path.join(out, "surfaces.json"), "w", encoding="utf-8") as f:
        json.dump(surfaces, f, indent=1, ensure_ascii=False)

    unused_loaded = write_usage_and_phrases(out, kept, surfaces)

    decisions_src = os.path.join(learn_home, "decisions.jsonl")
    if os.path.isfile(decisions_src):
        shutil.copyfile(decisions_src, os.path.join(out, "decisions.jsonl"))

    manifest = {
        "learn_home": learn_home,
        "harnesses": present,
        "per_harness": per_harness,
        "run_dir": out,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "params": {
            "days": args.days, "since_last": args.since_last, "cutoff": cutoff.isoformat() if cutoff else None,
            "include_headless": args.include_headless,
            "include_subagents": args.include_subagents, "cwd": args.cwd,
            "exclude_cwd": exclude_cwd, "drop_patterns": args.drop_pattern, "min_turns": args.min_turns,
            "session_ids": args.session_id, "limit": args.limit, "harness": args.harness,
        },
        "estimate": estimate(len(kept), args.batch),
        "sessions_seen": seen,
        "sessions_kept": len(kept),
        "dropped": dict(dropped),
        "human_turns_total": sum(r["human_turns"] for r in kept),
        "repeated_single_turn_sessions": sum(1 for r in kept if r["repeated_single_turn"]),
        "project_roots": surfaces["project_roots"],
        "kept": [{"index": r["index"], "id": r["id"], "harness": r["harness"], "cwd": r["cwd"],
                  "turns": r["human_turns"], "updated_at": r["updated_at"], "title": r["title"]} for r in kept],
        "prior_decisions": os.path.isfile(decisions_src),
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    try:
        state = read_json(state_path)
    except (OSError, ValueError):
        state = {}
    state.update({"last_run_at": manifest["generated_at"], "last_run_dir": out, "sessions_kept": len(kept)})
    if kept:
        state["pending"] = {"run_dir": out, "status": "collected", "started_at": manifest["generated_at"],
                            "updated_at": manifest["generated_at"], "report_ready": False}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)

    log(f"seen={seen} kept={len(kept)} dropped={dict(dropped)} turns={manifest['human_turns_total']} harnesses={present}")
    log(f"surfaces: skills={len(surfaces['skills'])} plugins={len(surfaces['plugins'])} mcp={len(surfaces['mcp_servers'])}")
    log(f"unused user/project skills={len(unused_loaded)}")
    print(json.dumps({"run_dir": out, "kept": len(kept), "seen": seen, "dropped": dict(dropped), "harnesses": present}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
