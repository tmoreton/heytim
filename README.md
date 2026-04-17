<p align="center">
<pre>
████████╗ ██╗ ███╗   ███╗
╚══██╔══╝ ██║ ████╗ ████║
   ██║    ██║ ██║╚██╔╝██║
   ██║    ██║ ██║ ╚═╝ ██║
   ╚═╝    ╚═╝ ╚═╝     ╚═╝
</pre>
</p>

<p align="center"><i>the minimalist coding companion</i></p>

<p align="center"><b>~4,210 source lines of JavaScript · ZERO runtime dependencies</b></p>

A minimal, single-developer clone of Claude Code. Runs locally, talks to the Fireworks AI API (Kimi K2.5 Turbo), gives the model file + shell tools, and wraps it in a ReAct loop.

The whole point is to be readable—small enough to understand end-to-end.

---

## Install

```bash
git clone <this-repo> TIM && cd TIM
npm install
npm link                      # installs the `tim` binary globally

# Set API key (one of the following)
export FIREWORKS_API_KEY=...  # add to your shell profile
# OR use /env set FIREWORKS_API_KEY=... inside tim
```

Now `tim` runs from anywhere. `cd` into a project, type `tim`, and you're in a REPL.

---

## Quick Example

```
$ cd ~/my-project
$ tim

you> what does this project do?
tim> · list_files({"path":"."})
     · read_file({"path":"package.json"})
     It's a small Express API...

you> add a /health endpoint
     ⚠ edit_file wants to run: edit src/server.js
     [y]es / [a]lways / [n]o > y
tim> Added GET /health handler.

you> /compact   # summarize history to save tokens
you> ^C^C       # exit
```

---

## How It Works

**ReAct Loop** (`src/react.js`): Stream LLM responses, execute any tool calls, feed results back, repeat until done.

**Tools** (`src/tools/`):
- `list_files`, `read_file`, `edit_file`, `write_file` — filesystem
- `bash` — shell commands with timeout
- `grep`, `glob` — search

**Permissions**: Destructive ops (`edit_file`, `write_file`, `bash`) prompt for confirmation. `[a]lways` allowlists for the session. `/yolo` toggles auto-accept.

**Context**: Loads `~/.tim/TIM.md` (global) and `./TIM.md` (project) into the system prompt.

**Sessions**: Auto-saved to `~/.tim/sessions/`. Resume with `tim --resume [id]`.

---

## Project Layout

```
src/
├── index.js      # entry: REPL, slash commands, multi-line input
├── react.js      # ReAct loop, streaming, token tracking
├── agents.js     # load sub-agent profiles from .tim/agents/*.md
├── llm.js        # Fireworks API + SSE parser
├── ui.js         # ANSI colors, spinner, markdown
├── commands.js   # /help, /clear, /compact, /yolo, /plan, etc
├── config.js     # loads TIM.md files
├── permissions.js# confirm prompts, auto-accept, plan mode
├── paths.js      # TIM_SOURCE_ROOT + self-edit guard helpers
├── history.js    # snapshot $TIM_DIR edits before write
├── session.js    # save/load sessions
└── tools/        # fs, bash, search tools
```

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | list commands |
| `/clear` | new session |
| `/compact` | summarize history |
| `/tokens` | token usage |
| `/sessions` | list saved sessions |
| `/yolo` | toggle auto-accept |
| `/exit` | quit |

---

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `FIREWORKS_API_KEY` | *(required)* | API key |
| `TIM_MODEL` | `accounts/fireworks/routers/kimi-k2p5-turbo` | model ID |
| `TIM_CONTEXT_LIMIT` | `128000` | context window (for `/compact` warning) |

---

## Image & PDF Input

Drag and drop files or paste paths:

```
you> /Users/me/screenshot.png what does this show?
     attached: screenshot.png
```
