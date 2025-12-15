"""Event formatting utilities for CodexMCP.

This module provides functions to format Codex CLI events for display,
used by both the live viewer GUI and the server logging system.

Display Strategy:
- Reasoning/Assistant: Always show fully (streaming is user-friendly)
- Tool calls: Compact by default (name only), verbose with show_all=True
- Commands: Show command, truncate output to 3 lines by default
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Tuple

try:
    from .config import DEFAULT_MAX_CHARS, DEFAULT_MAX_LINES
except ImportError:
    DEFAULT_MAX_CHARS = 6000
    DEFAULT_MAX_LINES = 120

__all__ = [
    "truncate_text", "format_timestamp", "extract_text_content",
    "format_event", "format_event_rich", "extract_session_id",
    "extract_agent_message", "RichLine", "TextTag",
]

# Compact mode limits for tool outputs
COMPACT_MAX_LINES = 3
COMPACT_MAX_CHARS = 300


# =============================================================================
# Text Tags for Styling
# =============================================================================

class TextTag:
    """Tag constants for styled text rendering."""
    TIMESTAMP = "timestamp"
    SESSION = "session"
    CONTEXT = "context"
    DEFAULT = "default"
    LABEL = "label"
    SEPARATOR = "separator"
    ERROR = "error"
    SERVER = "server"
    USER = "user"
    ASSISTANT = "assistant"
    PROMPT = "prompt"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"
    COMMAND = "command"
    COMMAND_OUTPUT = "command_output"
    FILE_CHANGE = "file_change"
    MCP_CALL = "mcp_call"
    WEB_SEARCH = "web_search"
    TODO_LIST = "todo_list"
    TURN_INFO = "turn_info"
    USAGE = "usage"
    # New: for compact indicators
    SUCCESS = "success"
    DIM = "dim"


# =============================================================================
# Configuration
# =============================================================================

_SIMPLE_ITEMS: Dict[str, Tuple[str, str, str, bool]] = {
    "agent_message": ("ASSISTANT", TextTag.ASSISTANT, "text", False),
    "reasoning": ("REASONING", TextTag.REASONING, "text", False),
    "web_search": ("WEB SEARCH ", TextTag.WEB_SEARCH, "query", True),
    "error": ("WARNING ", TextTag.ERROR, "message", True),
}

_ROLE_MAP: Dict[str, Tuple[str, str]] = {
    "user": ("USER", TextTag.USER),
    "assistant": ("ASSISTANT", TextTag.ASSISTANT),
}


# =============================================================================
# RichLine Class
# =============================================================================

@dataclass
class RichLine:
    """A line of text with styling segments."""
    segments: List[Tuple[str, str]] = field(default_factory=list)

    def add(self, text: str, tag: str = TextTag.DEFAULT) -> "RichLine":
        if text:
            self.segments.append((text, tag))
        return self

    def to_plain(self) -> str:
        return "".join(t for t, _ in self.segments)

    def __bool__(self) -> bool:
        return bool(self.segments)


# =============================================================================
# Utility Functions
# =============================================================================

def truncate_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS, max_lines: int = DEFAULT_MAX_LINES, flatten: bool = False) -> str:
    """Truncate text to fit within limits.

    Args:
        flatten: If True, replace newlines with ↵ to show content in single line
    """
    if flatten:
        # Replace newlines with visible marker for compact display
        text = text.replace('\n', ' ↵ ').replace('\r', '')
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars] + "…"
        return text

    if max_lines > 0:
        lines = text.splitlines()
        if len(lines) > max_lines:
            text = "\n".join(lines[:max_lines] + ["…"])
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def format_timestamp(ts: str | None) -> str:
    """Format ISO timestamp to short time string."""
    if not ts:
        return ""
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def extract_text_content(content: Any) -> str:
    """Extract text from various message formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    if isinstance(content, dict):
        t = content.get("text")
        return t if isinstance(t, str) else ""
    return ""


def extract_session_id(event: Dict[str, Any]) -> str | None:
    """Extract session ID from a Codex event."""
    etype = event.get("type")
    if etype == "thread.started":
        v = event.get("thread_id")
        if isinstance(v, str) and v:
            return v
    for key in ("thread_id", "session_id", "SESSION_ID", "threadId", "sessionId"):
        v = event.get(key)
        if isinstance(v, str) and v:
            return v
    payload = event.get("payload")
    if isinstance(payload, dict):
        if etype == "session_meta":
            v = payload.get("id")
            if isinstance(v, str) and v:
                return v
        for key in ("thread_id", "session_id"):
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
    # Check thread object (NOT item - item.id is item identifier, not session)
    thread = event.get("thread")
    if isinstance(thread, dict):
        for key in ("id", "thread_id", "session_id"):
            v = thread.get(key)
            if isinstance(v, str) and v:
                return v
    return None


