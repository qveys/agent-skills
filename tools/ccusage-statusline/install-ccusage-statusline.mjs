#!/usr/bin/env node

/**
 * Cross-platform, user-space installer for ccusage and a cached Claude Code
 * statusline. Supported schedulers:
 *   - macOS: per-user LaunchAgent
 *   - Windows: per-user Scheduled Task
 *
 * The statusline never executes ccusage. A separate scheduled producer runs
 * ccusage, writes one timestamped JSON cache atomically, and exits.
 */

import { spawnSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const LABEL = "com.qveys.ccusage-status-cache";
const WINDOWS_TASK_NAME = "qveys-ccusage-status-cache";
const DEFAULT_INTERVAL_SECONDS = 3600;
const DEFAULT_VERSION = "latest";

const NODE_STATUSLINE_SOURCE = String.raw`#!/usr/bin/env node
"use strict";

// Cheap render path: read Claude stdin + two small JSON files. Never run ccusage.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", function (chunk) { input += chunk; });
process.stdin.on("end", function () {
  try {
    render();
  } catch (_error) {
    process.stdout.write("🤖  Claude | ⚠️  statusline error\n");
  }
});

function numeric(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function compactNumber(value) {
  const parsed = numeric(value);
  if (parsed === null) return null;
  if (parsed >= 1_000_000_000) return (parsed / 1_000_000_000).toFixed(1) + "B";
  if (parsed >= 1_000_000) return (parsed / 1_000_000).toFixed(0) + "M";
  if (parsed >= 1_000) return (parsed / 1_000).toFixed(0) + "k";
  return parsed.toFixed(0);
}

function formatDuration(seconds) {
  const safe = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  if (hours) return hours + "h " + String(minutes).padStart(2, "0") + "m";
  return minutes + "m";
}

function defaultCachePath() {
  if (process.platform === "win32") {
    const root = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(root, "ccusage-statusline", "metrics.json");
  }
  const root = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  return path.join(root, "ccusage-statusline", "metrics.json");
}

function formatCwd(cwd) {
  if (!cwd) return null;
  const home = os.homedir();
  if (cwd === home) return "~";
  return cwd.startsWith(home + path.sep) ? "~" + cwd.slice(home.length) : cwd;
}

// Reads .git/HEAD directly instead of spawning \`git\`, matching the
// never-shell-out discipline this statusline already follows for ccusage.
function gitBranchName(cwd) {
  if (!cwd) return null;
  let current = cwd;
  for (let i = 0; i < 64; i += 1) {
    const gitPath = path.join(current, ".git");
    let headPath = null;
    try {
      const stat = fs.statSync(gitPath);
      if (stat.isDirectory()) {
        headPath = path.join(gitPath, "HEAD");
      } else if (stat.isFile()) {
        const pointer = fs.readFileSync(gitPath, "utf8").trim();
        if (!pointer.startsWith("gitdir:")) return null;
        let gitdir = pointer.slice("gitdir:".length).trim();
        if (!path.isAbsolute(gitdir)) gitdir = path.join(current, gitdir);
        headPath = path.join(gitdir, "HEAD");
      }
    } catch (_error) {
      // No .git at this level; keep walking up toward the repo root.
    }
    if (headPath) {
      try {
        const head = fs.readFileSync(headPath, "utf8").trim();
        if (head.startsWith("ref:")) {
          const ref = head.slice("ref:".length).trim();
          const prefix = "refs/heads/";
          return ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
        }
        return head ? head.slice(0, 7) : null;
      } catch (_error) {
        return null;
      }
    }
    const parent = path.dirname(current);
    if (parent === current) return null;
    current = parent;
  }
  return null;
}

function loadConfig() {
  const configPath = process.argv[2] || process.env.CCUSAGE_STATUS_CONFIG
    || path.join(os.homedir(), ".claude", "ccusage-status-cache-config.json");
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    if (config && typeof config === "object" && !Array.isArray(config)) return config;
  } catch (_error) {
    // The cache fallback remains usable without a config file.
  }
  return {};
}

function cachePathFromConfig(config) {
  const explicit = process.env.CCUSAGE_STATUS_CACHE;
  if (explicit) return explicit;
  if (typeof config.cache_file === "string" && config.cache_file) return config.cache_file;
  return defaultCachePath();
}

// Ask the scheduler to run the producer now; this file still never runs ccusage.
// The scheduler already serialises the job and carries the environment it was
// registered with, so kicking it beats respawning the producer from here. The
// sentinel keeps a wedged producer from being kicked on every render.
function requestRefresh(config, cachePath, interval) {
  const argv = config.producer_kick_argv;
  const usable = Array.isArray(argv) && argv.length
    && argv.every(function (item) { return typeof item === "string" && item; });
  if (!usable) return false;

  const throttle = numeric(config.refresh_throttle_seconds) || Math.max(300, interval / 4);
  const sentinel = path.join(path.dirname(cachePath), ".refresh-requested");
  const now = Date.now() / 1000;
  try {
    if (now - fs.statSync(sentinel).mtimeMs / 1000 < throttle) return false;
  } catch (error) {
    if (!error || error.code !== "ENOENT") return false;
  }
  try {
    const childProcess = require("node:child_process");
    fs.mkdirSync(path.dirname(sentinel), { recursive: true });
    fs.writeFileSync(sentinel, String(Math.floor(now)) + "\n", "utf8");
    const child = childProcess.spawn(argv[0], argv.slice(1), {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.unref();
  } catch (_error) {
    return false;
  }
  return true;
}

function loadFreshCache(config) {
  const cachePath = cachePathFromConfig(config);
  let stat;
  let cache;
  try {
    stat = fs.statSync(cachePath);
    cache = JSON.parse(fs.readFileSync(cachePath, "utf8"));
  } catch (error) {
    if (error && error.code === "ENOENT") {
      const interval = numeric(config.interval_seconds) || 3600;
      const kicked = requestRefresh(config, cachePath, interval);
      return { cache: null, warning: "usage cache unavailable" + (kicked ? " ↻" : "") };
    }
    return { cache: null, warning: "usage cache invalid" };
  }

  if (!cache || typeof cache !== "object" || Array.isArray(cache)) {
    return { cache: null, warning: "usage cache invalid" };
  }
  const producedAt = numeric(cache.produced_at_epoch);
  const interval = numeric(cache.producer_interval_seconds) || 3600;
  const staleAfter = numeric(cache.stale_after_seconds) || (interval * 2 + 300);
  if (producedAt === null) return { cache: null, warning: "usage cache invalid" };

  const now = Date.now() / 1000;
  const ageFromPayload = Math.max(0, now - producedAt);
  const ageFromFile = Math.max(0, now - stat.mtimeMs / 1000);
  const age = Math.max(ageFromPayload, ageFromFile);
  if (age > staleAfter) {
    const kicked = requestRefresh(config, cachePath, interval);
    return {
      cache: null,
      warning: "usage cache stale (" + formatDuration(age) + " old)" + (kicked ? " ↻" : ""),
    };
  }
  // Refresh before the cache can go stale, so the warning stays unreachable.
  if (age > interval) requestRefresh(config, cachePath, interval);
  return { cache: cache, warning: null };
}

function render() {
  let payload = {};
  try { payload = JSON.parse(input || "{}"); } catch (_error) { payload = {}; }

  const model = payload.model || {};
  const modelName = model.display_name
    || process.env.CLAUDE_MODEL_DISPLAY_NAME
    || "Claude";
  const cost = payload.cost || {};
  const sessionCost = numeric(cost.total_cost_usd);

  const context = payload.context_window || {};
  const usage = context.current_usage || {};
  let contextTokens = [
    usage.input_tokens,
    usage.cache_creation_input_tokens,
    usage.cache_read_input_tokens,
  ].reduce(function (total, value) { return total + (numeric(value) || 0); }, 0);
  if (!contextTokens) contextTokens = numeric(context.total_input_tokens) || 0;
  let usedPercent = numeric(context.used_percentage);
  const windowSize = numeric(context.context_window_size);
  if (usedPercent === null && contextTokens && windowSize) {
    usedPercent = contextTokens * 100 / windowSize;
  }

  const fresh = loadFreshCache(loadConfig());
  const cache = fresh.cache;
  const parts = ["🤖  " + modelName];
  const cwdValue = payload.cwd || (payload.workspace || {}).current_dir;
  const cwdText = formatCwd(cwdValue);
  if (cwdText) parts.push("📁  " + cwdText);
  const branch = gitBranchName(cwdValue);
  if (branch) parts.push("🌿  " + branch);
  const costParts = [];
  if (sessionCost !== null) costParts.push("$" + sessionCost.toFixed(2) + " session");

  let activeBlock = null;
  if (cache) {
    const daily = cache.daily || {};
    const dailyCost = numeric(daily.cost_usd);
    if (dailyCost !== null) costParts.push("$" + dailyCost.toFixed(2) + " today");

    const block = cache.block || {};
    const blockCost = numeric(block.cost_usd);
    const blockEnd = numeric(block.ends_at_epoch);
    if (block.active === true && blockCost !== null && blockEnd !== null && blockEnd > Date.now() / 1000) {
      activeBlock = block;
      costParts.push(
        "$" + blockCost.toFixed(2) + " block ("
        + formatDuration(blockEnd - Date.now() / 1000) + " left)"
      );
    }
  }
  if (costParts.length) parts.push("💰  " + costParts.join(" / "));

  if (activeBlock) {
    const burnRate = numeric(activeBlock.burn_rate_usd_per_hour);
    if (burnRate !== null) parts.push("🔥  $" + burnRate.toFixed(2) + "/hr");
  }

  if (contextTokens) {
    let contextText = "🧠  " + Math.trunc(contextTokens).toLocaleString("en-US");
    if (usedPercent !== null) contextText += " (" + usedPercent.toFixed(0) + "%)";
    parts.push(contextText);
  }

  if (cache) {
    const tokens = compactNumber((cache.daily || {}).tokens);
    if (tokens !== null) parts.push("📊  " + tokens + " tok");
  }
  if (fresh.warning) parts.push("⚠️  " + fresh.warning);

  const time = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  parts.push("🕐  " + time);
process.stdout.write(parts.join(" | ") + "\n");
}
`;

const PYTHON_STATUSLINE_SOURCE = String.raw`#!/usr/bin/env python3
"""Cheap Claude Code statusline. This file never invokes ccusage."""

import datetime
import json
import os
import sys
import time


def numeric(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def compact_number(value):
    number = numeric(value)
    if number is None:
        return None
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.0f}M"
    if number >= 1_000:
        return f"{number / 1_000:.0f}k"
    return f"{number:.0f}"


def format_duration(seconds):
    safe = max(0, int(seconds))
    hours, remainder = divmod(safe, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def default_cache_path():
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    else:
        root = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
    return os.path.join(root, "ccusage-statusline", "metrics.json")


def format_cwd(cwd):
    if not cwd:
        return None
    home = os.path.expanduser("~")
    if cwd == home:
        return "~"
    if cwd.startswith(home + os.sep):
        return "~" + cwd[len(home):]
    return cwd


def git_branch_name(cwd):
    """Reads .git/HEAD directly instead of spawning git, matching the
    never-shell-out discipline this statusline already follows for ccusage."""
    if not cwd:
        return None
    current = cwd
    for _ in range(64):
        git_path = os.path.join(current, ".git")
        head_path = None
        if os.path.isdir(git_path):
            head_path = os.path.join(git_path, "HEAD")
        elif os.path.isfile(git_path):
            try:
                with open(git_path, encoding="utf-8") as git_file:
                    pointer = git_file.read().strip()
            except Exception:
                return None
            if not pointer.startswith("gitdir:"):
                return None
            gitdir = pointer[len("gitdir:"):].strip()
            if not os.path.isabs(gitdir):
                gitdir = os.path.join(current, gitdir)
            head_path = os.path.join(gitdir, "HEAD")
        if head_path is not None:
            try:
                with open(head_path, encoding="utf-8") as head_file:
                    head = head_file.read().strip()
            except Exception:
                return None
            if head.startswith("ref:"):
                ref = head[len("ref:"):].strip()
                prefix = "refs/heads/"
                return ref[len(prefix):] if ref.startswith(prefix) else ref
            return head[:7] if head else None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def load_config():
    config_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("CCUSAGE_STATUS_CONFIG")
        or os.path.join(os.path.expanduser("~"), ".claude", "ccusage-status-cache-config.json")
    )
    try:
        with open(config_path, encoding="utf-8") as config_file:
            config = json.load(config_file)
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def cache_path_from_config(config):
    explicit = os.environ.get("CCUSAGE_STATUS_CACHE")
    if explicit:
        return explicit
    configured = config.get("cache_file")
    if isinstance(configured, str) and configured:
        return configured
    return default_cache_path()


def request_refresh(config, cache_path, interval):
    """Ask the scheduler to run the producer now. This file still never runs ccusage.

    The scheduler already serialises the job and carries the environment it was
    registered with, so kicking it beats respawning the producer from here. The
    sentinel keeps a wedged producer from being kicked on every render.
    """
    argv = config.get("producer_kick_argv")
    if not isinstance(argv, list) or not argv:
        return False
    if not all(isinstance(item, str) and item for item in argv):
        return False

    throttle = numeric(config.get("refresh_throttle_seconds")) or max(300, interval / 4)
    sentinel = os.path.join(os.path.dirname(cache_path), ".refresh-requested")
    now = time.time()
    try:
        if now - os.stat(sentinel).st_mtime < throttle:
            return False
    except FileNotFoundError:
        pass
    except Exception:
        return False
    try:
        import subprocess

        detach = (
            {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        os.makedirs(os.path.dirname(sentinel), exist_ok=True)
        with open(sentinel, "w", encoding="utf-8") as sentinel_file:
            sentinel_file.write(f"{int(now)}\n")
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen(argv, stdin=devnull, stdout=devnull, stderr=devnull, **detach)
    except Exception:
        return False
    return True


def load_fresh_cache(config):
    cache_path = cache_path_from_config(config)
    try:
        stat = os.stat(cache_path)
        with open(cache_path, encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
    except FileNotFoundError:
        interval = numeric(config.get("interval_seconds")) or 3600
        kicked = request_refresh(config, cache_path, interval)
        return None, "usage cache unavailable" + (" ↻" if kicked else "")
    except Exception:
        return None, "usage cache invalid"
    if not isinstance(cache, dict):
        return None, "usage cache invalid"

    produced_at = numeric(cache.get("produced_at_epoch"))
    interval = numeric(cache.get("producer_interval_seconds")) or 3600
    stale_after = numeric(cache.get("stale_after_seconds")) or interval * 2 + 300
    if produced_at is None:
        return None, "usage cache invalid"
    now = time.time()
    age = max(0, now - produced_at, now - stat.st_mtime)
    if age > stale_after:
        kicked = request_refresh(config, cache_path, interval)
        return None, f"usage cache stale ({format_duration(age)} old)" + (" ↻" if kicked else "")
    # Refresh before the cache can go stale, so the warning stays unreachable.
    if age > interval:
        request_refresh(config, cache_path, interval)
    return cache, None


def render():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    model = payload.get("model") or {}
    model_name = (
        model.get("display_name")
        or os.environ.get("CLAUDE_MODEL_DISPLAY_NAME")
        or "Claude"
    )
    session_cost = numeric((payload.get("cost") or {}).get("total_cost_usd"))

    context = payload.get("context_window") or {}
    usage = context.get("current_usage") or {}
    context_tokens = sum(
        numeric(usage.get(key)) or 0
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    if not context_tokens:
        context_tokens = numeric(context.get("total_input_tokens")) or 0
    used_percent = numeric(context.get("used_percentage"))
    window_size = numeric(context.get("context_window_size"))
    if used_percent is None and context_tokens and window_size:
        used_percent = context_tokens * 100 / window_size

    cache, warning = load_fresh_cache(load_config())
    parts = [f"🤖  {model_name}"]
    cwd_value = payload.get("cwd") or (payload.get("workspace") or {}).get("current_dir")
    cwd_text = format_cwd(cwd_value)
    if cwd_text:
        parts.append(f"📁  {cwd_text}")
    branch = git_branch_name(cwd_value)
    if branch:
        parts.append(f"🌿  {branch}")
    costs = []
    if session_cost is not None:
        costs.append("$" + f"{session_cost:.2f} session")

    active_block = None
    if cache:
        daily = cache.get("daily") or {}
        daily_cost = numeric(daily.get("cost_usd"))
        if daily_cost is not None:
            costs.append("$" + f"{daily_cost:.2f} today")
        block = cache.get("block") or {}
        block_cost = numeric(block.get("cost_usd"))
        block_end = numeric(block.get("ends_at_epoch"))
        if block.get("active") is True and block_cost is not None and block_end and block_end > time.time():
            active_block = block
            costs.append("$" + f"{block_cost:.2f} block ({format_duration(block_end - time.time())} left)")
    if costs:
        parts.append("💰  " + " / ".join(costs))

    if active_block:
        burn = numeric(active_block.get("burn_rate_usd_per_hour"))
        if burn is not None:
            parts.append("🔥  $" + f"{burn:.2f}/hr")

    if context_tokens:
        context_text = f"🧠  {int(context_tokens):,}"
        if used_percent is not None:
            context_text += f" ({used_percent:.0f}%)"
        parts.append(context_text)
    if cache:
        tokens = compact_number((cache.get("daily") or {}).get("tokens"))
        if tokens is not None:
            parts.append(f"📊  {tokens} tok")
    if warning:
        parts.append(f"⚠️  {warning}")
    parts.append(f"🕐  {datetime.datetime.now():%H:%M}")
    print(" | ".join(parts))


try:
    render()
except Exception:
    print("🤖  Claude | ⚠️  statusline error")
`;

const PRODUCER_SOURCE = String.raw`#!/usr/bin/env node
"use strict";

// Expensive path: scheduled out-of-band. Never imported by the statusline.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const childProcess = require("node:child_process");

function numeric(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function executableNames() {
  return process.platform === "win32"
    ? ["ccusage.cmd", "ccusage.exe", "ccusage.bat", "ccusage"]
    : ["ccusage"];
}

function isExecutable(filePath) {
  try {
    fs.accessSync(filePath, process.platform === "win32" ? fs.constants.F_OK : fs.constants.X_OK);
    return true;
  } catch (_error) {
    return false;
  }
}

function resolveCcusage(config) {
  const configured = process.env.CCUSAGE_BIN || config.ccusage_bin;
  if (configured && isExecutable(configured)) return configured;

  const pathEntries = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  for (const directory of pathEntries) {
    for (const name of executableNames()) {
      const candidate = path.join(directory, name);
      if (isExecutable(candidate)) return candidate;
    }
  }

  const home = os.homedir();
  const candidates = process.platform === "win32"
    ? [
        path.join(process.env.APPDATA || path.join(home, "AppData", "Roaming"), "npm", "ccusage.cmd"),
        path.join(home, ".local", "bin", "ccusage.cmd"),
        path.join(home, ".bun", "bin", "ccusage.exe"),
        path.join(home, ".local", "share", "ccusage", "node_modules", ".bin", "ccusage.cmd"),
      ]
    : [
        "/opt/homebrew/bin/ccusage",
        path.join(home, ".local", "bin", "ccusage"),
        "/usr/local/bin/ccusage",
        path.join(home, ".bun", "bin", "ccusage"),
        path.join(home, ".local", "share", "ccusage", "node_modules", ".bin", "ccusage"),
      ];
  for (const candidate of candidates) {
    if (isExecutable(candidate)) return candidate;
  }
  throw new Error("ccusage was not found in PATH or explicit user-space candidates");
}

function runCcusage(binary, args) {
  const useShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(binary);
  const result = childProcess.spawnSync(binary, args, {
    encoding: "utf8",
    shell: useShell,
    timeout: 30 * 60 * 1000,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error("ccusage " + args[0] + " failed: " + (result.stderr || "exit " + result.status).trim());
  }
  return JSON.parse(result.stdout);
}

function parseInstant(value) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed / 1000 : null;
}

function localDay(offsetDays) {
  const now = new Date();
  if (offsetDays) now.setDate(now.getDate() + offsetDays);
  const pad = function (value) { return String(value).padStart(2, "0"); };
  return String(now.getFullYear()) + pad(now.getMonth() + 1) + pad(now.getDate());
}

function localIsoDay() {
  const compact = localDay();
  return compact.slice(0, 4) + "-" + compact.slice(4, 6) + "-" + compact.slice(6, 8);
}

function tokenTotal(row) {
  const sum = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]
    .reduce(function (total, key) { return total + (numeric(row[key]) || 0); }, 0);
  return sum || numeric(row.totalTokens) || 0;
}

function readConfig() {
  const configPath = process.argv[2] || process.env.CCUSAGE_STATUS_CONFIG
    || path.join(os.homedir(), ".claude", "ccusage-status-cache-config.json");
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  return { path: configPath, data: config };
}

function main() {
  const loaded = readConfig();
  const config = loaded.data;
  const interval = numeric(config.interval_seconds) || 3600;
  const staleAfter = numeric(config.stale_after_seconds) || interval * 2 + 300;
  const cacheFile = config.cache_file;
  if (typeof cacheFile !== "string" || !cacheFile) throw new Error("cache_file missing in config");

  const ccusage = resolveCcusage(config);
  const day = localIsoDay();
  const dailyJson = runCcusage(ccusage, ["daily", "--json", "--since", localDay()]);
  // Include yesterday because a five-hour block can cross local midnight.
  const blocksJson = runCcusage(ccusage, ["blocks", "--json", "--active", "--since", localDay(-1)]);

  const dailyRows = Array.isArray(dailyJson.daily)
    ? dailyJson.daily.filter(function (row) { return String(row.period || "").slice(0, 10) === day; })
    : [];
  const aggregateRows = dailyRows.filter(function (row) { return (row.agent || "all") === "all"; });
  const selectedRows = aggregateRows.length ? aggregateRows : dailyRows;
  const dailyTokens = selectedRows.reduce(function (total, row) { return total + tokenTotal(row); }, 0);
  const dailyCost = selectedRows.reduce(function (total, row) { return total + (numeric(row.totalCost) || 0); }, 0);

  const blocks = Array.isArray(blocksJson.blocks) ? blocksJson.blocks : [];
  const current = blocks.find(function (block) { return block && block.isActive === true; }) || null;
  let block = { active: false, cost_usd: null, ends_at: null, ends_at_epoch: null, burn_rate_usd_per_hour: null };
  if (current) {
    const startEpoch = parseInstant(current.startTime);
    const endEpoch = parseInstant(current.endTime) || (startEpoch === null ? null : startEpoch + 5 * 3600);
    block = {
      active: true,
      cost_usd: numeric(current.costUSD),
      ends_at: endEpoch === null ? null : new Date(endEpoch * 1000).toISOString(),
      ends_at_epoch: endEpoch,
      burn_rate_usd_per_hour: numeric((current.burnRate || {}).costPerHour),
    };
  }

  const producedAtEpoch = Math.floor(Date.now() / 1000);
  const output = {
    schema_version: 1,
    produced_at: new Date(producedAtEpoch * 1000).toISOString(),
    produced_at_epoch: producedAtEpoch,
    producer_interval_seconds: interval,
    stale_after_seconds: staleAfter,
    source: { ccusage_path: ccusage },
    daily: { date: day, tokens: dailyTokens, cost_usd: dailyCost },
    block: block,
  };

  fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
  const temporary = cacheFile + ".tmp-" + process.pid;
  try {
    fs.writeFileSync(temporary, JSON.stringify(output, null, 2) + "\n", "utf8");
    fs.renameSync(temporary, cacheFile);
  } finally {
    try { fs.rmSync(temporary, { force: true }); } catch (_error) {}
  }
  process.stdout.write(
    "cache updated: " + cacheFile + " produced_at=" + output.produced_at
    + " daily_tokens=" + dailyTokens + "\n"
  );
}

try {
  main();
} catch (error) {
  process.stderr.write("producer error: " + (error && error.message ? error.message : String(error)) + "\n");
  process.exit(1);
}
`;

function printHelp() {
  console.log(`Usage:
  macOS:
    ./install-ccusage-statusline.mjs ~/.claude
    ./install-ccusage-statusline.mjs --interval 7200 ~/.claude

  Windows PowerShell:
    node .\\install-ccusage-statusline.mjs "$env:USERPROFILE\\.claude"

Options:
  --interval <seconds>          Producer period; default 3600
  --stale-after <seconds>       Freshness limit; default 2*interval+300
  --ccusage-version <version>   Managed npm version/tag; default latest
  --ccusage-bin <path>          Use an existing binary and skip npm update
  --skip-ccusage-update         Resolve an existing binary and skip npm update
  --skip-initial-refresh        Do not run the producer during installation
  --no-schedule                 Prepare files but do not load/create the scheduler
  --help                        Show this help

The target is the Claude configuration directory. The installer is user-space
only: no sudo, no global npm installation. Existing files are timestamp-backed
up before replacement. The statusline never invokes ccusage.`);
}

function fail(message, code = 1) {
  console.error("Error: " + message);
  process.exit(code);
}

function parseInteger(value, option) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) fail(option + " requires a positive integer", 2);
  return parsed;
}

