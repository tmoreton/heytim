// Unified TIM server: scheduler + HTTP/WebSocket API
// Handles cron triggers, agent chat, and remote client connections.

import { createServer } from "node:http";
import { execSync } from "node:child_process";
import { loadTriggers, getTriggerState, recordRun } from "./triggers.js";
import { matches, sameMinute } from "./cron.js";
import { loadWorkflows, mergeProfile } from "./workflows.js";
import { loadAgents } from "./agents.js";
import { createAgent, resumeSession } from "./react.js";
import { getTools } from "./tools/index.js";
import { setAutoAccept } from "./permissions.js";
import { load as loadSession, save as saveSession, list as listSessions, listByFolder } from "./session.js";

const TICK_MS = 30_000;
const DEFAULT_PORT = 8080;

const ts = () => new Date().toISOString();
const log = (...args) => console.log(`[${ts()}]`, ...args);

// ============================================================================
// TAILSCALE DETECTION
// ============================================================================

const TAILSCALE_PATHS = [
  "tailscale",
  "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
  "/usr/local/bin/tailscale",
  "/opt/homebrew/bin/tailscale",
];

let cachedTailscalePath = null;

function findTailscale() {
  if (cachedTailscalePath) return cachedTailscalePath;
  for (const path of TAILSCALE_PATHS) {
    try {
      if (path === "tailscale") {
        execSync("which tailscale", { timeout: 1000, stdio: "ignore" });
        cachedTailscalePath = path;
        return path;
      }
      execSync(`test -x "${path}"`, { timeout: 1000, stdio: "ignore" });
      cachedTailscalePath = path;
      return path;
    } catch {}
  }
  return null;
}

function getTailscaleIP() {
  const bin = findTailscale();
  if (!bin) return null;
  try {
    const output = execSync(`"${bin}" ip -4 2>/dev/null`, { 
      encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"]
    });
    const lines = output.trim().split("\n");
    for (const line of lines) {
      const ip = line.trim();
      if (ip.startsWith("100.")) return ip;
    }
    return null;
  } catch {
    return null;
  }
}

function hasTailscaleCLI() {
  return !!findTailscale();
}

function getTailscaleStatus() {
  const bin = findTailscale();
  if (!bin) return null;
  try {
    const output = execSync(`"${bin}" status 2>/dev/null`, { encoding: "utf8", timeout: 5000 });
    return output.trim();
  } catch {
    return null;
  }
}

// ============================================================================
// SCHEDULER (CRON TRIGGERS)
// ============================================================================

function looksEmpty(result) {
  if (result == null) return true;
  if (typeof result === "string") return !result.trim() || result.startsWith("ERROR:");
  if (Array.isArray(result)) return result.length === 0;
  if (typeof result === "object") {
    if (Array.isArray(result.emails) && result.emails.length === 0) return true;
    if (Array.isArray(result.items) && result.items.length === 0) return true;
    if (Array.isArray(result.messages) && result.messages.length === 0) return true;
    if (result.count === 0) return true;
  }
  return false;
}

async function hasWork(precheckTool) {
  if (!precheckTool) return { work: true };
  try {
    const tools = await getTools();
    const tool = tools[precheckTool];
    if (!tool) {
      log(`  ⚠ precheck tool "${precheckTool}" not found — firing anyway`);
      return { work: true };
    }
    const result = await tool.run({ dryRun: true }, { signal: null });
    const count = Array.isArray(result?.emails) ? result.emails.length
                : Array.isArray(result?.items)  ? result.items.length
                : Array.isArray(result?.messages) ? result.messages.length
                : typeof result?.count === "number" ? result.count
                : null;
    if (count !== null) return { work: count > 0, count };
    const data = result && typeof result === "object" && "content" in result ? result.content : result;
    return { work: !looksEmpty(data), count: null };
  } catch (e) {
    log(`  ⚠ precheck failed: ${e.message} — firing anyway`);
    return { work: true };
  }
}

async function fireTrigger(trigger) {
  const workflows = loadWorkflows();
  const workflow = workflows[trigger.workflow];
  if (!workflow) {
    log(`✗ ${trigger.name}: workflow "${trigger.workflow}" not found`);
    recordRun(trigger.name, { startedAt: ts(), finishedAt: ts(), status: "error", error: `workflow "${trigger.workflow}" not found` });
    return;
  }
  const agents = loadAgents();
  const agent = agents[workflow.agent];
  if (!agent) {
    log(`✗ ${trigger.name}: agent "${workflow.agent}" not found`);
    recordRun(trigger.name, { startedAt: ts(), finishedAt: ts(), status: "error", error: `agent "${workflow.agent}" not found` });
    return;
  }

  const task = trigger.task || workflow.task || `Run the ${workflow.name} workflow.`;
  const started = ts();
  log(`→ firing ${trigger.name} (${workflow.name} → ${agent.name})`);
  try {
    const sub = await createAgent(mergeProfile(agent, workflow));
    await sub.turn(task);
    const finished = ts();
    log(`✓ ${trigger.name} done (${Math.round((new Date(finished) - new Date(started)) / 1000)}s)`);
    recordRun(trigger.name, { startedAt: started, finishedAt: finished, status: "ok" });
  } catch (e) {
    log(`✗ ${trigger.name} failed: ${e.message}`);
    recordRun(trigger.name, { startedAt: started, finishedAt: ts(), status: "error", error: e.message });
  }
}