def extract_agent_message(event: Dict[str, Any]) -> Dict[str, Any] | None:
    """Extract agent_message item from a Codex event if present.

    Returns the agent_message item dict if this is a completed agent_message event,
    otherwise returns None.
    """
    etype = event.get("type")
    if etype == "item.completed":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            return item
    return None


# =============================================================================
# Prefix Helpers
# =============================================================================

def _pfx(sess: str) -> RichLine:
    """Create prefix with session ID."""
    line = RichLine()
    if sess:
        short = sess[-8:] if len(sess) > 8 else sess
        line.add("[", TextTag.SEPARATOR).add(f"#{short}", TextTag.SESSION).add("] ", TextTag.SEPARATOR)
    return line


def _pfx_ts(ts: str, sess: str = "") -> RichLine:
    """Create prefix with session ID and timestamp."""
    line = _pfx(sess)
    if ts:
        line.add(f"[{ts}] ", TextTag.TIMESTAMP)
    return line


# =============================================================================
# Main Entry Points
# =============================================================================

def format_event(event: Dict[str, Any], *, max_chars: int = DEFAULT_MAX_CHARS,
                 max_lines: int = DEFAULT_MAX_LINES, show_all: bool = False) -> List[str]:
    """Format event as plain text."""
    return [line.to_plain() for line in format_event_rich(
        event, max_chars=max_chars, max_lines=max_lines, show_all=show_all
    ) if line]


def format_event_rich(event: Dict[str, Any], *, max_chars: int = DEFAULT_MAX_CHARS,
                      max_lines: int = DEFAULT_MAX_LINES, show_all: bool = False,
                      session_id: str = "") -> List[RichLine]:
    """Format event with styling tags."""
    sess = session_id or extract_session_id(event) or ""
    etype = event.get("type", "")

    if event.get("codexmcp") == "live":
        return _fmt_live(event, max_chars, max_lines, show_all, sess)

    if isinstance(etype, str) and (
        etype.startswith(("thread.", "turn.", "item.")) or etype == "error"
    ):
        return _fmt_exec(event, max_chars, max_lines, show_all, sess)

    return _fmt_codex(event, max_chars, max_lines, show_all, sess)


# =============================================================================
# CodexMCP Live Events
# =============================================================================

def _fmt_live(event: Dict[str, Any], max_chars: int, max_lines: int, show_all: bool, sess: str) -> List[RichLine]:
    kind = event.get("kind")
    sess = sess or event.get("SESSION_ID", "") or event.get("session_id", "")
    trunc = lambda t: truncate_text(t, max_chars=max_chars, max_lines=max_lines)

    if kind == "server_start":
        line = _pfx(sess).add("SERVER START ", TextTag.SERVER)
        line.add(f"pid={event.get('pid')} cwd={event.get('cwd')} py={event.get('python')}", TextTag.DEFAULT)
        return [line]

    if kind == "request_start":
        lines = [_pfx(sess).add("[REQUEST START] ", TextTag.SESSION)
                 .add(f"cd={event.get('cd')} sandbox={event.get('sandbox')} resume={event.get('resume')}", TextTag.DEFAULT)]
        prompt = event.get("prompt")
        if isinstance(prompt, str) and prompt:
            lines.append(_pfx(sess).add("[PROMPT] ", TextTag.LABEL).add(trunc(prompt), TextTag.PROMPT))
        return lines

    if kind == "request_end":
        lines = [_pfx(sess).add("[REQUEST END] ", TextTag.SESSION)
                 .add(f"output={event.get('had_any_output')} agent_len={event.get('agent_messages_len')}", TextTag.DEFAULT)]
        if event.get("errors"):
            lines.append(_pfx(sess).add("[ERRORS] ", TextTag.ERROR).add(trunc(str(event.get("errors") or "")), TextTag.ERROR))
        return lines

    if kind == "codex_event":
        inner = event.get("event")
        if isinstance(inner, dict):
            # Inner event will add its own prefix, don't duplicate
            return format_event_rich(inner, max_chars=max_chars, max_lines=max_lines, show_all=show_all, session_id=sess)
        return [_pfx(sess).add(f"CODEX EVENT {type(inner).__name__}", TextTag.DEFAULT)]

    if kind == "codex_raw":
        return [_pfx(sess).add("CODEX RAW", TextTag.LABEL),
                RichLine().add(trunc(str(event.get("line", ""))), TextTag.DEFAULT)]

    if show_all:
        return [_pfx(sess).add(f"LIVE {kind}: ", TextTag.LABEL)
                .add(trunc(json.dumps(event, ensure_ascii=False)), TextTag.DEFAULT)]
    return []


