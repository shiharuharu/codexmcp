"""GUI log viewer for CodexMCP (best-effort).

This module provides a standalone GUI viewer for Codex CLI events.
It reads newline-delimited JSON from stdin and displays formatted output
in a scrollable tkinter window with syntax highlighting.

This module is designed to run standalone without requiring the full
codexmcp package dependencies (like mcp).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
from typing import Dict, List

# Support both package and standalone imports
try:
    from .config import (
        VIEW_QUEUE_MAX_SIZE,
        QUEUE_POLL_INTERVAL_MS,
        FINAL_FLUSH_DELAY_MS,
        WINDOW_CLOSE_DELAY_MS,
        DEFAULT_MAX_CHARS,
        DEFAULT_MAX_LINES,
        env_truthy,
        get_logger,
    )
    from .formatters import format_event_rich, RichLine, TextTag
except ImportError:
    # Running standalone - add parent directory to path and import directly
    _parent = os.path.dirname(os.path.abspath(__file__))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)

    from config import (  # type: ignore
        VIEW_QUEUE_MAX_SIZE,
        QUEUE_POLL_INTERVAL_MS,
        FINAL_FLUSH_DELAY_MS,
        WINDOW_CLOSE_DELAY_MS,
        DEFAULT_MAX_CHARS,
        DEFAULT_MAX_LINES,
        env_truthy,
        get_logger,
    )
    from formatters import format_event_rich, RichLine, TextTag  # type: ignore

__all__ = ["main"]

logger = get_logger("codexmcp.live_view")


# =============================================================================
# Color Scheme Configuration (Dark Theme)
# =============================================================================

# Background and base colors
BG_COLOR = "#1E1E1E"  # VS Code-like dark background
FG_COLOR = "#D4D4D4"  # Default foreground
SELECTION_BG = "#264F78"  # Selection background
CURSOR_COLOR = "#AEAFAD"  # Cursor color

# Text tag colors - designed for readability on dark background
# User preference: User input = bright, Tool calls = dim, Reasoning = gray, Output = near white
TAG_COLORS: Dict[str, Dict[str, str]] = {
    # Basic tags
    TextTag.TIMESTAMP: {"foreground": "#5A5A5A"},  # Dim gray for timestamps
    TextTag.SESSION: {"foreground": "#4EC9B0"},  # Cyan/Teal for session info
    TextTag.CONTEXT: {"foreground": "#7A7A7A"},  # Muted gray for context
    TextTag.DEFAULT: {"foreground": "#A0A0A0"},  # Medium gray default
    TextTag.LABEL: {"foreground": "#569CD6"},  # Blue for labels
    TextTag.SEPARATOR: {"foreground": "#4A4A4A"},  # Very dim for separators
    TextTag.ERROR: {"foreground": "#F44747"},  # Bright red for errors
    TextTag.SERVER: {"foreground": "#4FC1FF"},  # Sky blue for server info

    # Message roles
    TextTag.USER: {"foreground": "#7CFC00"},  # Bright lime green - PROMINENT
    TextTag.ASSISTANT: {"foreground": "#F5F5F5"},  # Near white - FINAL OUTPUT
    TextTag.PROMPT: {"foreground": "#7CFC00"},  # Same bright green as USER

    # Codex exec item types
    TextTag.REASONING: {"foreground": "#8B8B8B"},  # Medium gray - THINKING
    TextTag.TOOL_CALL: {"foreground": "#6A6A6A"},  # Dim gray - TOOL CALL (subdued)
    TextTag.TOOL_OUTPUT: {"foreground": "#5A5A5A"},  # Even dimmer - TOOL OUTPUT
    TextTag.COMMAND: {"foreground": "#CE9178"},  # Salmon - command text
    TextTag.COMMAND_OUTPUT: {"foreground": "#6A9955"},  # Muted green - command output
    TextTag.FILE_CHANGE: {"foreground": "#DCDCAA"},  # Yellow - file changes
    TextTag.MCP_CALL: {"foreground": "#C586C0"},  # Purple - MCP tool calls
    TextTag.WEB_SEARCH: {"foreground": "#9CDCFE"},  # Light blue - web search
    TextTag.TODO_LIST: {"foreground": "#B5CEA8"},  # Light green - todo items

    # Turn status
    TextTag.TURN_INFO: {"foreground": "#808080"},  # Gray - turn info
    TextTag.USAGE: {"foreground": "#6A6A6A"},  # Dim gray - token usage

    # Compact mode indicators
    TextTag.SUCCESS: {"foreground": "#89D185"},  # Green checkmark
    TextTag.DIM: {"foreground": "#5A5A5A"},  # Dim text for counts/summaries
}

# Font configuration
FONT_FAMILY = "Monaco" if sys.platform == "darwin" else "Consolas"
FONT_SIZE = 12


def _run() -> int:
    """Main entry point for the GUI viewer."""
    parser = argparse.ArgumentParser(description="GUI log viewer for CodexMCP")
    parser.add_argument("--title", default="CodexMCP Live Output")
    parser.add_argument(
        "--file",
        default="",
        help="Optional rollout JSONL file to view (offline). If omitted, read from stdin.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep window open after EOF instead of auto-closing.",
    )
    args = parser.parse_args()

    # Import tkinter lazily to allow headless usage
    try:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
        from tkinter import font as tkfont
    except ImportError as e:
        logger.error(f"tkinter not available: {e}")
        return 2

    logger.debug(f"Starting live view: title={args.title}, file={args.file or 'stdin'}")

    # Create window with dark theme
    root = tk.Tk()
    root.title(args.title)
    root.configure(bg=BG_COLOR)

    # Configure font
    try:
        text_font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE)
    except tk.TclError:
        text_font = tkfont.Font(family="TkFixedFont", size=FONT_SIZE)

    # Create text widget with dark theme
    text = ScrolledText(
        root,
        height=40,
        width=120,
        wrap="word",
        bg=BG_COLOR,
        fg=FG_COLOR,
        insertbackground=CURSOR_COLOR,
        selectbackground=SELECTION_BG,
        font=text_font,
        borderwidth=0,
        highlightthickness=0,
        padx=10,
        pady=10,
    )
    text.pack(fill="both", expand=True)
    text.configure(state="disabled")

    # Configure text tags for syntax highlighting
    for tag_name, tag_config in TAG_COLORS.items():
        text.tag_configure(tag_name, **tag_config)

    # Configuration - simplified, using defaults
    queue_max_size = VIEW_QUEUE_MAX_SIZE
    incoming: queue.Queue[str | None] = queue.Queue(maxsize=queue_max_size)

    # Only CODEXMCP_VIEW_ALL is configurable (useful for detailed debugging)
    show_all = env_truthy("CODEXMCP_VIEW_ALL")
    keep_open = args.keep_open  # Only via CLI arg
    max_chars = DEFAULT_MAX_CHARS
    max_lines = DEFAULT_MAX_LINES

    # Statistics
    items_received = [0]
    items_dropped = [0]

    def reader() -> None:
        """Background thread that reads input and queues it."""
        if args.file:
            logger.debug(f"Reading from file: {args.file}")
            try:
                with open(args.file, "r", encoding="utf-8") as f:
                    for raw in f:
                        try:
                            incoming.put(raw.rstrip("\n"), timeout=1.0)
                            items_received[0] += 1
                        except queue.Full:
                            items_dropped[0] += 1
                            logger.warning("Queue full, dropping message")
            except OSError as e:
                incoming.put(f'{{"error": "failed to read file: {e}"}}')
        else:
            logger.debug("Reading from stdin")
            for raw in sys.stdin:
                try:
                    incoming.put(raw.rstrip("\n"), timeout=1.0)
                    items_received[0] += 1
                except queue.Full:
                    items_dropped[0] += 1
        incoming.put(None)
        logger.debug(f"Reader finished: received={items_received[0]}, dropped={items_dropped[0]}")

    def render_rich_line(line: RichLine) -> None:
        """Render a RichLine to the text widget with proper tags."""
        for segment_text, tag in line.segments:
            text.insert("end", segment_text, tag)
        text.insert("end", "\n")

    def render_items(items: List[str]) -> None:
        """Render multiple items to the text widget (batched for performance)."""
        if not items:
            return

        from datetime import datetime
        now_ts = datetime.now().strftime("%H:%M:%S")

        all_rich_lines: List[RichLine] = []
        for item in items:
            if not item:
                continue
            try:
                event = json.loads(item)
                if isinstance(event, dict):
                    rich_lines = format_event_rich(
                        event,
                        max_chars=max_chars,
                        max_lines=max_lines,
                        show_all=show_all,
                    )
                    # Add timestamp to first line of each event
                    if rich_lines:
                        first_line = rich_lines[0]
                        ts_line = RichLine().add(f"[{now_ts}] ", TextTag.TIMESTAMP)
                        ts_line.segments.extend(first_line.segments)
                        rich_lines[0] = ts_line
                    all_rich_lines.extend(rich_lines)
                else:
                    all_rich_lines.append(RichLine().add(f"[{now_ts}] ", TextTag.TIMESTAMP).add(str(event), TextTag.DEFAULT))
            except json.JSONDecodeError:
                all_rich_lines.append(RichLine().add(f"[{now_ts}] ", TextTag.TIMESTAMP).add(item, TextTag.DEFAULT))

        # Batch update the widget
        if all_rich_lines:
            text.configure(state="normal")
            for rich_line in all_rich_lines:
                if rich_line:
                    render_rich_line(rich_line)
            text.see("end")
            text.configure(state="disabled")

    def flush_queue() -> None:
        """Process queued items and update display."""
        items_to_render: List[str] = []
        try:
            while True:
                item = incoming.get_nowait()
                if item is None:
                    render_items(items_to_render)
                    root.after(FINAL_FLUSH_DELAY_MS, final_flush)
                    return
                items_to_render.append(item)
        except queue.Empty:
            pass

        render_items(items_to_render)
        root.after(QUEUE_POLL_INTERVAL_MS, flush_queue)

    def final_flush() -> None:
        """Final flush after EOF - ensure all remaining items are displayed."""
        items_to_render: List[str] = []
        try:
            while True:
                item = incoming.get_nowait()
                if item is None:
                    break
                items_to_render.append(item)
        except queue.Empty:
            pass

        render_items(items_to_render)
        logger.debug(f"Final flush complete, items_dropped={items_dropped[0]}")

        if keep_open:
            text.configure(state="normal")
            text.insert("end", "\n")
            text.insert("end", "━━━ EOF ━━━", TextTag.SESSION)
            text.insert("end", "\n")
            if items_dropped[0] > 0:
                text.insert("end", f"[{items_dropped[0]} messages dropped due to queue overflow]", TextTag.ERROR)
                text.insert("end", "\n")
            text.see("end")
            text.configure(state="disabled")
            root.title(f"{args.title} [EOF - Press Ctrl+W or ⌘Q to close]")
        else:
            root.after(WINDOW_CLOSE_DELAY_MS, root.destroy)

    # Start reader thread and event loop
    threading.Thread(target=reader, daemon=True, name="live-view-reader").start()
    root.after(QUEUE_POLL_INTERVAL_MS, flush_queue)
    root.mainloop()

    logger.debug("Live view closed")
    return 0


def main() -> None:
    """Entry point for console script."""
    raise SystemExit(_run())


if __name__ == "__main__":
    main()