function parseArguments(argv) {
  const options = {
    interval: DEFAULT_INTERVAL_SECONDS,
    staleAfter: null,
    ccusageVersion: DEFAULT_VERSION,
    ccusageBin: null,
    skipCcusageUpdate: false,
    skipInitialRefresh: false,
    noSchedule: false,
    target: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      printHelp();
      process.exit(0);
    }
    if (argument === "--interval" || argument === "--stale-after" || argument === "--ccusage-version" || argument === "--ccusage-bin") {
      index += 1;
      if (index >= argv.length) fail(argument + " requires a value", 2);
      const value = argv[index];
      if (argument === "--interval") options.interval = parseInteger(value, argument);
      if (argument === "--stale-after") options.staleAfter = parseInteger(value, argument);
      if (argument === "--ccusage-version") options.ccusageVersion = value;
      if (argument === "--ccusage-bin") options.ccusageBin = path.resolve(expandTarget(value));
      continue;
    }
    if (argument === "--skip-ccusage-update") options.skipCcusageUpdate = true;
    else if (argument === "--skip-initial-refresh") options.skipInitialRefresh = true;
    else if (argument === "--no-schedule") options.noSchedule = true;
    else if (argument.startsWith("--")) fail("unknown option: " + argument, 2);
    else if (options.target !== null) fail("exactly one target directory is required", 2);
    else options.target = argument;
  }
  if (options.target === null) {
    printHelp();
    fail("missing Claude configuration directory", 2);
  }
  if (!/^[0-9A-Za-z._+-]+$/.test(options.ccusageVersion)) fail("invalid ccusage version/tag", 2);
  options.staleAfter = options.staleAfter || options.interval * 2 + 300;
  if (options.staleAfter <= options.interval) fail("--stale-after must exceed --interval", 2);
  return options;
}

