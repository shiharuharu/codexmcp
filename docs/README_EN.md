![CodexMCP](../images/title.png)

<div align="center">

**Seamlessly Bridge Claude Code and Codex**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT) [![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/) [![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

English | [简体中文](../README.md)

> Fork from [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp) | Refactored by Claude Opus 4.5

</div>

---

## Quick Start

### Prerequisites

- **Claude Code** v2.0.56+
- **Codex CLI** v0.61.0+
- **uv** package manager

### Installation

```bash
# Remove old version (if installed)
claude mcp remove codex

# Install
claude mcp add codex -s user --transport stdio -- uvx --from git+https://github.com/shiharuharu/codexmcp.git codexmcp

# Verify
claude mcp list
```

---

## Environment Variables

Minimalist design with only **4** environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `CODEXMCP_LOG_LEVEL` | Log level, set to `DEBUG` for verbose output | `WARNING` |
| `CODEXMCP_LOG_FILE` | Log file path, `auto` for auto-generated | *(empty)* |
| `CODEXMCP_LIVE_UI` | Enable GUI live viewer | `false` |
| `CODEXMCP_VIEW_ALL` | Show all event details | `false` |

```bash
# Development/Debug mode
CODEXMCP_LOG_LEVEL=DEBUG CODEXMCP_LIVE_UI=1 codexmcp

# Production (zero config)
codexmcp
```

---

## Codex Tool

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|:--------:|---------|-------------|
| `PROMPT` | `str` | ✅ | - | Task instruction |
| `cd` | `Path` | ✅ | - | Working directory |
| `sandbox` | `str` | | `read-only` | Sandbox policy |
| `SESSION_ID` | `str` | | `""` | Resume session ID |
| `return_all_messages` | `bool` | | `false` | Return all agent_message items |
| `image` | `List[Path]` | | `[]` | Attach images |
| `model` | `str` | | `""` | Specify model |
| `yolo` | `bool` | | `false` | No approval mode |
| `profile` | `str` | | `""` | Config profile name |
| `skip_git_repo_check` | `bool` | | `true` | Skip Git check |

### Sandbox Policies

| Policy | Description |
|--------|-------------|
| `read-only` | **Recommended** - Read-only access |
| `workspace-write` | Allow writes to workspace |
| `danger-full-access` | Full access (dangerous) |

### Response Structure

```json
// Normal response
{
  "success": true,
  "SESSION_ID": "sess_abc123",
  "agent_messages": "Last agent reply",
  "log_file": "/tmp/codexmcp-xxx.jsonl"
}

// With return_all_messages=true
{
  "success": true,
  "SESSION_ID": "sess_abc123",
  "agent_messages": "Last agent reply",
  "all_messages": [
    {"type": "agent_message", "text": "First reply..."},
    {"type": "agent_message", "text": "Last reply..."}
  ],
  "log_file": "/tmp/codexmcp-xxx.jsonl"
}

// With LOG_LEVEL=DEBUG (additional fields)
{
  ...,
  "debug_info": {
    "request_id": "abc123",
    "live": { ... }
  }
}
```

---

## GUI Live Monitoring

Enable to display Codex event stream with dark theme + syntax highlighting:

```bash
export CODEXMCP_LIVE_UI=1
```

### Color Scheme

| Type | Color | Example |
|------|-------|---------|
| `[PROMPT]` | 🔵 Blue + 🟢 Bright Green | `[PROMPT] User input` |
| `[ASSISTANT]` | ⚪ Near White | `[ASSISTANT] AI reply` |
| `[COMMAND]` | 🔵 Blue + 🟠 Orange | `[COMMAND] ✓ git status` |
| `[TOOL]` | 🔵 Blue + ⚫ Gray | `[TOOL] Read args...` |
| `[TODO]` | 🔵 Blue + 🟢 Light Green | `[TODO] 2/5 done` |
| `[MCP]` | 🔵 Blue + 🟣 Purple | `[MCP] server/tool ✓` |
| `[ERROR]` | 🔴 Red | `[ERROR] Error message` |

### Display Format

```
[#efgh5678] [THREAD] 019b2293-7741-71f2-bd38-df366ebcd402
[#efgh5678] [COMMAND] ✓ ls -la
[#efgh5678] [TODO] 2/5 done
  ✓ Task 1
  ○ Task 2
  ○ Task 3
[#efgh5678] [ASSISTANT] Here is the result!
[#efgh5678] [TURN COMPLETED] [in=100 cached=50 out=30]
```

---

## Project Structure

```
codexmcp/
├── config.py      # Constants, logging
├── formatters.py  # Event formatting (rich text coloring)
├── sinks.py       # Output management (file, stderr, GUI)
├── shell.py       # Process management
├── live_view.py   # GUI viewer
├── server.py      # MCP Server
└── __init__.py    # Package exports
```

---

## Development

```bash
git clone https://github.com/shiharuharu/codexmcp.git
cd codexmcp
uv sync
uv run python -c "from codexmcp import *; print('OK')"
```

### Test GUI

```bash
# With test data
uv run python -m codexmcp.live_view --file test_events.jsonl --keep-open

# Live monitoring
CODEXMCP_LIVE_UI=1 CODEXMCP_VIEW_ALL=1 codexmcp
```

---

## License

MIT License - Fork from [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp)
