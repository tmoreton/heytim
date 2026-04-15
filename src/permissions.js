import { warn, confirmPrompt } from "./ui.js";

const sessionAllow = new Set();
let sharedRl = null;

export const setReadline = (rl) => {
  sharedRl = rl;
};

const keyFor = (tool, args) => {
  if (tool === "bash") {
    const cmd = (args.command || "").trim().split(/\s+/)[0] || "";
    return `bash:${cmd}`;
  }
  return tool;
};

const ask = (question) =>
  new Promise((resolve) => {
    if (!sharedRl) {
      resolve("n");
      return;
    }
    sharedRl.question(question, (answer) => {
      resolve(answer.trim().toLowerCase());
    });
  });

export async function confirm(tool, args, preview) {
  const key = keyFor(tool, args);
  if (sessionAllow.has(key)) return true;

  warn(tool, preview);
  const answer = await ask(confirmPrompt());

  if (answer === "a" || answer === "always") {
    sessionAllow.add(key);
    return true;
  }
  return answer === "y" || answer === "yes" || answer === "";
}