function expandTarget(value) {
  let expanded = value.replace(/%([^%]+)%/g, function (match, name) {
    return process.env[name] ?? process.env[name.toUpperCase()] ?? match;
  });
  if (expanded === "~") return os.homedir();
  if (expanded.startsWith("~/") || expanded.startsWith("~\\")) {
    return path.join(os.homedir(), expanded.slice(2));
  }
  return expanded;
}

function stamp() {
  const now = new Date();
  const pad = function (value) { return String(value).padStart(2, "0"); };
  return String(now.getFullYear()) + pad(now.getMonth() + 1) + pad(now.getDate())
    + "-" + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
}

function uniqueBackupPath(filePath) {
  const base = filePath + ".backup-" + stamp();
  let candidate = base;
  let suffix = 1;
  while (existsSync(candidate)) {
    candidate = base + "-" + suffix;
    suffix += 1;
  }
  return candidate;
}

function backup(filePath) {
  if (!existsSync(filePath)) return null;
  const destination = uniqueBackupPath(filePath);
  const stat = lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    const target = readlinkSync(filePath);
    symlinkSync(target, destination);
  } else {
    copyFileSync(filePath, destination);
  }
  return destination;
}

function atomicWrite(filePath, content, mode = 0o644) {
  mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = filePath + ".tmp-" + process.pid;
  try {
    writeFileSync(temporary, content, { encoding: "utf8", mode: mode });
    renameSync(temporary, filePath);
  } finally {
    try { rmSync(temporary, { force: true }); } catch (_error) {}
  }
  if (process.platform !== "win32") chmodSync(filePath, mode);
}

