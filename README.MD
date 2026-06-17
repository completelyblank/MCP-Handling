# mcp-headroom

> **Context-Window Compactor for VS Code Copilot Agent Mode**
> Keeps Copilot sharp by surgically trimming verbose terminal output before it floods the context window.

---

## The Problem

Copilot's Agent Mode is powerful, but it suffers from **"Lost in the Middle" syndrome** — when you hand it 500 lines of `npm install` chatter or a wall of compilation logs, the model's attention drifts. The error buried at line 480 gets ignored. Tokens get burned on noise.

`mcp-headroom` sits silently between Copilot and your shell. It runs commands, counts their output tokens with `tiktoken`, and trims anything that exceeds your threshold — keeping the **first 20 lines** (context/intent) and the **last 20 lines** (result/error), replacing the middle with a semantic placeholder:

```
[... Truncated 312 lines of repetitive output (4,218 tokens omitted) ...]
```

---

## Setup

### 1. Create the project and virtual environment

```bash
mkdir mcp-headroom && cd mcp-headroom
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure VS Code

Add `.vscode/mcp.json` to your workspace (already included here):

```json
{
  "servers": {
    "mcp-headroom": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["${workspaceFolder}/server.py"]
    }
  }
}
```

> **Windows users:** change `command` to `"${workspaceFolder}\\.venv\\Scripts\\python.exe"`

### 3. Enable in Copilot Chat

1. Open Copilot Chat (`Ctrl+Alt+I`)
2. Switch to **Agent Mode** (the `@` dropdown → Agent)
3. Click the **🔧 Tools** icon — you should see `mcp-headroom` listed
4. Toggle it **on**

---

## Tools

### `run_compact_command`
Run any shell command. Output above the token threshold is automatically compacted.

```
Copilot prompt:  "Run npm install using run_compact_command and fix any errors"
```

Response always ends with a `[Headroom Alert]` banner:
```
[Headroom Alert: Saved 4,218 tokens (4,891 → 673) | exit 0]
```

| Parameter | Default | Description |
|---|---|---|
| `command` | — | Shell command to run |
| `timeout` | `60` | Kill after N seconds |
| `token_threshold` | `800` | Compact if output exceeds this |
| `working_dir` | cwd | Directory to run in |

---

### `compact_text`
Compact text you already have (log file contents, pasted output).

```
Copilot prompt:  "Compact this log and tell me what went wrong"
```

---

### `estimate_savings`
Dry-run: see how many tokens would be saved without running anything.

---

## How the Compactor Works

```
Raw output (5,000 tokens)
│
├── Lines 1–20      ← kept  (build context, command invocation)
│
├── Lines 21–480    ← REPLACED with:
│   [... Truncated 460 lines (4,218 tokens omitted) ...]
│
└── Lines 481–500   ← kept  (error message, exit status, summary)

Final output: ~680 tokens   Saved: 4,320 tokens
```

The threshold and head/tail line counts are constants at the top of `server.py` — tune them for your workflow.

---

## Token Savings Math

| Scenario | Raw tokens | After compaction | Saved |
|---|---|---|---|
| `npm install` (clean) | ~4,800 | ~650 | ~4,150 |
| `pytest -v` (100 tests) | ~6,200 | ~720 | ~5,480 |
| 1,000-line log file | ~8,500 | ~700 | ~7,800 |

On a complex debugging session with 10 such commands, that's **40,000–70,000 tokens saved** — keeping you well within rate limits and keeping Copilot's attention on what matters.

---

## Test it without Copilot

```bash
# MCP inspector (browser UI)
pip install mcp[cli]
mcp dev server.py

# Or raw JSON-RPC via stdin
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python server.py
```