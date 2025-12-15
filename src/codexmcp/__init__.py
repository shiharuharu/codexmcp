"""CodexMCP - MCP Server for Codex CLI.

This package provides an MCP (Model Context Protocol) server that wraps
the Codex CLI, allowing AI assistants to execute coding tasks.
"""

__version__ = "0.8.0"

from .config import LiveEventKind, get_logger, env_truthy
from .formatters import format_event, truncate_text, extract_session_id, extract_agent_message
from .sinks import CodexOutputSinks
from .shell import run_shell_command, windows_escape
from .server import mcp, codex, run

__all__ = [
    "__version__",
    # Config
    "LiveEventKind",
    "get_logger",
    "env_truthy",
    # Formatters
    "format_event",
    "truncate_text",
    "extract_session_id",
    "extract_agent_message",
    # Sinks
    "CodexOutputSinks",
    # Shell
    "run_shell_command",
    "windows_escape",
    # Server
    "mcp",
    "codex",
    "run",
]