function writeManagedFile(filePath, content, mode = 0o644) {
  if (existsSync(filePath) && readFileSync(filePath, "utf8") === content) {
    if (process.platform !== "win32") chmodSync(filePath, mode);
    return { changed: false, backupPath: null };
  }
  const backupPath = backup(filePath);
  atomicWrite(filePath, content, mode);
  return { changed: true, backupPath: backupPath };
}

function commandNeedsShell(command) {
  return process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    shell: commandNeedsShell(command),
    stdio: options.inherit ? "inherit" : "pipe",
    input: options.input,
    timeout: options.timeout,
    maxBuffer: options.maxBuffer || 32 * 1024 * 1024,
  });
}

function assertSuccess(result, description) {
  if (result.error) throw new Error(description + ": " + result.error.message);
  if (result.status !== 0) {
    throw new Error(description + ": " + (result.stderr || "exit " + result.status).trim());
  }
  return result;
}

function isExecutable(filePath) {
  try {
    if (!existsSync(filePath)) return false;
    return true;
  } catch (_error) {
    return false;
  }
}

function resolveExistingCcusage(homeDirectory) {
  const names = process.platform === "win32"
    ? ["ccusage.cmd", "ccusage.exe", "ccusage.bat", "ccusage"]
    : ["ccusage"];
  for (const directory of (process.env.PATH || "").split(path.delimiter).filter(Boolean)) {
    for (const name of names) {
      const candidate = path.join(directory, name);
      if (isExecutable(candidate)) return candidate;
    }
  }
  const candidates = process.platform === "win32"
    ? [
        path.join(process.env.APPDATA || path.join(homeDirectory, "AppData", "Roaming"), "npm", "ccusage.cmd"),
        path.join(homeDirectory, ".local", "bin", "ccusage.cmd"),
        path.join(homeDirectory, ".bun", "bin", "ccusage.exe"),
      ]
    : [
        "/opt/homebrew/bin/ccusage",
        path.join(homeDirectory, ".local", "bin", "ccusage"),
        "/usr/local/bin/ccusage",
        path.join(homeDirectory, ".bun", "bin", "ccusage"),
      ];
  return candidates.find(isExecutable) || null;
}

