// REPL interface - handles user input, multi-line mode, and dispatches to agent.

import readline from "node:readline";
import fs from "node:fs";
import path from "node:path";
import { agentTurn, getModel, getSessionId } from "./agent.js";
import { Interrupted } from "./streaming.js";
import { isCommand, runCommand } from "./commands.js";
import { setReadline } from "./permissions.js";
import * as ui from "./ui.js";

// --- Auto-detect attachments in text --------------------------------------

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]);
const PDF_EXT = ".pdf";

const extractAttachments = (text) => {
  const images = [];
  const pdfs = [];
  // Match quoted paths and bare paths (including spaces in quotes)
  const pathRegex = /"([^"]+\.(?:png|jpg|jpeg|gif|webp|bmp|pdf))"|'([^']+\.(?:png|jpg|jpeg|gif|webp|bmp|pdf))'|(\S+\.(?:png|jpg|jpeg|gif|webp|bmp|pdf))/gi;

  let match;
  const found = new Set();
  while ((match = pathRegex.exec(text)) !== null) {
    const filePath = match[1] || match[2] || match[3];
    if (found.has(filePath.toLowerCase())) continue;
    found.add(filePath.toLowerCase());

    // Resolve relative to cwd (remove escapes from drag-drop)
    const resolved = path.resolve(filePath.replace(/\\/g, ''));
    if (!fs.existsSync(resolved)) continue;

    const ext = path.extname(resolved).toLowerCase();
    if (IMAGE_EXTS.has(ext)) {
      images.push(resolved);
    } else if (ext === PDF_EXT) {
      pdfs.push(resolved);
    }
  }

  // Remove the paths from the text
  let cleaned = text;
  for (const p of found) {
    const escaped = p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    cleaned = cleaned.replace(new RegExp(`["']?${escaped}["']?`, 'gi'), ' ');
  }
  cleaned = cleaned.replace(/\s+/g, ' ').trim();

  return { text: cleaned, images, pdfs };
};

// --- REPL state ------------------------------------------------------------

let rl = null;
let currentAbort = null;
let lastSigintAt = 0;

let buffer = [];
let inHeredoc = false;
let flushTimer = null;
const FLUSH_DELAY_MS = 50; // debounce for paste detection

const flushBuffer = () => {
  const joined = buffer.join("\n");
  buffer = [];
  return joined.trim();
};

const safePrompt = () => {
  if (rl && !rl.closed) rl.prompt();
};

// --- Input processing ------------------------------------------------------

const processInput = async (initialAttachments = null) => {
  const rawInput = flushBuffer();
  if (!rawInput) return safePrompt();

  // Extract any image/pdf paths from the input
  const { text: input, images, pdfs } = extractAttachments(rawInput);

  // Merge with any attachments from CLI args
  const allAttachments = {
    images: [...(initialAttachments?.images || []), ...images],
    pdfs: [...(initialAttachments?.pdfs || []), ...pdfs],
  };

  if (input === "exit" || input === "quit") {
    ui.exitHint(getSessionId());
    process.exit(0);
  }
  if (isCommand(input)) {
    await runCommand(input);
    return safePrompt();
  }

  // Show detected attachments
  if (allAttachments.images.length || allAttachments.pdfs.length) {
    const all = [...allAttachments.images, ...allAttachments.pdfs].map(p => path.basename(p));
    ui.info(`attached: ${all.join(", ")}`);
  }

  await handle(input, allAttachments);
};

const handle = async (input, attachments) => {
  currentAbort = new AbortController();
  try {
    await agentTurn(input, currentAbort.signal, attachments);
  } catch (e) {
    if (e instanceof Interrupted || e?.name === "AbortError") {
      console.log();
      ui.info("interrupted");
      console.log();
    } else {
      ui.error(e.message);
    }
  } finally {
    currentAbort = null;
    safePrompt();
  }
};

// --- Event handlers --------------------------------------------------------

const handleSigint = () => {
  if (currentAbort && !currentAbort.signal.aborted) {
    currentAbort.abort();
    return;
  }
  const now = Date.now();
  if (now - lastSigintAt < 1500) {
    console.log();
    ui.info("bye.");
    ui.exitHint(getSessionId());
    process.exit(0);
  }
  lastSigintAt = now;
  console.log();
  ui.info("press Ctrl+C again to exit");
  safePrompt();
};

const setupLineHandler = (initialAttachments) => {
  rl.on("line", async (line) => {
    // heredoc mode: collect until closing """
    if (inHeredoc) {
      if (line.trim() === '"""') {
        inHeredoc = false;
        const input = flushBuffer();
        if (input) await processInput(initialAttachments);
        else safePrompt();
        return;
      }
      buffer.push(line);
      return;
    }

    // entering heredoc mode
    if (line.trim() === '"""') {
      inHeredoc = true;
      return;
    }

    // explicit line continuation with backslash
    if (line.endsWith("\\")) {
      buffer.push(line.slice(0, -1));
      return;
    }

    buffer.push(line);

    // debounced flush: if more lines arrive quickly (paste), we wait
    clearTimeout(flushTimer);
    flushTimer = setTimeout(() => processInput(initialAttachments), FLUSH_DELAY_MS);
  });
};

// --- Public API ------------------------------------------------------------

export function startRepl(initialAttachments = null) {
  rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: ui.prompt(),
  });
  setReadline(rl);

  // readline auto-closes on SIGINT unless the interface has its own listener
  process.on("SIGINT", handleSigint);
  rl.on("SIGINT", handleSigint);
  rl.on("close", () => process.exit(0));

  ui.banner(getModel(), process.cwd());
  setupLineHandler(initialAttachments);
  safePrompt();

  return rl;
}

export function stopRepl() {
  if (rl) {
    rl.close();
    rl = null;
  }
}
