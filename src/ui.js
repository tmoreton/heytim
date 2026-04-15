// Minimal ANSI-based TUI helpers. No deps.

const SUPPORTS = process.stdout.isTTY && process.env.TERM !== "dumb";

const ESC = "\x1b[";
const RESET = `${ESC}0m`;

const codes = {
  reset: 0,
  bold: 1,
  dim: 2,
  italic: 3,
  underline: 4,
  black: 30,
  red: 31,
  green: 32,
  yellow: 33,
  blue: 34,
  magenta: 35,
  cyan: 36,
  white: 37,
  gray: 90,
};

const wrap = (code, s) => (SUPPORTS ? `${ESC}${code}m${s}${RESET}` : s);

export const c = {};
for (const [name, n] of Object.entries(codes)) c[name] = (s) => wrap(n, s);
c.rgb = (r, g, b, s) =>
  SUPPORTS ? `${ESC}38;2;${r};${g};${b}m${s}${RESET}` : s;

// Teal accent (truecolor). Falls back to cyan on non-truecolor terminals.
c.teal = (s) => c.rgb(20, 184, 166, s);

const lerp = (a, b, t) => Math.round(a + (b - a) * t);
export const gradient = (text, [r1, g1, b1], [r2, g2, b2]) => {
  if (!SUPPORTS) return text;
  const chars = [...text];
  return chars
    .map((ch, i) => {
      if (ch === " ") return ch;
      const t = chars.length === 1 ? 0 : i / (chars.length - 1);
      return c.rgb(lerp(r1, r2, t), lerp(g1, g2, t), lerp(b1, b2, t), ch);
    })
    .join("");
};

// --- Banner ----------------------------------------------------------------

const BANNER = [
  " ████████╗ ██╗ ███╗   ███╗",
  " ╚══██╔══╝ ██║ ████╗ ████║",
  "    ██║    ██║ ██║╚██╔╝██║",
  "    ██║    ██║ ██║ ╚═╝ ██║",
  "    ╚═╝    ╚═╝ ╚═╝     ╚═╝",
];

const START = [13, 148, 136]; // deep teal (teal-600)
const END = [94, 234, 212]; // bright aqua (teal-300)

export function banner(model, cwd) {
  console.log();
  for (const line of BANNER) console.log("  " + gradient(line, START, END));
  console.log();
  console.log(
    "  " +
      gradient("the minimalist coding companion", START, END),
  );
  console.log();
  console.log("  " + c.dim(`model   `) + c.white(model));
  console.log("  " + c.dim(`cwd     `) + c.white(cwd));
  console.log(
    "  " +
      c.dim(`hint    /help for commands · Ctrl+C to interrupt`),
  );
  console.log();
}

// --- Prompt / header -------------------------------------------------------

export const prompt = () => c.bold(c.green("❯ "));
export const header = () => c.bold(gradient("tim", START, END));

// --- Spinner ---------------------------------------------------------------

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function spinner(label = "thinking") {
  if (!SUPPORTS) return { stop() {} };
  let i = 0;
  const render = () => {
    process.stdout.write(
      `\r${c.teal(FRAMES[i++ % FRAMES.length])} ${c.dim(label)}${ESC}K`,
    );
  };
  process.stdout.write(`${ESC}?25l`);
  render();
  const id = setInterval(render, 80);
  return {
    stop() {
      clearInterval(id);
      process.stdout.write(`\r${ESC}K${ESC}?25h`);
    },
  };
}

// --- Tool call + result pretty-printers -----------------------------------

const ARROW = c.teal("⏵");
const RETURN = c.gray("  ↳");

const summarizeArgs = (name, args) => {
  if (!args || typeof args !== "object") return "";
  if (name === "bash") return args.command || "";
  if (args.path && args.old_string !== undefined)
    return `${args.path} ${c.dim("(edit)")}`;
  if (args.path && args.content !== undefined)
    return `${args.path} ${c.dim(`(${args.content.length}b)`)}`;
  if (args.pattern) return `"${args.pattern}"${args.path ? ` in ${args.path}` : ""}`;
  if (args.path) return args.path;
  const j = JSON.stringify(args);
  return j.length > 80 ? j.slice(0, 77) + "..." : j;
};

export function toolCall(name, args) {
  console.log(`${ARROW} ${c.bold(name)} ${c.dim(summarizeArgs(name, args))}`);
}

export function toolResult(result) {
  const s = String(result);
  if (s.startsWith("ERROR:")) {
    console.log(`${RETURN} ${c.red(s.split("\n")[0])}`);
    return;
  }
  const lines = s.split("\n");
  const first = (lines[0] || "").slice(0, 100);
  const suffix =
    lines.length > 1 ? c.dim(` (+${lines.length - 1} lines)`) : "";
  console.log(`${RETURN} ${c.dim(first)}${suffix}`);
}

// --- Status footer / warnings ---------------------------------------------

export function statusFooter({ lastPromptTokens, limit, sessionId, model }) {
  const parts = [];
  if (lastPromptTokens) {
    const pct = Math.round((lastPromptTokens / limit) * 100);
    const color = pct >= 80 ? "yellow" : pct >= 50 ? "white" : "gray";
    parts.push(c[color](`${(lastPromptTokens / 1000).toFixed(1)}k/${(limit / 1000).toFixed(0)}k (${pct}%)`));
  }
  if (sessionId) parts.push(c.dim(`session ${sessionId.slice(0, 19)}`));
  if (model) parts.push(c.dim(model.split("/").pop()));
  if (!parts.length) return;
  console.log(c.dim("  ─ ") + parts.join(c.dim(" · ")));
}

export function warn(tool, preview) {
  console.log();
  console.log(`  ${c.yellow("⚠")}  ${c.bold(tool)} ${c.dim("wants to run:")}`);
  console.log(`     ${c.white(preview)}`);
}

export function confirmPrompt() {
  return `  ${c.dim("[")}${c.green("y")}${c.dim("]es / [")}${c.teal("a")}${c.dim("]lways / [")}${c.red("n")}${c.dim("]o ❯ ")}`;
}

// --- Misc ------------------------------------------------------------------

export const info = (msg) => console.log(c.dim(`  ${msg}`));
export const error = (msg) => console.log(c.red(`  ✗ ${msg}`));
export const success = (msg) => console.log(c.green(`  ✓ ${msg}`));