function installManagedCcusage(homeDirectory, version) {
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const root = path.join(homeDirectory, ".local", "share", "ccusage");
  const staging = root + ".install-" + stamp() + "-" + process.pid;
  const binaryRelative = path.join(
    "node_modules",
    ".bin",
    process.platform === "win32" ? "ccusage.cmd" : "ccusage"
  );
  mkdirSync(path.dirname(root), { recursive: true });
  console.log("Installing/updating isolated ccusage@" + version + " in staging...");
  try {
    assertSuccess(
      run(npm, ["install", "--prefix", staging, "ccusage@" + version, "--no-audit", "--no-fund"], { inherit: true }),
      "npm user-space installation failed"
    );
    const stagingBinary = path.join(staging, binaryRelative);
    if (!existsSync(stagingBinary)) {
      throw new Error("managed ccusage binary was not created: " + stagingBinary);
    }
    verifyCcusage(stagingBinary);

    let backupPath = null;
    if (existsSync(root)) {
      backupPath = uniqueBackupPath(root);
      renameSync(root, backupPath);
    }
    try {
      renameSync(staging, root);
    } catch (error) {
      if (backupPath && !existsSync(root) && existsSync(backupPath)) {
        renameSync(backupPath, root);
      }
      throw error;
    }
    return {
      binary: path.join(root, binaryRelative),
      change: { label: "Managed ccusage", path: root, changed: true, backupPath: backupPath },
    };
  } finally {
    try { rmSync(staging, { recursive: true, force: true }); } catch (_error) {}
  }
}

