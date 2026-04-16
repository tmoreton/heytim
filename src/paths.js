// Single source of truth for tim's data directory.
// Honors $TIM_DIR override, falls back to ~/.tim.

import os from "node:os";
import path from "node:path";

export const timDir = () => process.env.TIM_DIR || path.join(os.homedir(), ".tim");
export const timPath = (...parts) => path.join(timDir(), ...parts);