# =============================================================================
# Standard Codex CLI Events
# =============================================================================

def _fmt_codex(event: Dict[str, Any], max_chars: int, max_lines: int, show_all: bool, sess: str) -> List[RichLine]:
    ts = format_timestamp(event.get("timestamp"))
    etype = event.get("type")
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    sess = sess or extract_session_id(event) or ""
    trunc = lambda t: truncate_text(t, max_chars=max_chars, max_lines=max_lines)

    if etype == "session_meta":
        return [_pfx_ts(ts, sess).add("SESSION ", TextTag.SESSION)
                .add(f"{payload.get('id')} | cwd={payload.get('cwd')} | cli={payload.get('cli_version')} | provider={payload.get('model_provider')}", TextTag.DEFAULT)]

    if etype == "turn_context":
        sb = payload.get("sandbox_policy", {})
        sb_type = sb.get("type") if isinstance(sb, dict) else None
        net = sb.get("network_access") if isinstance(sb, dict) else None
        return [_pfx_ts(ts, sess).add("CONTEXT ", TextTag.CONTEXT)
                .add(f"cwd={payload.get('cwd')} | model={payload.get('model')} | effort={payload.get('effort')} | sandbox={sb_type} | net={net} | approvals={payload.get('approval_policy')}", TextTag.DEFAULT)]

    if etype == "event_msg":
        msg_type = payload.get("type")
        if msg_type == "agent_reasoning":
            text = payload.get("text", "")
            if isinstance(text, str) and text:
                return [_pfx_ts(ts, sess).add("[REASONING] ", TextTag.REASONING).add(trunc(text), TextTag.REASONING)]
        if show_all:
            return [_pfx_ts(ts, sess).add(f"[EVENT {msg_type}] ", TextTag.LABEL)
                    .add(trunc(json.dumps(payload, ensure_ascii=False)), TextTag.DEFAULT)]
        return []

    if etype == "response_item":
        return _fmt_resp_item(payload, ts, max_chars, max_lines, show_all, sess)

    if show_all:
        return [_pfx_ts(ts, sess).add(f"{etype}: ", TextTag.LABEL)
                .add(trunc(json.dumps(event, ensure_ascii=False)), TextTag.DEFAULT)]
    return []


