import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const DIR = path.join(os.homedir(), ".tim", "sessions");

const ensureDir = () => fs.mkdirSync(DIR, { recursive: true });

const newId = () =>
  new Date().toISOString().replace(/[:.]/g, "-").replace(/Z$/, "");

export function createSession(model) {
  ensureDir();
  return {
    id: newId(),
    cwd: process.cwd(),
    model,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

export function save(session, messages, usage) {
  ensureDir();
  session.updatedAt = Date.now();
  const data = { ...session, messages, usage };
  fs.writeFileSync(path.join(DIR, `${session.id}.json`), JSON.stringify(data, null, 2));
}

export function load(id) {
  ensureDir();
  const exact = path.join(DIR, `${id}.json`);
  if (fs.existsSync(exact)) return JSON.parse(fs.readFileSync(exact, "utf8"));

  // Prefix match (e.g. user pasted a truncated ID from the status footer).
  const matches = fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith(".json") && f.startsWith(id));
  if (matches.length === 1)
    return JSON.parse(fs.readFileSync(path.join(DIR, matches[0]), "utf8"));
  if (matches.length > 1)
    throw new Error(
      `Ambiguous session id "${id}" — matches ${matches.length} sessions. Use /sessions to see full IDs.`,
    );
  throw new Error(`Session not found: ${id}`);
}

export function list() {
  ensureDir();
  return fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      const data = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8"));
      return {
        id: data.id,
        cwd: data.cwd,
        updatedAt: data.updatedAt,
        turns: (data.messages || []).filter((m) => m.role === "user").length,
      };
    })
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

export const latest = () => list()[0];
