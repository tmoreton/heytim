// Snapshots of tim's own source files before the model edits them, so
// broken changes can be reverted. Written to $TIM_DIR/history/<ISO-ts>/
// mirroring the relative path under TIM_SOURCE_ROOT.

import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { TIM_SOURCE_ROOT, isInsideTimSource } from "./paths.js";

const timDir = () => process.env.TIM_DIR || path.join(os.homedir(), ".tim");

// One timestamp per REPL session keeps related edits grouped together.
const SESSION_STAMP = new Date().toISOString().replace(/[:.]/g, "-");

export function snapshotFile(absPath) {
  if (!isInsideTimSource(absPath)) return null;
  if (!fs.existsSync(absPath)) return null; // new file, nothing to snapshot
  const rel = path.relative(TIM_SOURCE_ROOT, absPath);
  const dest = path.join(timDir(), "history", SESSION_STAMP, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  // Don't overwrite an existing snapshot in the same session — we want the
  // earliest pre-edit state, not the most recent intermediate one.
  if (!fs.existsSync(dest)) fs.copyFileSync(absPath, dest);
  return dest;
}

export const historyDir = () => path.join(timDir(), "history");