async function tick() {
  const now = new Date();
  const triggers = loadTriggers();
  for (const t of triggers) {
    if (!t.enabled) continue;
    if (!matches(t.schedule, now)) continue;

    const prev = getTriggerState(t.name);
    if (prev?.lastRunAt) {
      const prevDate = new Date(prev.lastRunAt);
      if (sameMinute(prevDate, now)) continue;
    }

    const workflows = loadWorkflows();
    const w = workflows[t.workflow];
    const precheck = t.precheck || w?.precheck || null;
    if (precheck) {
      const { work, count } = await hasWork(precheck);
      if (!work) {
        log(`· ${t.name} precheck (${precheck}): 0 items — skipping`);
        continue;
      }
      const n = typeof count === "number" ? count : "?";
      log(`· ${t.name} precheck (${precheck}): ${n} item(s) — firing`);
    }

    await fireTrigger(t);
  }
}

function startScheduler() {
  const triggers = loadTriggers();
  log(`scheduler: ${triggers.length} trigger(s) loaded`);
  for (const t of triggers) {
    log(`  • ${t.name} [${t.schedule}] → ${t.workflow}${t.enabled ? "" : " (disabled)"}`);
  }

  tick().catch((e) => log(`tick error: ${e.message}`));
  return setInterval(() => tick().catch((e) => log(`tick error: ${e.message}`)), TICK_MS);
}

// ============================================================================
// HTTP SERVER + WEBSOCKET
// ============================================================================

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => { try { resolve(body ? JSON.parse(body) : {}); } catch (e) { reject(e); } });
    req.on("error", reject);
  });
}

