// Session persistence to $TIM_DIR/sessions/ as JSON files.
// createSession(), save(), load(), list() — load() supports prefix matching for truncated IDs.
// Sessions are grouped by folder: repo-name for git repos, "general" for normal chats.

import fs from "node:fs";
import path from "node:path";
import { timPath } from "./paths.js";

const DIR = () => timPath("sessions");

const ensureDir = (subDir) => fs.mkdirSync(subDir, { recursive: true });

const newId = () =>
  new Date().toISOString().replace(/[:.]/g, "-").replace(/Z$/, "");

/** Detect if we're in a git repo and return the repo name */
function getRepoName(cwd) {
  try {
    // Check for .git in current directory or walk up
    let current = cwd;
    while (current && current !== path.dirname(current)) {
      const gitPath = path.join(current, ".git");
      if (fs.existsSync(gitPath)) {
        // Get repo name from directory name or remote URL
        const dirName = path.basename(current);
        // Sanitize: kebab-case, no special chars
        return dirName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      }
      current = path.dirname(current);
    }
  } catch {}
  return null;
}

/** Get session folder based on CWD */
function getSessionFolder(cwd) {
  const repo = getRepoName(cwd);
  if (repo) return repo;
  return "general";
}

export function createSession(model) {
  const cwd = process.cwd();
  const folder = getSessionFolder(cwd);
  const dir = path.join(DIR(), folder);
  ensureDir(dir);
  return {
    id: newId(),
    folder,
    cwd,
    model,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

export function save(session, messages, usage) {
  const folder = session.folder || getSessionFolder(session.cwd);
  const dir = path.join(DIR(), folder);
  ensureDir(dir);
  session.updatedAt = Date.now();
  const data = { ...session, messages, usage };
  fs.writeFileSync(path.join(dir, `${session.id}.json`), JSON.stringify(data, null, 2));
}

export function load(id) {
  if (!id || typeof id !== "string") {
    throw new Error("Session ID required");
  }
  
  // Sanitize ID to prevent directory traversal
  const safeId = id.replace(/[\/\\]/g, "");
  if (!safeId) {
    throw new Error("Invalid session ID");
  }

  // Get all subdirectories in sessions/
  const baseDir = DIR();
  const folders = fs.existsSync(baseDir) 
    ? fs.readdirSync(baseDir).filter(f => fs.statSync(path.join(baseDir, f)).isDirectory())
    : [];
  
  // Search in all folders for exact match
  for (const folder of folders) {
    const exact = path.join(baseDir, folder, `${safeId}.json`);
    if (fs.existsSync(exact)) {
      try {
        const data = JSON.parse(fs.readFileSync(exact, "utf8"));
        if (!data.id || !Array.isArray(data.messages)) {
          throw new Error("Corrupted session file");
        }
        return data;
      } catch (e) {
        if (e instanceof SyntaxError) {
          throw new Error(`Corrupted session file: ${safeId}`);
        }
        throw e;
      }
    }
  }

  // Prefix match across all folders
  const matches = [];
  for (const folder of folders) {
    const folderMatches = fs
      .readdirSync(path.join(baseDir, folder))
      .filter((f) => f.endsWith(".json") && f.startsWith(safeId))
      .map(f => path.join(folder, f));
    matches.push(...folderMatches);
  }
  
  if (matches.length === 1) {
    return JSON.parse(fs.readFileSync(path.join(baseDir, matches[0]), "utf8"));
  }
  if (matches.length > 1) {
    throw new Error(
      `Ambiguous session id "${safeId}" — matches ${matches.length} sessions. Use /sessions to see full IDs.`,
    );
  }

  // List recent sessions from all folders
  const allSessions = [];
  for (const folder of folders) {
    const files = fs.readdirSync(path.join(baseDir, folder)).filter(f => f.endsWith('.json'));
    for (const f of files) {
      const stat = fs.statSync(path.join(baseDir, folder, f));
      allSessions.push({ file: path.join(folder, f), mtime: stat.mtimeMs });
    }
  }
  const recent = allSessions
    .sort((a, b) => b.mtime - a.mtime)
    .slice(0, 3)
    .map(s => `  ${s.file.replace('.json', '')}`)
    .join('\n');
  throw new Error(`Session not found: ${safeId}\nRecent sessions:\n${recent}`);
}

export function list() {
  const baseDir = DIR();
  if (!fs.existsSync(baseDir)) return [];
  
  const folders = fs.readdirSync(baseDir).filter(f => fs.statSync(path.join(baseDir, f)).isDirectory());
  const sessions = [];
  
  for (const folder of folders) {
    const files = fs.readdirSync(path.join(baseDir, folder)).filter(f => f.endsWith(".json"));
    for (const f of files) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(baseDir, folder, f), "utf8"));
        sessions.push({
          id: data.id,
          folder,
          cwd: data.cwd,
          updatedAt: data.updatedAt,
          turns: (data.messages || []).filter((m) => m.role === "user").length,
        });
      } catch {}
    }
  }
  
  return sessions.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** List sessions grouped by folder */
export function listByFolder() {
  const sessions = list();
  const grouped = {};
  for (const s of sessions) {
    if (!grouped[s.folder]) grouped[s.folder] = [];
    grouped[s.folder].push(s);
  }
  return grouped;
}

export const latest = () => list()[0];
