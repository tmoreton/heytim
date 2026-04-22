// Tool registry. Auto-discovers any `src/tools/*.js` that exports a
// `tools` object — drop a file in this directory and its tools register
// on next launch. Each entry: { schema, run, requiredEnv? }.
// MCP tools are loaded from external MCP servers configured in $TIM_DIR/mcp.json.

import nodeFs from "node:fs";
import nodePath from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { rehydrateReadsFromMessages, markRead } from "./fs.js";
import { connectMcpServers, getMcpTools } from "../mcp.js";

const __dirname = nodePath.dirname(fileURLToPath(import.meta.url));

const hasRequiredEnv = (req) => {
  if (!req) return true;
  const vars = Array.isArray(req) ? req : [req];
  return vars.every((v) => process.env[v]);
};

// Scan src/tools/ for files exporting `tools = { name: { schema, run, requiredEnv? } }`.
// Tools with missing required env vars are silently dropped so the model doesn't see them.
async function loadCoreTools() {
  const out = {};
  const files = nodeFs.readdirSync(__dirname).filter((f) =>
    f.endsWith(".js") && f !== "index.js"
  );
  for (const file of files) {
    try {
      const mod = await import(pathToFileURL(nodePath.join(__dirname, file)).href);
      if (!mod.tools) continue;
      for (const [name, def] of Object.entries(mod.tools)) {
        if (!def?.schema || !def?.run) continue;
        if (!hasRequiredEnv(def.requiredEnv)) continue;
        out[name] = { schema: def.schema, run: def.run };
      }
    } catch (e) {
      console.error(`[tools] failed to load "${file}": ${e.message}`);
    }
  }
  return out;
}

// Built lazily so env vars from $TIM_DIR/.env are loaded by the time we
// decide what's registered.
let mergedTools = null;
let mcpConnected = false;

async function getMergedTools() {
  if (mergedTools) return mergedTools;
  const core = await loadCoreTools();

  if (!mcpConnected) {
    await connectMcpServers();
    mcpConnected = true;
  }
  const mcpTools = getMcpTools();
  const mcpToolDefs = {};
  for (const tool of mcpTools) {
    const fullName = `mcp_${tool.server}_${tool.name}`;
    mcpToolDefs[fullName] = {
      schema: {
        type: "function",
        function: {
          name: fullName,
          description: `[${tool.server}] ${tool.description}`,
          parameters: tool.inputSchema || { type: "object", properties: {} },
        },
      },
      run: async (args) => tool._call(args),
      isMcp: true,
      server: tool.server,
      originalName: tool.name,
    };
  }

  mergedTools = { ...core, ...mcpToolDefs };
  return mergedTools;
}

export async function getTools() {
  return getMergedTools();
}

export async function getToolSchemas() {
  const all = await getMergedTools();
  return Object.values(all).map((t) => t.schema);
}

// Re-exports for fs tracking
export { rehydrateReadsFromMessages, markRead };
