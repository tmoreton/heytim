// The scheduler loop for `tim start`. Checks all triggers every 30 seconds and
// fires any whose cron schedule matches the current minute (deduped so a
// trigger fires at most once per minute). Runs agents in-process — no forked
// Node processes per fire.
//
// Designed to run as a single long-lived Node process: foreground in a tmux
// session, backgrounded via nohup, or under any supervisor you choose.

import { loadTriggers, getTriggerState, recordRun } from "./triggers.js";
import { matches, sameMinute } from "./cron.js";
import { loadWorkflows, mergeProfile } from "./workflows.js";
import { loadAgents } from "./agents.js";
import { createAgent } from "./react.js";
import { getTools } from "./tools/index.js";
import { setAutoAccept } from "./permissions.js";

const TICK_MS = 30_000;

const ts = () => new Date().toISOString();
const log = (...args) => console.log(`[${ts()}]`, ...args);

// Heuristic: does a tool result indicate "nothing to do"? Used by precheck
// to skip agent invocation when a polling tool returns empty.
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
    // dryRun: true tells stateful polling tools (e.g. receive_email) not to
    // mark items as processed during the precheck — the agent will do that
    // on its own call when it actually handles them.
    const result = await tool.run({ dryRun: true }, { signal: null });
    // Structured count is the source of truth when available (e.g. receive_email
    // returns {emails:[], count:0, content:"No new emails..."} — we'd otherwise
    // mis-read the non-empty `content` string as "has work").
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
    recordRun(trigger.name, {
      startedAt: ts(), finishedAt: ts(), status: "error",
      error: `workflow "${trigger.workflow}" not found`,
    });
    return;
  }
  const agents = loadAgents();
  const agent = agents[workflow.agent];
  if (!agent) {
    log(`✗ ${trigger.name}: agent "${workflow.agent}" (for workflow ${workflow.name}) not found`);
    recordRun(trigger.name, {
      startedAt: ts(), finishedAt: ts(), status: "error",
      error: `agent "${workflow.agent}" not found`,
    });
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
    recordRun(trigger.name, {
      startedAt: started, finishedAt: ts(), status: "error", error: e.message,
    });
  }
}

async function tick() {
  const now = new Date();
  const triggers = loadTriggers();
  for (const t of triggers) {
    if (!t.enabled) continue;
    if (!matches(t.schedule, now)) continue;

    // Dedupe: don't re-fire if we already fired within this same minute.
    const prev = getTriggerState(t.name);
    if (prev?.lastRunAt) {
      const prevDate = new Date(prev.lastRunAt);
      if (sameMinute(prevDate, now)) continue;
    }

    // Precheck: skip firing if there's no work (saves LLM tokens on frequent polls).
    // Precheck lives on the workflow (task-semantic), but a trigger can
    // override. Either one being set is enough to run it.
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

    // Fire sequentially — if two triggers match the same minute, run one after
    // the other rather than in parallel. Keeps log output readable and avoids
    // memory-file write races when two workflows touch the same agent.
    await fireTrigger(t);
  }
}

export async function start() {
  setAutoAccept(true); // headless: no interactive prompts
  const triggers = loadTriggers();
  log(`tim start — ${triggers.length} trigger(s) loaded`);
  for (const t of triggers) {
    log(`  • ${t.name} [${t.schedule}] → ${t.workflow}${t.enabled ? "" : " (disabled)"}`);
  }

  // Run one tick immediately so a just-added trigger fires at the next matching
  // minute without waiting for the first 30s boundary.
  await tick();

  const handle = setInterval(() => {
    tick().catch((e) => log(`tick error: ${e.message}`));
  }, TICK_MS);

  // Graceful shutdown: let the current tick finish before exiting.
  const shutdown = (sig) => {
    log(`received ${sig} — shutting down`);
    clearInterval(handle);
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}
