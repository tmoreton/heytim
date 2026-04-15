#!/usr/bin/env node
// Entry point - parses CLI args, sets up the REPL, handles Ctrl+C interrupt.
// Delegates commands to commands.js, chat to agent.js.

import readline from "node:readline";
import fs from "node:fs";
import path from "node:path";
import {
  agentTurn,
  getModel,
  resumeSession,
  getSessionId,
} from "./agent.js";
import { Interrupted } from "./streaming.js";
import { isCommand, runCommand } from "./commands.js";
import { load as loadSession, latest } from "./session.js";
import { setReadline, setAutoAccept } from "./permissions.js";
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

    // Resolve relative to cwd
    const resolved = path.resolve(filePath.replace(/\\/g, '')); // remove escapes
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

// --- argv handling ---
const argv = process.argv.slice(2);

// Extract attachments from argv
const attachments = { images: [], pdfs: [] };
for (let i = argv.length - 1; i >= 0; i--) {
  if (argv[i] === "--image" && argv[i + 1]) {
    attachments.images.push(argv[i + 1]);
    argv.splice(i, 2);
  } else if (argv[i] === "--pdf" && argv[i + 1]) {
    attachments.pdfs.push(argv[i + 1]);
    argv.splice(i, 2);
  }
}

// Validate attachment files exist
for (const img of attachments.images) {
  if (!fs.existsSync(img)) {
    console.error(`image not found: ${img}`);
    process.exit(1);
  }
}
for (const pdf of attachments.pdfs) {
  if (!fs.existsSync(pdf)) {
    console.error(`pdf not found: ${pdf}`);
    process.exit(1);
  }
}

if (argv.includes("--list")) {
  await runCommand("/sessions");
  process.exit(0);
}
if (argv.includes("--yolo")) {
  setAutoAccept(true);
  ui.info("⚠ auto-accept ON (--yolo) — edits and bash run without prompting");
}

const resumeIdx = argv.indexOf("--resume");
if (resumeIdx !== -1) {
  const id = argv[resumeIdx + 1];
  const data = id ? loadSession(id) : latest();
  if (!data) {
    console.error("no session to resume");
    process.exit(1);
  }
  resumeSession(data);
  ui.success(`resumed ${data.id} (${(data.messages || []).length} messages)`);
}

// --- REPL ---
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  prompt: ui.prompt(),
});
setReadline(rl);

let currentAbort = null;
let lastSigintAt = 0;

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

// readline auto-closes on SIGINT unless the interface has its own listener —
// register on both so Ctrl+C mid-stream doesn't kill the REPL.
process.on("SIGINT", handleSigint);
rl.on("SIGINT", handleSigint);
rl.on("close", () => process.exit(0));

const safePrompt = () => {
  if (!rl.closed) rl.prompt();
};

let buffer = [];
let inHeredoc = false;
let flushTimer = null;
const FLUSH_DELAY_MS = 50; // debounce for paste detection

const flushBuffer = () => {
  const joined = buffer.join("\n");
  buffer = [];
  return joined.trim();
};

const processInput = async () => {
  const rawInput = flushBuffer();
  if (!rawInput) return safePrompt();

  // Extract any image/pdf paths from the input
  const { text: input, images, pdfs } = extractAttachments(rawInput);

  if (input === "exit" || input === "quit") {
    ui.exitHint(getSessionId());
    process.exit(0);
  }
  if (isCommand(input)) {
    await runCommand(input);
    return safePrompt();
  }

  // Show detected attachments
  if (images.length || pdfs.length) {
    const all = [...images, ...pdfs].map(p => path.basename(p));
    ui.info(`attached: ${all.join(", ")}`);
  }

  await handle(input, { images, pdfs });
};

ui.banner(getModel(), process.cwd());
safePrompt();

rl.on("line", async (line) => {
  // heredoc mode: collect until closing """
  if (inHeredoc) {
    if (line.trim() === '"""') {
      inHeredoc = false;
      const input = flushBuffer();
      if (input) await handle(input);
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
  flushTimer = setTimeout(processInput, FLUSH_DELAY_MS);
});

async function handle(input, extraAttachments = null) {
  currentAbort = new AbortController();
  try {
    // Merge any extra attachments detected in REPL input
    const allAttachments = extraAttachments
      ? { images: extraAttachments.images, pdfs: extraAttachments.pdfs }
      : { images: [], pdfs: [] };
    await agentTurn(input, currentAbort.signal, allAttachments);
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
}