function verifyCcusage(binary) {
  const result = assertSuccess(run(binary, ["--version"]), "ccusage verification failed");
  return result.stdout.trim();
}

function readSettings(settingsPath) {
  if (!existsSync(settingsPath)) return {};
  try {
    const value = JSON.parse(readFileSync(settingsPath, "utf8"));
    if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("root is not an object");
    return value;
  } catch (error) {
    throw new Error("cannot parse " + settingsPath + ": " + error.message);
  }
}

function firstPathResult(command, args) {
  const result = run(command, args);
  if (result.status !== 0 || !result.stdout) return null;
  return result.stdout.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || null;
}

function detectStatuslineRuntime() {
  if (process.platform === "darwin") {
    const python = "/usr/bin/python3";
    const check = run(python, ["-c", "import sys; assert sys.version_info >= (3, 8); print(sys.implementation.cache_tag)"]);
    if (check.status !== 0) throw new Error("/usr/bin/python3 >= 3.8 is required for the fast macOS statusline");
    return { command: python, prefixArgs: [], source: PYTHON_STATUSLINE_SOURCE, filename: "statusline-ccusage.py", fast: true, isPython: true, cacheTag: check.stdout.trim() };
  }

  const pyLauncher = firstPathResult("where.exe", ["py.exe"]);
  if (pyLauncher) {
    const check = run(pyLauncher, ["-3", "-c", "import sys; assert sys.version_info >= (3, 8); print(sys.implementation.cache_tag)"]);
    if (check.status === 0) {
      return { command: pyLauncher, prefixArgs: ["-3"], source: PYTHON_STATUSLINE_SOURCE, filename: "statusline-ccusage.py", fast: true, isPython: true, cacheTag: check.stdout.trim() };
    }
  }
  const python = firstPathResult("where.exe", ["python.exe"]);
  if (python) {
    const check = run(python, ["-c", "import sys; assert sys.version_info >= (3, 8); print(sys.implementation.cache_tag)"]);
    if (check.status === 0) {
      return { command: python, prefixArgs: [], source: PYTHON_STATUSLINE_SOURCE, filename: "statusline-ccusage.py", fast: true, isPython: true, cacheTag: check.stdout.trim() };
    }
  }
  return {
    command: process.execPath,
    prefixArgs: [],
    source: NODE_STATUSLINE_SOURCE,
    filename: "statusline-ccusage.cjs",
    fast: false,
    isPython: false,
    cacheTag: null,
  };
}

function compilePythonStatusline(runtime, sourcePath, sourceChanged, changes) {
  if (!runtime.isPython) return sourcePath;
  const compiledPath = path.join(
    path.dirname(sourcePath),
    "statusline-ccusage." + runtime.cacheTag + ".pyc"
  );
  if (!sourceChanged && existsSync(compiledPath)) return compiledPath;

  const backupPath = backup(compiledPath);
  const temporary = compiledPath + ".tmp-" + process.pid;
  const code = "import py_compile,sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)";
  try {
    assertSuccess(
      run(runtime.command, [...runtime.prefixArgs, "-c", code, sourcePath, temporary]),
      "Python statusline bytecode compilation failed"
    );
    renameSync(temporary, compiledPath);
  } finally {
    try { rmSync(temporary, { force: true }); } catch (_error) {}
  }
  changes.push({
    label: "Compiled statusline",
    path: compiledPath,
    changed: true,
    backupPath: backupPath,
  });
  return compiledPath;
}

