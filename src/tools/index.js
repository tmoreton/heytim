// Tool registry - exports all tools and their OpenAI-compatible schemas.
// Each tool has: schema (OpenAI function spec) and run(args, ctx) function.

import { listFiles, readFile, editFile, writeFile } from "./fs.js";
import { bash } from "./bash.js";
import { grep, glob } from "./search.js";
import { spawnAgent } from "./spawn.js";
import { webSearch, webFetch } from "./web.js";
import { generateImage } from "./generate_image.js";

export const tools = {
  list_files: listFiles,
  read_file: readFile,
  edit_file: editFile,
  write_file: writeFile,
  bash,
  grep,
  glob,
  spawn_agent: spawnAgent,
  web_search: webSearch,
  web_fetch: webFetch,
  generate_image: generateImage,
};

export const toolSchemas = Object.values(tools).map((t) => t.schema);
