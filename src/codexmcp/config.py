"""Configuration constants and logging setup for CodexMCP.

This module provides centralized configuration for the entire package,
including timing constants, queue sizes, and logging configuration.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Set

__all__ = [
    # Event types
    "LiveEventKind",
    "CodexExecEventType",
    "CodexExecItemType",
    # Timing constants
    "UI_STARTUP_WAIT_SECONDS",
    "UI_QUEUE_PUT_TIMEOUT",
    "UI_QUEUE_DRAIN_TIMEOUT",
    "UI_THREAD_JOIN_TIMEOUT",
    "UI_PROCESS_WAIT_TIMEOUT",
    "PROCESS_EXIT_GRACE_SECONDS",
    # Queue sizes
    "UI_QUEUE_MAX_SIZE",
    "VIEW_QUEUE_MAX_SIZE",
    # Display limits
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MAX_LINES",
    # GUI timing
    "QUEUE_POLL_INTERVAL_MS",
    "FINAL_FLUSH_DELAY_MS",
    "WINDOW_CLOSE_DELAY_MS",
    # Helpers
    "env_truthy",
    "get_logger",
    # Truthy values
    "TRUTHY_VALUES",
]

# =============================================================================
# Event Types
# =============================================================================

class LiveEventKind:
    """Event type constants for live output streaming."""
    SERVER_START = "server_start"
    REQUEST_START = "request_start"
    REQUEST_END = "request_end"
    CODEX_EVENT = "codex_event"
    CODEX_RAW = "codex_raw"


class CodexExecEventType:
    """Top-level event types from `codex exec --json` output.

    Reference: codex-rs/exec/src/exec_events.rs
    """
    THREAD_STARTED = "thread.started"
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    ITEM_STARTED = "item.started"
    ITEM_UPDATED = "item.updated"
    ITEM_COMPLETED = "item.completed"
    ERROR = "error"


class CodexExecItemType:
    """ThreadItem types from `codex exec --json` output.

    Reference: codex-rs/exec/src/exec_events.rs, sdk/typescript/src/items.ts
    """
    AGENT_MESSAGE = "agent_message"
    REASONING = "reasoning"
    COMMAND_EXECUTION = "command_execution"
    FILE_CHANGE = "file_change"
    MCP_TOOL_CALL = "mcp_tool_call"
    WEB_SEARCH = "web_search"
    TODO_LIST = "todo_list"
    ERROR = "error"


# =============================================================================
# Timing Constants (seconds)
# =============================================================================

UI_STARTUP_WAIT_SECONDS = 0.15
UI_QUEUE_PUT_TIMEOUT = 0.1
UI_QUEUE_DRAIN_TIMEOUT = 2.0
UI_THREAD_JOIN_TIMEOUT = 2.0
UI_PROCESS_WAIT_TIMEOUT = 2.0
PROCESS_EXIT_GRACE_SECONDS = 2.0


# =============================================================================
# Queue Sizes (hardcoded - no env config needed)
# =============================================================================

UI_QUEUE_MAX_SIZE = 2000
VIEW_QUEUE_MAX_SIZE = 5000


# =============================================================================
# Display Limits
# =============================================================================

DEFAULT_MAX_CHARS = 6000
DEFAULT_MAX_LINES = 120


# =============================================================================
# GUI Timing (milliseconds)
# =============================================================================

QUEUE_POLL_INTERVAL_MS = 50
FINAL_FLUSH_DELAY_MS = 100
WINDOW_CLOSE_DELAY_MS = 200


# =============================================================================
# Environment Variable Helpers
# =============================================================================

TRUTHY_VALUES: Set[str] = {"1", "true", "yes", "y", "on"}


def env_truthy(name: str) -> bool:
    """Check if an environment variable is set to a truthy value.

    Args:
        name: Environment variable name

    Returns:
        True if the value is in TRUTHY_VALUES (case-insensitive)
    """
    value = os.environ.get(name, "")
    return value.strip().lower() in TRUTHY_VALUES


# =============================================================================
# Logging Configuration
# =============================================================================

_LOGGERS: dict[str, logging.Logger] = {}


def get_logger(name: str = "codexmcp") -> logging.Logger:
    """Get or create a configured logger.

    Args:
        name: Logger name (default: "codexmcp")

    Returns:
        Configured logger instance
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        log_level = os.environ.get("CODEXMCP_LOG_LEVEL", "WARNING").upper()
        logger.setLevel(getattr(logging, log_level, logging.WARNING))

        # Create stderr handler
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _LOGGERS[name] = logger
    return logger
