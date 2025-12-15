"""FastMCP server implementation for the Codex MCP project.

This module provides the MCP server that wraps the Codex CLI,
allowing AI assistants to execute coding tasks via the Model Context Protocol.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .config import LiveEventKind, get_logger
from .formatters import extract_session_id, extract_agent_message
from .shell import run_shell_command, windows_escape
from .sinks import CodexOutputSinks

__all__ = ["mcp", "codex", "run"]

logger = get_logger("codexmcp.server")

# =============================================================================
# MCP Server Instance
# =============================================================================

mcp = FastMCP("Codex MCP Server-from guda.studio")


# =============================================================================
# MCP Tool: codex
# =============================================================================

@mcp.tool(
    name="codex",
    description="""
    Executes a non-interactive Codex session via CLI to perform AI-assisted coding tasks in a secure workspace.
    This tool wraps the `codex exec` command, enabling model-driven code generation, debugging, or automation based on natural language prompts.
    It supports resuming ongoing sessions for continuity and enforces sandbox policies to prevent unsafe operations. Ideal for integrating Codex into MCP servers for agentic workflows, such as code reviews or repo modifications.

    **Key Features:**
        - **Prompt-Driven Execution:** Send task instructions to Codex for step-by-step code handling.
        - **Workspace Isolation:** Operate within a specified directory, with optional Git repo skipping.
        - **Security Controls:** Three sandbox levels balance functionality and safety.
        - **Session Persistence:** Resume prior conversations via `SESSION_ID` for iterative tasks.

    **Edge Cases & Best Practices:**
        - Ensure `cd` exists and is accessible; tool fails silently on invalid paths.
        - For most repos, prefer "read-only" to avoid accidental changes.
        - If needed, set `return_all_messages` to `True` to parse "all_messages" for detailed tracing (e.g., reasoning, tool calls, etc.).
    """,
    meta={"version": "0.0.0", "author": "guda.studio"},
)
async def codex(
    PROMPT: Annotated[str, "Instruction for the task to send to codex."],
    cd: Annotated[Path, "Set the workspace root for codex before executing the task."],
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"],
        Field(description="Sandbox policy for model-generated commands. Defaults to `read-only`."),
    ] = "read-only",
    SESSION_ID: Annotated[
        str,
        "Resume the specified session of the codex. Defaults to `None`, start a new session.",
    ] = "",
    skip_git_repo_check: Annotated[
        bool,
        "Allow codex running outside a Git repository (useful for one-off directories).",
    ] = True,
    return_all_messages: Annotated[
        bool,
        "Return all messages (e.g. reasoning, tool calls, etc.) from the codex session. Set to `False` by default, only the agent's final reply message is returned.",
    ] = False,
    image: Annotated[
        List[Path],
        Field(description="Attach one or more image files to the initial prompt."),
    ] = [],
    model: Annotated[
        str,
        Field(description="The model to use for the codex session. This parameter is strictly prohibited unless explicitly specified by the user."),
    ] = "",
    yolo: Annotated[
        bool,
        Field(description="Run every command without approvals or sandboxing. Only use when `sandbox` couldn't be applied."),
    ] = False,
    profile: Annotated[
        str,
        "Configuration profile name to load from `~/.codex/config.toml`. This parameter is strictly prohibited unless explicitly specified by the user.",
    ] = "",
) -> Dict[str, Any]:
    """Execute a Codex CLI session and return the results."""
    # Build command
    cmd = ["codex", "exec", "--sandbox", sandbox, "--cd", str(cd), "--json"]

    if image:
        cmd.extend(["--image", ",".join(str(p) for p in image)])
    if model:
        cmd.extend(["--model", model])
    if profile:
        cmd.extend(["--profile", profile])
    if yolo:
        cmd.append("--yolo")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    if SESSION_ID:
        cmd.extend(["resume", str(SESSION_ID)])

    # Apply Windows escaping if needed
    prompt = windows_escape(PROMPT) if os.name == "nt" else PROMPT
    cmd += ["--", prompt]

    # Initialize state
    all_messages: list[Dict[str, Any]] = []  # All agent_message items when return_all_messages=True
    last_agent_message = ""  # Last agent_message text when return_all_messages=False
    err_message = ""
    session_id: Optional[str] = None
    had_any_output = False

    # Setup output sinks
    sinks = CodexOutputSinks.from_env(title="CodexMCP Live Output")
    request_id = uuid.uuid4().hex[:12]

    logger.debug(f"Starting codex request {request_id}: cd={cd}, sandbox={sandbox}")

    # Log request start
    if sinks.enabled():
        sinks.write_json({
            "codexmcp": "live",
            "kind": LiveEventKind.REQUEST_START,
            "ts": time.time(),
            "req_id": request_id,
            "cd": str(cd),
            "sandbox": sandbox,
            "resume": bool(SESSION_ID),
            "SESSION_ID": str(SESSION_ID) if SESSION_ID else "",
            "prompt": PROMPT,
            "image": [str(p) for p in image] if image else [],
            "model": model,
            "profile": profile,
            "yolo": yolo,
            "skip_git_repo_check": skip_git_repo_check,
        })

    try:
        for line in run_shell_command(cmd):
            if line:
                had_any_output = True
            try:
                line_dict = json.loads(line.strip())

                # Log event
                if sinks.enabled():
                    sinks.write_json({
                        "codexmcp": "live",
                        "kind": LiveEventKind.CODEX_EVENT,
                        "ts": time.time(),
                        "req_id": request_id,
                        "SESSION_ID": session_id or "",
                        "event": line_dict,
                    })

                # Collect agent_message items
                agent_msg = extract_agent_message(line_dict)
                if agent_msg is not None:
                    all_messages.append(agent_msg)
                    # Update last_agent_message (overwrite, keep only last one)
                    text = agent_msg.get("text", "")
                    if isinstance(text, str) and text:
                        last_agent_message = text

                # Extract session ID
                extracted_session_id = extract_session_id(line_dict)
                if extracted_session_id is not None:
                    session_id = extracted_session_id

                # Check for errors
                event_type = line_dict.get("type", "")
                if isinstance(event_type, str) and "fail" in event_type:
                    err_message += "\n\n[codex error] " + line_dict.get("error", {}).get("message", "")
                if isinstance(event_type, str) and "error" in event_type:
                    error_msg = line_dict.get("message", "")
                    is_reconnecting = bool(re.match(r"^Reconnecting\.\.\.\s+\d+/\d+$", error_msg))
                    if not is_reconnecting:
                        err_message += "\n\n[codex error] " + error_msg

            except json.JSONDecodeError:
                if sinks.enabled():
                    sinks.write_json({
                        "codexmcp": "live",
                        "kind": LiveEventKind.CODEX_RAW,
                        "ts": time.time(),
                        "req_id": request_id,
                        "SESSION_ID": session_id or "",
                        "line": line,
                    })
                err_message += "\n\n[json decode error] " + line
                continue
    finally:
        logger.debug(f"Codex request {request_id} completed: output={had_any_output}")
        if sinks.enabled():
            sinks.write_json({
                "codexmcp": "live",
                "kind": LiveEventKind.REQUEST_END,
                "ts": time.time(),
                "req_id": request_id,
                "SESSION_ID": session_id or "",
                "had_any_output": had_any_output,
                "agent_messages_len": len(last_agent_message),
                "errors": err_message.strip(),
            })

    # Build result - keep it minimal for LLM consumption
    if not had_any_output and not all_messages and not err_message:
        return {"success": False, "error": "No output received from codex."}

    result: Dict[str, Any] = {
        "success": True,
        "SESSION_ID": session_id or "",
        "agent_messages": last_agent_message,
    }

    # Only include error if present
    if err_message.strip():
        result["error"] = err_message.strip()

    # Only include all_messages when explicitly requested
    if return_all_messages:
        result["all_messages"] = all_messages

    # Always include log_file path if available (commonly used for debugging)
    live_status = sinks.status()
    if live_status.get("log_file"):
        result["log_file"] = live_status["log_file"]

    # Include full debug info only when LOG_LEVEL=DEBUG
    is_debug = os.environ.get("CODEXMCP_LOG_LEVEL", "").upper() == "DEBUG"
    if is_debug and (live_status.get("ui_requested") or live_status.get("stderr_enabled")):
        result["debug_info"] = {
            "request_id": request_id,
            "live": live_status,
        }

    return result


# =============================================================================
# Server Entry Point
# =============================================================================

def run() -> None:
    """Start the MCP server over stdio transport.

    IMPORTANT: MCP uses stdout for JSON-RPC communication.
    All logging and error output MUST go to stderr to avoid protocol corruption.
    """
    import sys
    import logging
    import io

    # Save original stdout for MCP protocol
    original_stdout = sys.stdout

    # Redirect stdout to stderr temporarily during initialization
    # This prevents any accidental print() or library output from corrupting the protocol
    sys.stdout = sys.stderr

    try:
        # Ensure all loggers output to stderr, not stdout
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream == original_stdout:
                    handler.stream = sys.stderr

        # Initialize output sinks (all output goes to stderr/file/GUI, never stdout)
        sinks = CodexOutputSinks.from_env(title="CodexMCP Live Output")
        sinks.banner()
        logger.info("Starting CodexMCP server...")

    finally:
        # Restore stdout for MCP protocol
        sys.stdout = original_stdout

    # Run MCP server - this takes over stdout for JSON-RPC
    mcp.run(transport="stdio")