async function createHttpServer() {
  const connections = new Map();

  const httpServer = createServer(async (req, res) => {
    if (req.method === "OPTIONS") {
      res.writeHead(204, corsHeaders);
      res.end();
      return;
    }

    const url = new URL(req.url, `http://localhost`);
    const path = url.pathname;

    try {
      if (path === "/health" && req.method === "GET") {
        res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
        res.end(JSON.stringify({ status: "ok" }));
        return;
      }

      if (path === "/agents" && req.method === "GET") {
        const agents = Object.values(loadAgents()).map(a => ({ name: a.name, description: a.description, tools: a.tools }));
        res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
        res.end(JSON.stringify({ agents }));
        return;
      }

      if (path === "/workflows" && req.method === "GET") {
        const workflows = Object.values(loadWorkflows()).map(w => ({ name: w.name, agent: w.agent, description: w.description }));
        res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
        res.end(JSON.stringify({ workflows }));
        return;
      }

      if (path === "/sessions" && req.method === "GET") {
        const groupByFolder = url.searchParams.get("group") === "folder";
        if (groupByFolder) {
          res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
          res.end(JSON.stringify({ sessionsByFolder: listByFolder() }));
        } else {
          res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
          res.end(JSON.stringify({ sessions: listSessions() }));
        }
        return;
      }

      if (path.startsWith("/sessions/") && req.method === "GET") {
        const id = path.split("/")[2];
        const session = loadSession(id);
        if (!session) {
          res.writeHead(404, { "Content-Type": "application/json", ...corsHeaders });
          res.end(JSON.stringify({ error: "session not found" }));
          return;
        }
        res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
        res.end(JSON.stringify(session));
        return;
      }

      if (path === "/chat" && req.method === "POST") {
        const body = await readBody(req);
        const { agent: agentName, message, sessionId, folder } = body;

        if (!agentName || !message) {
          res.writeHead(400, { "Content-Type": "application/json", ...corsHeaders });
          res.end(JSON.stringify({ error: "agent and message required" }));
          return;
        }

        const agents = loadAgents();
        const agent = agents[agentName];
        if (!agent) {
          res.writeHead(404, { "Content-Type": "application/json", ...corsHeaders });
          res.end(JSON.stringify({ error: `agent "${agentName}" not found` }));
          return;
        }

        let sub;
        if (sessionId) {
          const data = loadSession(sessionId);
          if (data) sub = resumeSession(data);
        }
        if (!sub) {
          if (folder) process.chdir(folder); // Set context for new session
          sub = await createAgent(agent);
        }

        await sub.turn(message);
        const last = sub.state.messages.filter(m => m.role === "assistant" && !m.tool_calls?.length && m.content).pop();
        const saved = saveSession(sub.state);

        res.writeHead(200, { "Content-Type": "application/json", ...corsHeaders });
        res.end(JSON.stringify({ response: last?.content || "", sessionId: saved.id, messages: sub.state.messages }));
        return;
      }

      res.writeHead(404, { "Content-Type": "application/json", ...corsHeaders });
      res.end(JSON.stringify({ error: "not found" }));
    } catch (e) {
      log("HTTP error:", e.message);
      res.writeHead(500, { "Content-Type": "application/json", ...corsHeaders });
      res.end(JSON.stringify({ error: e.message }));
    }
  });

  // WebSocket upgrade
  httpServer.on("upgrade", async (req, socket) => {
    const url = new URL(req.url, `http://localhost`);
    if (url.pathname !== "/ws") {
      socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
      socket.destroy();
      return;
    }

    const agentName = url.searchParams.get("agent");
    const sessionId = url.searchParams.get("session");
    const folder = url.searchParams.get("folder");

    if (!agentName) {
      socket.write("HTTP/1.1 400 Bad Request\r\n\r\n");
      socket.destroy();
      return;
    }

    const agents = loadAgents();
    const agent = agents[agentName];
    if (!agent) {
      socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
      socket.destroy();
      return;
    }

    socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n");

    const send = (data) => {
      const json = JSON.stringify(data);
      const payload = Buffer.from(json);
      const frame = Buffer.alloc(2 + payload.length);
      frame[0] = 0x81;
      frame[1] = payload.length;
      payload.copy(frame, 2);
      socket.write(frame);
    };

    let sub;
    try {
      if (sessionId) {
        const data = loadSession(sessionId);
        if (data) sub = resumeSession(data);
      }
      if (!sub) {
        if (folder) process.chdir(folder);
        sub = await createAgent(agent);
      }
      connections.set(socket, { agent: sub, sessionId: sub.state.id });
      send({ type: "connected", sessionId: sub.state.id, agent: agentName, folder: folder || process.cwd() });
    } catch (e) {
      send({ type: "error", error: e.message });
      socket.end();
      return;
    }

    socket.on("data", async (data) => {
      try {
        const opcode = data[0] & 0x0f;
        if (opcode === 0x08) { socket.end(); return; }
        if (opcode !== 0x01 && opcode !== 0x02) return;

        const masked = data[1] & 0x80;
        let payloadLen = data[1] & 0x7f;
        let offset = 2;
        if (payloadLen === 126) { payloadLen = data.readUInt16BE(2); offset = 4; }
        else if (payloadLen === 127) { payloadLen = data.readUInt32BE(2) * 0x100000000 + data.readUInt32BE(6); offset = 10; }

        let payload = data.slice(offset, offset + payloadLen);
        if (masked) {
          const mask = data.slice(offset, offset + 4);
          offset += 4;
          payload = data.slice(offset, offset + payloadLen);
          for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        }

        const msg = JSON.parse(payload.toString());

        if (msg.type === "message" && msg.content) {
          const onToken = (token) => send({ type: "token", content: token });
          const originalHandler = sub.onToken;
          sub.onToken = onToken;

          try {
            await sub.turn(msg.content);
            saveSession(sub.state);
            send({ type: "done" });
          } catch (e) {
            send({ type: "error", error: e.message });
          } finally {
            sub.onToken = originalHandler;
          }
        }
      } catch (e) {
        send({ type: "error", error: e.message });
      }
    });

    socket.on("close", () => connections.delete(socket));
    socket.on("error", (err) => { log("WebSocket error:", err.message); connections.delete(socket); });
  });

  return {
    httpServer,
    listen: (host, port) => new Promise((resolve, reject) => {
      httpServer.listen(port, host, () => {
        log(`server listening on http://${host}:${port}`);
        resolve();
      });
      httpServer.on("error", reject);
    }),
    close: () => new Promise((resolve) => {
      for (const [socket] of connections) socket.end();
      httpServer.close(resolve);
    }),
  };
}

// ============================================================================
// MAIN ENTRY: tim start [--tailscale]
// ============================================================================

export async function start({ tailscale = false } = {}) {
  setAutoAccept(true);

  let bindHost = "0.0.0.0";
  
  if (tailscale) {
    if (!hasTailscaleCLI()) {
      log("⚠ tailscale CLI not found");
      log("  Install: https://tailscale.com/download");
    } else {
      const tsIp = getTailscaleIP();
      if (tsIp) {
        bindHost = tsIp;
        log(`tailscale IP detected: ${tsIp}`);
      } else {
        const status = getTailscaleStatus();
        if (status) {
          log("⚠ tailscale running but no 100.x IP found");
        } else {
          log("⚠ tailscale not logged in — run: tailscale up");
        }
      }
    }
  }

  const server = await createHttpServer();
  await server.listen(bindHost, DEFAULT_PORT);

  const schedulerHandle = startScheduler();

  const shutdown = (sig) => {
    log(`received ${sig} — shutting down`);
    clearInterval(schedulerHandle);
    server.close().then(() => process.exit(0));
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  await new Promise(() => {});
}
