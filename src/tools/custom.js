// Custom tool loader — any `$TIM_DIR/tools/*.js` that exports `schema` + `run`
// is auto-registered. Optional `requiredEnv` (string | string[]) gates loading
// on env vars. Users edit these files directly; tim doesn't manage them.

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { timPath } from "../paths.js";

const toolsDir = () => timPath("tools");

const hasRequiredEnv = (required) => {
  if (!required) return true;
  const vars = Array.isArray(required) ? required : [required];
  return vars.every((v) => process.env[v]);
};

// Custom tool dirs need a package.json so node treats .js files as ESM.
function ensurePackageJson() {
  const pkg = path.join(toolsDir(), "package.json");
  if (!fs.existsSync(pkg)) {
    fs.writeFileSync(pkg, JSON.stringify({ type: "module" }, null, 2));
  }
}

export async function loadCustomTools() {
  const dir = toolsDir();
  const tools = {};
  let files;
  try { files = fs.readdirSync(dir).filter((f) => f.endsWith(".js")); }
  catch { return tools; }
  if (!files.length) return tools;
  ensurePackageJson();

  for (const file of files) {
    const name = path.basename(file, ".js");
    try {
      // Cache-buster forces a fresh import each call so user edits hot-reload.
      const mod = await import(`${pathToFileURL(path.join(dir, file)).href}?t=${Date.now()}`);
      if (!mod.schema || !mod.run) continue;
      if (!hasRequiredEnv(mod.requiredEnv)) continue;
      tools[name] = {
        schema: { ...mod.schema, function: { ...mod.schema.function, name } },
        run: mod.run,
        name,
      };
    } catch (e) {
      console.error(`[tim] Failed to load tool "${name}": ${e.message}`);
    }
  }
  return tools;
}

export async function listCustomToolNames() {
  return Object.keys(await loadCustomTools());
}