def _fmt_resp_item(payload: Dict[str, Any], ts: str, max_chars: int, max_lines: int, show_all: bool, sess: str) -> List[RichLine]:
    itype = payload.get("type")
    trunc = lambda t: truncate_text(t, max_chars=max_chars, max_lines=max_lines)
    trunc_compact = lambda t: truncate_text(t, max_chars=COMPACT_MAX_CHARS, max_lines=1, flatten=True)

    if itype == "message":
        role = payload.get("role", "")
        text = extract_text_content(payload.get("content"))
        if not text and not show_all:
            return []
        text = trunc(text or json.dumps(payload, ensure_ascii=False))
        label, tag = _ROLE_MAP.get(role, (f"MSG({role})", TextTag.DEFAULT))
        return [_pfx_ts(ts, sess).add(f"[{label}] ", tag).add(text, tag)]

    if itype == "reasoning":
        summary = payload.get("summary", [])
        texts = [p.get("text", "") for p in summary if isinstance(p, dict) and p.get("type") == "summary_text" and p.get("text")]
        lines: List[RichLine] = []
        if texts:
            lines.append(_pfx_ts(ts, sess).add("[REASONING(summary)] ", TextTag.REASONING).add(trunc("\n\n".join(texts)), TextTag.REASONING))
        enc = payload.get("encrypted_content")
        if enc and show_all:
            lines.append(_pfx_ts(ts, sess).add(f"[REASONING(encrypted)] len={len(enc) if isinstance(enc, str) else '?'}", TextTag.REASONING))
        return lines

    # Tool calls - show name + truncated args
    if itype == "function_call":
        name, call_id = payload.get("name", "?"), payload.get("call_id", "")
        line = _pfx_ts(ts, sess).add("[TOOL] ", TextTag.LABEL).add(name, TextTag.TOOL_CALL)
        args_raw = payload.get("arguments", "")
        if isinstance(args_raw, str) and args_raw:
            try:
                args = json.loads(args_raw)
                if isinstance(args, dict) and (args.get("command") is not None or args.get("workdir") is not None):
                    args_text = f"command={args.get('command')!r} workdir={args.get('workdir')!r}"
                else:
                    args_text = json.dumps(args, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                args_text = args_raw
            # Compact: truncate to 3 lines; Verbose: full
            args_text = trunc(args_text) if show_all else trunc_compact(args_text)
            if args_text:
                line.add(" ", TextTag.DEFAULT).add(args_text, TextTag.TOOL_CALL)
        return [line]

    # Tool output - show indicator + truncated output
    if itype == "function_call_output":
        call_id = payload.get("call_id", "")
        output = payload.get("output", "")
        has_error = isinstance(output, str) and "error" in output.lower()
        indicator = "✗" if has_error else "✓"
        indicator_tag = TextTag.ERROR if has_error else TextTag.SUCCESS
        line = _pfx_ts(ts, sess).add("[TOOL] ", TextTag.LABEL).add(indicator, indicator_tag)
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False)
        if output:
            # Compact: truncate to 3 lines; Verbose: full
            out_text = trunc(output) if show_all else trunc_compact(output)
            if out_text:
                line.add(" ", TextTag.DEFAULT).add(out_text, TextTag.TOOL_OUTPUT)
        return [line]

    if show_all:
        return [_pfx_ts(ts, sess).add(f"[ITEM {itype}] ", TextTag.LABEL)
                .add(trunc(json.dumps(payload, ensure_ascii=False)), TextTag.DEFAULT)]
    return []


# =============================================================================
# Codex Exec JSON Format (codex exec --json)
# =============================================================================

def _fmt_exec(event: Dict[str, Any], max_chars: int, max_lines: int, show_all: bool, sess: str) -> List[RichLine]:
    etype = event.get("type", "")
    trunc = lambda t: truncate_text(t, max_chars=max_chars, max_lines=max_lines)

    if etype == "thread.started":
        return [_pfx(sess).add("[THREAD] ", TextTag.SESSION).add(event.get("thread_id", ""), TextTag.DEFAULT)]

    if etype == "turn.started":
        return [_pfx(sess).add("[TURN STARTED]", TextTag.TURN_INFO)] if show_all else []

    if etype == "turn.completed":
        usage = event.get("usage", {})
        if isinstance(usage, dict) and usage:
            return [_pfx(sess).add("[TURN COMPLETED] ", TextTag.TURN_INFO)
                    .add(f"[in={usage.get('input_tokens', 0)} cached={usage.get('cached_input_tokens', 0)} out={usage.get('output_tokens', 0)}]", TextTag.USAGE)]
        return []

    if etype == "turn.failed":
        err = event.get("error", {})
        msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)
        return [_pfx(sess).add("[TURN FAILED] ", TextTag.ERROR).add(msg, TextTag.ERROR)]

    if etype == "error":
        return [_pfx(sess).add("[ERROR] ", TextTag.ERROR).add(event.get("message", "Unknown error"), TextTag.ERROR)]

    if etype in ("item.started", "item.updated", "item.completed"):
        item = event.get("item", {})
        if isinstance(item, dict):
            return _fmt_item(item, etype, sess, max_chars, max_lines, show_all)
        return []

    if show_all:
        return [_pfx(sess).add(f"[{etype}] ", TextTag.LABEL)
                .add(trunc(json.dumps(event, ensure_ascii=False)), TextTag.DEFAULT)]
    return []


