"""Output sink management for CodexMCP.

This module handles streaming output to multiple destinations:
- Log files (JSONL format)
- Stderr (for debugging)
- GUI viewer (via subprocess stdin pipe)
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from .config import (
    LiveEventKind,
    UI_STARTUP_WAIT_SECONDS,
    UI_QUEUE_PUT_TIMEOUT,
    UI_THREAD_JOIN_TIMEOUT,
    UI_PROCESS_WAIT_TIMEOUT,
    UI_QUEUE_MAX_SIZE,
    env_truthy,
    get_logger,
)

__all__ = ["CodexOutputSinks"]

logger = get_logger("codexmcp.sinks")


class CodexOutputSinks:
    """Manages output sinks for live Codex event streaming.

    This class handles writing events to multiple destinations:
    - Log file (JSONL format)
    - Stderr (for debugging)
    - GUI viewer (via subprocess stdin pipe)

    Usage:
        sinks = CodexOutputSinks.from_env(title="My Viewer")
        sinks.write_json({"type": "event", "data": "..."})
        sinks.close()  # Or let atexit handle it
    """

    _GLOBAL: "CodexOutputSinks | None" = None
    _GLOBAL_LOCK = threading.Lock()

    def __init__(self) -> None:
        self._file: Any = None
        self._file_path: str | None = None
        self._ui_proc: subprocess.Popen[str] | None = None
        self._ui_queue: queue.Queue[str | None] | None = None
        self._ui_thread: threading.Thread | None = None
        self._stderr = False
        self._ui_requested = False
        self._ui_debug = False
        self._write_lock = threading.Lock()
        self._closed = False
        self._dropped_messages = 0

    @classmethod
    def from_env(cls, *, title: str) -> "CodexOutputSinks":
        """Create or return the singleton instance configured from environment.

        Environment variables:
            CODEXMCP_LOG_LEVEL: Set to DEBUG to enable stderr output and UI debug
            CODEXMCP_LIVE_UI: Enable GUI viewer
            CODEXMCP_LOG_FILE: Log file path (or "auto" for temp file)

        Args:
            title: Window title for the GUI viewer

        Returns:
            The singleton CodexOutputSinks instance
        """
        with cls._GLOBAL_LOCK:
            if cls._GLOBAL is not None:
                return cls._GLOBAL
            sinks = cls()

        # Use LOG_LEVEL=DEBUG to enable stderr and UI debug output
        is_debug = os.environ.get("CODEXMCP_LOG_LEVEL", "").upper() == "DEBUG"
        sinks._stderr = is_debug
        sinks._ui_debug = is_debug

        want_ui = env_truthy("CODEXMCP_LIVE_UI")
        sinks._ui_requested = want_ui

        # Configure log file
        log_file = os.environ.get("CODEXMCP_LOG_FILE", "").strip()
        if want_ui and not log_file:
            log_file = "auto"

        if log_file:
            if log_file.lower() == "auto":
                log_file = os.path.join(
                    tempfile.gettempdir(),
                    f"codexmcp-codex-{uuid.uuid4().hex}.jsonl",
                )
            sinks._file_path = log_file
            try:
                sinks._file = open(log_file, "a", encoding="utf-8")
                logger.info(f"Live log file opened: {sinks._file_path}")
            except OSError as e:
                logger.error(f"Failed to open log file {log_file}: {e}")
                sinks._file = None
                sinks._file_path = None

        # Start UI if requested
        if want_ui:
            sinks._start_ui(title=title)
            if sinks._ui_proc is None:
                logger.warning(
                    "Live UI unavailable (tkinter missing or headless); "
                    f"log_file={sinks._file_path or 'none'}"
                )

        # Register cleanup on exit
        atexit.register(sinks.close)

        cls._GLOBAL = sinks
        return cls._GLOBAL

    def _find_python_with_tkinter(self) -> str:
        """Find a Python interpreter that has tkinter available."""
        # Check current Python first
        try:
            import tkinter  # noqa: F401
            logger.debug(f"Current Python has tkinter: {sys.executable}")
            return sys.executable
        except ImportError:
            logger.debug("Current Python lacks tkinter, searching alternatives...")

        # Try common system Python paths
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, "miniforge3/bin/python"),
            os.path.join(home, "miniconda3/bin/python"),
            os.path.join(home, "anaconda3/bin/python"),
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
            shutil.which("python3"),
            shutil.which("python"),
        ]

        for candidate in candidates:
            if not candidate or not os.path.isfile(candidate):
                continue
            try:
                result = subprocess.run(
                    [candidate, "-c", "import tkinter"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    logger.debug(f"Found Python with tkinter: {candidate}")
                    return candidate
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.debug(f"Failed to check {candidate}: {e}")
                continue

        logger.warning("No Python with tkinter found, using current interpreter")
        return sys.executable

    def _start_ui(self, *, title: str) -> None:
        """Start the GUI viewer subprocess."""
        python_exe = self._find_python_with_tkinter()
        live_view_path = Path(__file__).parent / "live_view.py"

        try:
            proc = subprocess.Popen(
                [python_exe, str(live_view_path), "--title", title],
                stdin=subprocess.PIPE,
                stdout=None if self._ui_debug else subprocess.DEVNULL,
                stderr=None if self._ui_debug else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            logger.debug(f"Live UI launched: python={python_exe} pid={proc.pid}")
        except OSError as e:
            logger.error(f"Failed to launch live UI: {e}")
            return

        # Check if viewer started successfully
        time.sleep(UI_STARTUP_WAIT_SECONDS)
        if proc.poll() is not None:
            logger.warning(f"Live UI exited immediately with code {proc.returncode}")
            return

        self._ui_proc = proc
        self._ui_queue = queue.Queue(maxsize=UI_QUEUE_MAX_SIZE)
        logger.info(f"Live UI started (pid={proc.pid}, queue_size={UI_QUEUE_MAX_SIZE})")

        def writer() -> None:
            """Background thread that writes queued messages to UI stdin."""
            assert self._ui_queue is not None
            try:
                while True:
                    item = self._ui_queue.get()
                    if item is None:
                        logger.debug("Writer thread received shutdown signal")
                        break
                    if self._ui_proc is None or self._ui_proc.stdin is None:
                        logger.debug("Writer thread: UI process gone")
                        break
                    try:
                        self._ui_proc.stdin.write(item + "\n")
                        self._ui_proc.stdin.flush()
                    except (BrokenPipeError, OSError) as e:
                        logger.debug(f"Writer thread pipe error: {e}")
                        break
            finally:
                try:
                    if self._ui_proc and self._ui_proc.stdin:
                        self._ui_proc.stdin.close()
                except OSError:
                    pass
                logger.debug("Writer thread exited")

        self._ui_thread = threading.Thread(
            target=writer,
            daemon=True,
            name="codexmcp-ui-writer",
        )
        self._ui_thread.start()

    def write_json(self, obj: Dict[str, Any]) -> None:
        """Serialize object to JSON and write to all sinks."""
        try:
            line = json.dumps(obj, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize object to JSON: {e}")
            line = str(obj)
        self.write_line(line)

    def write_line(self, line: str) -> None:
        """Write a line to all enabled sinks."""
        if self._closed:
            return

        with self._write_lock:
            # Write to stderr
            if self._stderr:
                try:
                    print(line, file=sys.stderr, flush=True)
                except OSError:
                    pass

            # Write to log file
            if self._file is not None:
                try:
                    self._file.write(line + "\n")
                    self._file.flush()
                except OSError as e:
                    logger.debug(f"Failed to write to log file: {e}")

            # Write to UI queue
            if self._ui_queue is not None:
                try:
                    self._ui_queue.put(line, timeout=UI_QUEUE_PUT_TIMEOUT)
                except queue.Full:
                    self._dropped_messages += 1
                    if self._dropped_messages == 1 or self._dropped_messages % 100 == 0:
                        logger.warning(
                            f"UI queue full, messages dropped (total: {self._dropped_messages})"
                        )
                except OSError:
                    pass

    def enabled(self) -> bool:
        """Check if any output sink is enabled."""
        return bool(self._ui_requested or self._stderr or self._file_path)

    def banner(self) -> None:
        """Write server startup banner to sinks."""
        if not self.enabled():
            return
        self.write_json({
            "codexmcp": "live",
            "kind": LiveEventKind.SERVER_START,
            "ts": time.time(),
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "python": sys.version.split()[0],
        })

    def close(self) -> None:
        """Clean up all resources."""
        if self._closed:
            return
        self._closed = True

        logger.debug("Closing output sinks...")

        # Signal writer thread to exit
        if self._ui_queue is not None:
            try:
                self._ui_queue.put(None, timeout=0.5)
            except (queue.Full, OSError):
                pass

        # Wait for writer thread
        if self._ui_thread is not None:
            self._ui_thread.join(timeout=UI_THREAD_JOIN_TIMEOUT)
            if self._ui_thread.is_alive():
                logger.warning("Writer thread did not exit in time")

        # Wait for UI process
        if self._ui_proc is not None:
            try:
                self._ui_proc.wait(timeout=UI_PROCESS_WAIT_TIMEOUT)
                logger.debug(f"UI process exited with code {self._ui_proc.returncode}")
            except subprocess.TimeoutExpired:
                logger.warning("UI process did not exit in time, killing")
                try:
                    self._ui_proc.kill()
                    self._ui_proc.wait(timeout=1)
                except OSError:
                    pass

        # Close log file
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
                logger.debug(f"Log file closed: {self._file_path}")
            except OSError as e:
                logger.warning(f"Error closing log file: {e}")
            self._file = None

        if self._dropped_messages > 0:
            logger.info(f"Total dropped messages: {self._dropped_messages}")

    def status(self) -> Dict[str, Any]:
        """Return current status of all sinks."""
        return {
            "ui_requested": self._ui_requested,
            "ui_started": self._ui_proc is not None,
            "ui_debug": self._ui_debug,
            "stderr_enabled": self._stderr,
            "log_file": self._file_path or "",
            "dropped_messages": self._dropped_messages,
        }
