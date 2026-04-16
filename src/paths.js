// Install-path helpers. TIM_SOURCE_ROOT is where tim itself lives on disk —
// used to guard against accidental self-edits when the user is running `tim`
// from another project directory.

import path from "node:path";
import { fileURLToPath } from "node:url";

// This file lives at <TIM_SOURCE_ROOT>/src/paths.js — one dir up from __dirname.
const __filename = fileURLToPath(import.meta.url);
export const TIM_SOURCE_ROOT = path.resolve(path.dirname(__filename), "..");

export const isInsideTimSource = (absPath) => {
  if (!absPath) return false;
  return absPath === TIM_SOURCE_ROOT || absPath.startsWith(TIM_SOURCE_ROOT + path.sep);
};

export const isCwdTimSource = () => process.cwd() === TIM_SOURCE_ROOT;