function quoteCommand(value) {
  if (process.platform === "win32") return '"' + value.replaceAll("\\", "/").replaceAll('"', '\\"') + '"';
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

function updateSettings(settingsPath, runtime, statuslinePath, configPath) {
  const settings = readSettings(settingsPath);
  const commandParts = [runtime.command, ...runtime.prefixArgs, statuslinePath, configPath];
  const desired = {
    type: "command",
    command: commandParts.map(quoteCommand).join(" "),
    refreshInterval: 120,
  };
  if (JSON.stringify(settings.statusLine) === JSON.stringify(desired)) {
    return { changed: false, backupPath: null };
  }
  const backupPath = backup(settingsPath);
  settings.statusLine = desired;
  atomicWrite(settingsPath, JSON.stringify(settings, null, 2) + "\n", 0o600);
  return { changed: true, backupPath: backupPath };
}

// Command the statusline uses to request an out-of-band refresh. Both schedulers
// refuse to start a second instance while one runs, so no extra lock is needed.
// Without a scheduler there is nothing to kick, hence the null.
//
// macOS occasionally fails to auto-bootstrap this LaunchAgent at login (seen
// after a reboot: absent from `launchctl list`, zero log lines, and a plain
// `kickstart` failing silently with "Could not find service"). A plain kick
// can't detect or fix that, so the cache stays stale until someone manually
// re-bootstraps it. Bootstrapping defensively before every kickstart costs
// nothing when the service is already loaded (it just errors and is ignored)
// and self-heals the missed auto-load case instead.
function producerKickArgv(noSchedule, plistPath) {
  if (noSchedule) return null;
  if (process.platform === "darwin") {
    const domain = "gui/" + process.getuid();
    const script = "/bin/launchctl bootstrap " + domain + " " + quoteCommand(plistPath)
      + " 2>/dev/null; exec /bin/launchctl kickstart -p " + quoteCommand(domain + "/" + LABEL);
    return ["/bin/sh", "-c", script];
  }
  return ["schtasks.exe", "/Run", "/TN", WINDOWS_TASK_NAME];
}

function xmlEscape(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function launchAgentSource(homeDirectory, producerPath, configPath, interval, stdoutPath, stderrPath) {
  const schedulerNode = ["/opt/homebrew/bin/node", "/usr/local/bin/node", process.execPath]
    .find(function (candidate) { return existsSync(candidate); });
  const schedulerPath = [
    path.dirname(schedulerNode),
    "/opt/homebrew/bin",
    path.join(homeDirectory, ".local", "bin"),
    "/usr/local/bin",
    path.join(homeDirectory, ".bun", "bin"),
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
  ].filter(function (entry, index, entries) { return entries.indexOf(entry) === index; }).join(":");
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${xmlEscape(schedulerNode)}</string>
    <string>${xmlEscape(producerPath)}</string>
    <string>${xmlEscape(configPath)}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${xmlEscape(schedulerPath)}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${interval}</integer>
  <!-- No ProcessType=Background: launchd treats those jobs as discretionary and
       defers them on battery / Low Power Mode, which lets the cache go stale for
       hours. Nice and LowPriorityIO already contain a ~5 s run. -->
  <key>LowPriorityIO</key>
  <true/>
  <key>Nice</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${xmlEscape(stdoutPath)}</string>
  <key>StandardErrorPath</key>
  <string>${xmlEscape(stderrPath)}</string>
</dict>
</plist>
`;
}

function macPlistPath(homeDirectory) {
  return path.join(homeDirectory, "Library", "LaunchAgents", LABEL + ".plist");
}

function configureMacScheduler(homeDirectory, producerPath, configPath, interval, changes, shouldLoad) {
  const launchAgents = path.join(homeDirectory, "Library", "LaunchAgents");
  const logs = path.join(homeDirectory, "Library", "Logs");
  mkdirSync(launchAgents, { recursive: true });
  mkdirSync(logs, { recursive: true });
  const plistPath = macPlistPath(homeDirectory);
  const logPath = path.join(logs, LABEL + ".log");
  const result = writeManagedFile(
    plistPath,
    launchAgentSource(homeDirectory, producerPath, configPath, interval, logPath, logPath),
    0o644
  );
  changes.push({ label: "LaunchAgent", path: plistPath, ...result });

  const domain = "gui/" + process.getuid();
  if (shouldLoad) {
    run("launchctl", ["bootout", domain + "/" + LABEL]);
    assertSuccess(run("launchctl", ["bootstrap", domain, plistPath]), "LaunchAgent bootstrap failed");
  }
  return {
    prepared: plistPath,
    load: "launchctl bootstrap " + domain + " " + quoteCommand(plistPath),
    run: "launchctl kickstart -k " + domain + "/" + LABEL,
    unload: "launchctl bootout " + domain + "/" + LABEL,
  };
}

function windowsTaskCommand(producerPath, configPath) {
  return '"' + process.execPath.replaceAll('"', '\\"') + '" "'
    + producerPath.replaceAll('"', '\\"') + '" "' + configPath.replaceAll('"', '\\"') + '"';
}

function configureWindowsScheduler(claudeDirectory, producerPath, configPath, interval, changes) {
  if (interval % 60 !== 0) throw new Error("Windows scheduled intervals must be divisible by 60 seconds");
  const existing = run("schtasks.exe", ["/Query", "/TN", WINDOWS_TASK_NAME, "/XML"]);
  if (existing.status === 0 && existing.stdout.trim()) {
    const taskBackup = path.join(claudeDirectory, WINDOWS_TASK_NAME + ".xml.backup-" + stamp());
    atomicWrite(taskBackup, existing.stdout, 0o600);
    changes.push({ label: "Scheduled Task", path: WINDOWS_TASK_NAME, changed: true, backupPath: taskBackup });
  }
  const minutes = String(interval / 60);
  assertSuccess(
    run("schtasks.exe", [
      "/Create", "/TN", WINDOWS_TASK_NAME,
      "/SC", "MINUTE", "/MO", minutes,
      "/TR", windowsTaskCommand(producerPath, configPath),
      "/F",
    ]),
    "Scheduled Task creation failed"
  );
  return {
    run: "schtasks /Run /TN \"" + WINDOWS_TASK_NAME + "\"",
    unload: "schtasks /Delete /TN \"" + WINDOWS_TASK_NAME + "\" /F",
  };
}

function verifyStatusline(runtime, statuslinePath, configPath) {
  // A throwaway .git/HEAD fixture proves the branch-detection walk-up without
  // depending on the installer's own directory being a git repo.
  const branchFixture = path.join(os.tmpdir(), "ccusage-statusline-selftest-" + process.pid);
  mkdirSync(path.join(branchFixture, ".git"), { recursive: true });
  writeFileSync(path.join(branchFixture, ".git", "HEAD"), "ref: refs/heads/skill/selftest-branch\n", "utf8");
  try {
    const payload = JSON.stringify({
      model: { display_name: "Opus" },
      cost: { total_cost_usd: 1.25 },
      cwd: branchFixture,
      context_window: {
        used_percentage: 57,
        current_usage: { input_tokens: 100000, cache_creation_input_tokens: 3718, cache_read_input_tokens: 10000 },
      },
    });
    const result = assertSuccess(
      run(runtime.command, [...runtime.prefixArgs, statuslinePath, configPath], { input: payload }),
      "statusline self-test failed"
    );
    if (
      !result.stdout.includes("Opus")
      || !result.stdout.includes("113,718")
      || !result.stdout.includes("skill/selftest-branch")
    ) {
      throw new Error("statusline self-test returned unexpected output: " + result.stdout.trim());
    }
    return result.stdout.trim();
  } finally {
    rmSync(branchFixture, { recursive: true, force: true });
  }
}

function describeChange(change) {
  console.log(change.label + ": " + (change.changed ? "installed/updated" : "already current") + " (" + change.path + ")");
  if (!change.backupPath) return;
  console.log("  backup: " + change.backupPath);
  if (change.label === "Scheduled Task") {
    console.log("  rollback: schtasks /Create /TN \"" + WINDOWS_TASK_NAME + "\" /XML \"" + change.backupPath + "\" /F");
  } else if (process.platform === "win32") {
    const powerShellQuote = function (value) { return "'" + value.replaceAll("'", "''") + "'"; };
    const displaced = change.path + ".replaced-before-rollback-" + stamp();
    console.log(
      "  rollback: Move-Item -LiteralPath " + powerShellQuote(change.path)
      + " -Destination " + powerShellQuote(displaced)
      + "; Copy-Item -LiteralPath " + powerShellQuote(change.backupPath)
      + " -Destination " + powerShellQuote(change.path) + " -Recurse -Force"
    );
  } else {
    const displaced = change.path + ".replaced-before-rollback-" + stamp();
    console.log(
      "  rollback: mv -- " + quoteCommand(change.path) + " " + quoteCommand(displaced)
      + " && cp -pR -- " + quoteCommand(change.backupPath) + " " + quoteCommand(change.path)
    );
  }
}

function main() {
  if (!new Set(["darwin", "win32"]).has(process.platform)) {
    fail("supported platforms are macOS and Windows");
  }
  const options = parseArguments(process.argv.slice(2));
  const claudeDirectory = path.resolve(expandTarget(options.target));
  const homeDirectory = path.dirname(claudeDirectory);
  const statuslineRuntime = detectStatuslineRuntime();
  const statuslinePath = path.join(claudeDirectory, statuslineRuntime.filename);
  const configPath = path.join(claudeDirectory, "ccusage-status-cache-config.json");
  const settingsPath = path.join(claudeDirectory, "settings.json");
  const producerPath = path.join(homeDirectory, ".local", "bin", "ccusage-status-cache-producer.cjs");
  const targetsCurrentHome = path.resolve(homeDirectory) === path.resolve(os.homedir());
  const cachePath = process.platform === "win32"
    ? path.join(
        targetsCurrentHome && process.env.LOCALAPPDATA
          ? process.env.LOCALAPPDATA
          : path.join(homeDirectory, "AppData", "Local"),
        "ccusage-statusline",
        "metrics.json"
      )
    : path.join(
        targetsCurrentHome && process.env.XDG_CACHE_HOME
          ? process.env.XDG_CACHE_HOME
          : path.join(homeDirectory, ".cache"),
        "ccusage-statusline",
        "metrics.json"
      );

  // Validate existing settings before changing npm, files, or schedulers.
  readSettings(settingsPath);
  mkdirSync(claudeDirectory, { recursive: true });

  const changes = [];
  let ccusageBinary = options.ccusageBin;
  if (ccusageBinary && !existsSync(ccusageBinary)) throw new Error("--ccusage-bin does not exist: " + ccusageBinary);
  if (!ccusageBinary && !options.skipCcusageUpdate) {
    const installed = installManagedCcusage(homeDirectory, options.ccusageVersion);
    ccusageBinary = installed.binary;
    changes.push(installed.change);
  }
  if (!ccusageBinary) ccusageBinary = resolveExistingCcusage(homeDirectory);
  if (!ccusageBinary) throw new Error("ccusage not found; remove --skip-ccusage-update to install it in user-space");
  console.log("ccusage: " + verifyCcusage(ccusageBinary) + " (" + ccusageBinary + ")");

  const statuslineResult = writeManagedFile(statuslinePath, statuslineRuntime.source, 0o755);
  changes.push({ label: "Statusline", path: statuslinePath, ...statuslineResult });
  const statuslineExecutionPath = compilePythonStatusline(
    statuslineRuntime,
    statuslinePath,
    statuslineResult.changed,
    changes
  );
  const producerResult = writeManagedFile(producerPath, PRODUCER_SOURCE, 0o755);
  changes.push({ label: "Producer", path: producerPath, ...producerResult });

  const config = {
    schema_version: 1,
    ccusage_bin: ccusageBinary,
    cache_file: cachePath,
    interval_seconds: options.interval,
    stale_after_seconds: options.staleAfter,
  };
  const kickArgv = producerKickArgv(
    options.noSchedule,
    process.platform === "darwin" ? macPlistPath(homeDirectory) : null
  );
  if (kickArgv) {
    config.producer_kick_argv = kickArgv;
    config.refresh_throttle_seconds = Math.max(300, Math.floor(options.interval / 4));
  }
  const configResult = writeManagedFile(configPath, JSON.stringify(config, null, 2) + "\n", 0o600);
  changes.push({ label: "Producer config", path: configPath, ...configResult });

  if (!options.skipInitialRefresh) {
    console.log("Running initial out-of-band cache refresh (this is the expensive step)...");
    assertSuccess(
      run(process.execPath, [producerPath, configPath], { inherit: true, timeout: 30 * 60 * 1000 }),
      "initial producer refresh failed"
    );
  }

  const settingsResult = updateSettings(
    settingsPath,
    statuslineRuntime,
    statuslineExecutionPath,
    configPath
  );
  changes.push({ label: "Claude settings", path: settingsPath, ...settingsResult });

  let schedulerCommands = null;
  if (process.platform === "darwin") {
    // Even --no-schedule prepares the plist so it can be linted and loaded later.
    schedulerCommands = configureMacScheduler(
      homeDirectory,
      producerPath,
      configPath,
      options.interval,
      changes,
      !options.noSchedule
    );
  } else if (!options.noSchedule) {
    schedulerCommands = configureWindowsScheduler(
      claudeDirectory,
      producerPath,
      configPath,
      options.interval,
      changes
    );
  }

  const selfTest = verifyStatusline(
    statuslineRuntime,
    statuslineExecutionPath,
    configPath
  );
  changes.forEach(describeChange);
  console.log("Cache: " + cachePath);
  console.log("Freshness limit: " + options.staleAfter + " seconds");
  console.log("Statusline runtime: " + statuslineRuntime.command + (statuslineRuntime.fast ? " (fast path)" : " (Node fallback; benchmark on this Windows host)"));
  console.log("Self-test: " + selfTest);
  if (schedulerCommands && options.noSchedule) {
    console.log("Scheduler: prepared but not loaded (--no-schedule): " + schedulerCommands.prepared);
    console.log("Load: " + schedulerCommands.load);
    console.log("Run producer now: " + schedulerCommands.run);
    console.log("Unload: " + schedulerCommands.unload);
  } else if (schedulerCommands) {
    if (schedulerCommands.load) console.log("Load: " + schedulerCommands.load);
    console.log("Run producer now: " + schedulerCommands.run);
    console.log("Unload: " + schedulerCommands.unload);
  } else {
    console.log("Scheduler: skipped by --no-schedule");
  }
  console.log("Rollback: use the exact command printed below each backup, after unloading the scheduler.");
  console.log("Restart active Claude Code sessions so they reload settings.json.");
}

try {
  main();
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}