def _fmt_item(item: Dict[str, Any], etype: str, sess: str, max_chars: int, max_lines: int, show_all: bool) -> List[RichLine]:
    itype = item.get("type", "")
    status = item.get("status", "")
    is_done = etype == "item.completed"
    trunc = lambda t: truncate_text(t, max_chars=max_chars, max_lines=max_lines)
    trunc_compact = lambda t: truncate_text(t, max_chars=COMPACT_MAX_CHARS, max_lines=1, flatten=True)

    # Simple items via config (reasoning, agent_message shown fully)
    if itype in _SIMPLE_ITEMS:
        label, tag, field, label_only = _SIMPLE_ITEMS[itype]
        text = item.get(field, "")
        if not text and itype not in ("error",):
            return []
        line = _pfx(sess).add(f"[{label}] ", tag)
        if label_only and text:
            line.add(text, TextTag.DEFAULT)
            return [line]
        if text:
            line.add(trunc(text), tag)
        return [line]

    # COMPACT: Command - show command, truncate output
    if itype == "command_execution":
        cmd = item.get("command", "")
        output = item.get("aggregated_output", "")
        exit_code = item.get("exit_code")

        # [COMMAND] label in blue, command text in salmon, output in muted green
        line = _pfx(sess).add("[COMMAND] ", TextTag.LABEL)
        if exit_code is not None:
            indicator = "✓" if exit_code == 0 else f"✗{exit_code}"
            indicator_tag = TextTag.SUCCESS if exit_code == 0 else TextTag.ERROR
            line.add(indicator, indicator_tag).add(" ", TextTag.DEFAULT)
        if cmd:
            line.add(trunc_compact(cmd), TextTag.COMMAND)
        lines = [line]

        if output and is_done:
            # Compact: truncate heavily; Verbose: show full
            out_text = trunc(output) if show_all else trunc_compact(output)
            if out_text:
                lines.append(RichLine().add(out_text, TextTag.COMMAND_OUTPUT))
        return lines

    # COMPACT: File change - show count only
    if itype == "file_change":
        changes = item.get("changes", [])
        if not changes:
            return []
        count = len(changes)
        line = _pfx(sess).add("[FILE] ", TextTag.LABEL)
        if status:
            line.add(f"[{status}] ", TextTag.DIM)
        line.add(f"×{count} files", TextTag.FILE_CHANGE)

        if show_all:
            # Verbose: show file list
            lines = [line]
            for c in changes[:10]:
                if isinstance(c, dict):
                    lines.append(RichLine().add(f"  {c.get('kind', '')}: {c.get('path', '')}", TextTag.FILE_CHANGE))
            return lines
        return [line]

    # MCP call - show server/tool + truncated args/result
    if itype == "mcp_tool_call":
        server, tool = item.get("server", ""), item.get("tool", "")
        error = item.get("error")
        result = item.get("result", {})
        args = item.get("arguments", {})

        line = _pfx(sess).add("[MCP] ", TextTag.LABEL).add(f"{server}/{tool}", TextTag.MCP_CALL)
        if error and isinstance(error, dict):
            line.add(" ✗", TextTag.ERROR)
        elif is_done and result:
            line.add(" ✓", TextTag.SUCCESS)

        lines = [line]

        # Show truncated arguments
        if args:
            args_text = trunc(json.dumps(args, ensure_ascii=False)) if show_all else trunc_compact(json.dumps(args, ensure_ascii=False))
            if args_text:
                lines.append(RichLine().add(args_text, TextTag.MCP_CALL))

        # Show error or truncated result
        if error and isinstance(error, dict):
            lines.append(RichLine().add(f"Error: {error.get('message', '')}", TextTag.ERROR))
        elif result and is_done:
            content = result.get("content", [])
            texts = [b.get("text", "") for b in content[:5] if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                result_text = "\n".join(texts)
                result_text = trunc(result_text) if show_all else trunc_compact(result_text)
                if result_text:
                    lines.append(RichLine().add(result_text, TextTag.TOOL_OUTPUT))
        return lines

    # TODO list - always show full details
    if itype == "todo_list":
        items = item.get("items", [])
        if not items:
            return []
        done = sum(1 for t in items if isinstance(t, dict) and t.get("completed", False))
        total = len(items)
        lines = [_pfx(sess).add("[TODO] ", TextTag.LABEL).add(f"{done}/{total} done", TextTag.DIM)]
        # Always show full todo list (user requirement)
        for t in items[:30]:  # Limit to 30 items max
            if isinstance(t, dict):
                marker = "✓" if t.get("completed", False) else "○"
                lines.append(RichLine().add(f"  {marker} {t.get('text', '')}", TextTag.TODO_LIST))
        return lines

    # Unknown type
    if show_all:
        item_id = item.get("id", "")
        line = _pfx(sess).add(f"[ITEM {itype}] ", TextTag.LABEL)
        if item_id:
            line.add(f"({item_id})", TextTag.DEFAULT)
        return [line, RichLine().add(trunc(json.dumps(item, ensure_ascii=False)), TextTag.DEFAULT)]
    return []
