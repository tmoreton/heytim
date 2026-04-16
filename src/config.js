// Loads TIM.md context files: global from $TIM_DIR/TIM.md + local from ./TIM.md.
// Used to build the system prompt in react.js.

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const timDir = () => process.env.TIM_DIR || path.join(os.homedir(), ".tim");
const timPath = (...parts) => path.join(timDir(), ...parts);

const tryRead = (p) => {
  try {
    return fs.readFileSync(p, "utf8").trim();
  } catch {
    return null;
  }
};

export function loadProjectContext() {
  const parts = [];
  const global = tryRead(timPath("TIM.md"));
  if (global) parts.push(`# Global TIM.md\n${global}`);
  const local = tryRead(path.join(process.cwd(), "TIM.md"));
  if (local) parts.push(`# Project TIM.md\n${local}`);
  return parts.join("\n\n");
}
