"""Shell command execution for CodexMCP.

This module provides functions to execute shell commands and stream their output,
with proper process management and cleanup.
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from typing import Generator

from .config import PROCESS_EXIT_GRACE_SECONDS, env_truthy, get_logger

__all__ = ["run_shell_command", "windows_escape"]

logger = get_logger("codexmcp.shell")


def run_shell_command(cmd: list[str]) -> Generator[str, None, None]:
    """Execute a command and stream its output line-by-line.

    This function runs a shell command in a subprocess and yields output lines
    as they become available. It handles process termination and cleanup.

    Args:
        cmd: Command and arguments as a list (e.g., ["codex", "exec", "prompt"])

    Yields:
        Output lines from the command (without trailing newlines)

    Raises:
        FileNotFoundError: If the codex command is not found in PATH

    Example:
        for line in run_shell_command(["codex", "exec", "--json", "--", "hello"]):
            print(line)
    """
    popen_cmd = cmd.copy()
    codex_path = shutil.which("codex")

    # Check if codex is available
    if codex_path is None:
        raise FileNotFoundError(
            "Codex CLI not found. Please install it first:\n"
            "  npm install -g @openai/codex\n"
            "Or visit: https://github.com/openai/codex"
        )

    popen_cmd[0] = codex_path
    logger.debug(f"Running command: {popen_cmd[0]}")

    process = subprocess.Popen(
        popen_cmd,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        encoding="utf-8",
        start_new_session=(os.name != "nt"),
    )

    output_queue: queue.Queue[str | None] = queue.Queue()

    def terminate_process_tree() -> None:
        """Terminate the process and its children."""
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        return
        else:
            process.kill()

    def read_output() -> None:
        """Read process output in a background thread."""
        try:
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    output_queue.put(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        finally:
            try:
                if process.stdout:
                    process.stdout.close()
            except OSError:
                pass
            output_queue.put(None)

    thread = threading.Thread(target=read_output, daemon=True, name="shell-output-reader")
    thread.start()

    # Yield lines while process is running
    process_exited_at: float | None = None
    while True:
        try:
            line = output_queue.get(timeout=0.5)
            if line is None:
                break
            yield line
        except queue.Empty:
            if process.poll() is not None:
                if process_exited_at is None:
                    process_exited_at = time.time()
                # Grace period for reading remaining output
                if time.time() - process_exited_at >= PROCESS_EXIT_GRACE_SECONDS:
                    try:
                        if process.stdout:
                            process.stdout.close()
                    except OSError:
                        pass
                    try:
                        if thread.is_alive():
                            terminate_process_tree()
                    finally:
                        break
            elif not thread.is_alive():
                break

    # Final cleanup
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        terminate_process_tree()
        process.wait()
    thread.join(timeout=5)

    # Drain remaining items
    while not output_queue.empty():
        try:
            line = output_queue.get_nowait()
            if line is not None:
                yield line
        except queue.Empty:
            break

    logger.debug(f"Command finished with code {process.returncode}")


def windows_escape(prompt: str) -> str:
    """Escape special characters for Windows command line.

    Note: When using subprocess.Popen(shell=False), Python handles argument
    escaping automatically. Manual escaping may cause double-escaping issues.
    This function is kept for compatibility but can be disabled via env var.

    Args:
        prompt: Original prompt string

    Returns:
        Escaped string (or original if escaping is disabled)

    Environment:
        CODEXMCP_DISABLE_WINDOWS_ESCAPE: Set to truthy value to disable
    """
    if env_truthy("CODEXMCP_DISABLE_WINDOWS_ESCAPE"):
        logger.debug("Windows escape disabled via env var")
        return prompt

    # Escape special characters
    result = prompt.replace("\\", "\\\\")
    result = result.replace('"', '\\"')
    result = result.replace("\n", "\\n")
    result = result.replace("\r", "\\r")
    result = result.replace("\t", "\\t")
    result = result.replace("\b", "\\b")
    result = result.replace("\f", "\\f")
    result = result.replace("'", "\\'")

    return result
