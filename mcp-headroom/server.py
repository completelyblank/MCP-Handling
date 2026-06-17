"""
mcp-headroom  –  Context-Window Compactor for VS Code Copilot Agent Mode
=========================================================================
Sits between Copilot and your shell as a stdio MCP server.
Runs commands, counts the output tokens with tiktoken, and surgically
trims anything that exceeds the threshold so Copilot never chokes on
walls of repetitive log output.

Tools
-----
  run_compact_command   Run a shell command and return trimmed output.
  compact_text          Compact an already-captured string (no subprocess).
  estimate_savings      Dry-run: show how many tokens would be saved.
"""

from __future__ import annotations

import subprocess
import shlex
import textwrap
from typing import Optional

import tiktoken
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_TOKEN_THRESHOLD = 800   # lines beyond this trigger compaction
HEAD_LINES              = 20    # lines to keep from the top
TAIL_LINES              = 20    # lines to keep from the bottom
ENCODING_NAME           = "cl100k_base"   # GPT-4 / Claude vocab

# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="mcp-headroom",
    instructions=(
        "Use run_compact_command instead of the built-in terminal whenever a "
        "shell command might produce verbose or repetitive output (builds, "
        "installs, test runs, log reads, diagnostics). "
        "The tool automatically trims token-heavy output while preserving "
        "the first and last lines where errors and status messages live. "
        "Use compact_text to trim any text you already have. "
        "Use estimate_savings to preview how much a string would be trimmed "
        "without running any command."
    ),
)

# ---------------------------------------------------------------------------
# Encoder (cached)
# ---------------------------------------------------------------------------
_enc: Optional[tiktoken.Encoding] = None

def _encoder() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding(ENCODING_NAME)
    return _enc

def _token_count(text: str) -> int:
    return len(_encoder().encode(text))

# ---------------------------------------------------------------------------
# Core compactor
# ---------------------------------------------------------------------------
def _compact(text: str, threshold: int = DEFAULT_TOKEN_THRESHOLD) -> tuple[str, int, int]:
    """
    Trim *text* if its token count exceeds *threshold*.

    Returns
    -------
    (compacted_text, original_token_count, saved_token_count)
    """
    original_tokens = _token_count(text)

    if original_tokens <= threshold:
        return text, original_tokens, 0

    lines = text.splitlines()
    total_lines = len(lines)

    head = lines[:HEAD_LINES]
    tail = lines[-TAIL_LINES:]
    omitted_lines = total_lines - HEAD_LINES - TAIL_LINES

    # Build placeholder
    middle_text   = "\n".join(lines[HEAD_LINES : total_lines - TAIL_LINES])
    middle_tokens = _token_count(middle_text)
    placeholder   = (
        f"\n[... Truncated {omitted_lines} lines of repetitive output "
        f"({middle_tokens:,} tokens omitted) ...]\n"
    )

    compacted      = "\n".join(head) + placeholder + "\n".join(tail)
    final_tokens   = _token_count(compacted)
    saved_tokens   = original_tokens - final_tokens

    return compacted, original_tokens, saved_tokens

# ---------------------------------------------------------------------------
# Tool 1: run_compact_command
# ---------------------------------------------------------------------------
@mcp.tool()
def run_compact_command(
    command: str,
    timeout: int = 60,
    token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
    working_dir: Optional[str] = None,
) -> dict:
    """
    Run a shell command, capture its combined stdout + stderr, compact the
    output if it exceeds token_threshold, and return a clean result.

    Prefer this tool over the built-in terminal for any command that may
    produce long or repetitive output: package installs, build systems,
    test runners, log dumps, linters, diagnostics.

    The response always ends with a [Headroom] summary line showing how
    many tokens were saved so you can track context-window efficiency.

    Args:
        command:         Shell command to run (e.g. "npm install", "pytest -v").
        timeout:         Max seconds to wait before killing the process (default 60).
        token_threshold: Token count above which output is compacted (default 800).
        working_dir:     Directory to run the command in (defaults to cwd).

    Returns a dict with:
        output          : str   – compacted (or full) command output
        exit_code       : int
        original_tokens : int
        final_tokens    : int
        tokens_saved    : int
        was_compacted   : bool
        headroom_banner : str   – one-line summary to append to your reply
    """
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )
        raw_output = result.stdout + (
            ("\n--- stderr ---\n" + result.stderr) if result.stderr.strip() else ""
        )
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        raw_output = f"[mcp-headroom] Command timed out after {timeout}s."
        exit_code  = -1
    except FileNotFoundError:
        raw_output = f"[mcp-headroom] Command not found: {command.split()[0]!r}"
        exit_code  = -1
    except Exception as exc:  # noqa: BLE001
        raw_output = f"[mcp-headroom] Unexpected error: {exc}"
        exit_code  = -1

    compacted, orig_tok, saved_tok = _compact(raw_output, threshold=token_threshold)
    final_tok    = orig_tok - saved_tok
    was_compacted = saved_tok > 0

    banner = (
        f"[Headroom Alert: Saved {saved_tok:,} tokens "
        f"({orig_tok:,} → {final_tok:,}) | exit {exit_code}]"
        if was_compacted
        else f"[Headroom: Output within threshold ({orig_tok:,} tokens) | exit {exit_code}]"
    )

    return {
        "output":          compacted + f"\n\n{banner}",
        "exit_code":       exit_code,
        "original_tokens": orig_tok,
        "final_tokens":    final_tok,
        "tokens_saved":    saved_tok,
        "was_compacted":   was_compacted,
        "headroom_banner": banner,
    }

# ---------------------------------------------------------------------------
# Tool 2: compact_text
# ---------------------------------------------------------------------------
@mcp.tool()
def compact_text(
    text: str,
    token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
) -> dict:
    """
    Compact an already-captured block of text (log file contents, copy-pasted
    terminal output, file reads) without running a subprocess.

    Useful when you have fetched a file or piped output and want to trim it
    before including it in context.

    Args:
        text:            The raw text to compact.
        token_threshold: Tokens above which compaction kicks in (default 800).

    Returns:
        output          : str  – compacted text
        original_tokens : int
        final_tokens    : int
        tokens_saved    : int
        was_compacted   : bool
    """
    compacted, orig_tok, saved_tok = _compact(text, threshold=token_threshold)
    final_tok = orig_tok - saved_tok
    return {
        "output":          compacted,
        "original_tokens": orig_tok,
        "final_tokens":    final_tok,
        "tokens_saved":    saved_tok,
        "was_compacted":   saved_tok > 0,
    }

# ---------------------------------------------------------------------------
# Tool 3: estimate_savings
# ---------------------------------------------------------------------------
@mcp.tool()
def estimate_savings(
    text: str,
    token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
) -> dict:
    """
    Dry-run: measure how many tokens the compactor would save on *text*
    without modifying anything or running any command.

    Use this to decide whether it is worth compacting a piece of text,
    or to show the user the before/after numbers in your reply.

    Args:
        text:            Text to analyse.
        token_threshold: Threshold used for the hypothetical compaction.

    Returns:
        original_tokens : int
        estimated_final : int
        estimated_saving: int
        saving_pct      : float  – percentage reduction
        would_compact   : bool
        line_count      : int
    """
    original_tokens = _token_count(text)
    line_count      = text.count("\n") + 1

    if original_tokens <= token_threshold:
        return {
            "original_tokens":  original_tokens,
            "estimated_final":  original_tokens,
            "estimated_saving": 0,
            "saving_pct":       0.0,
            "would_compact":    False,
            "line_count":       line_count,
        }

    _, orig_tok, saved_tok = _compact(text, threshold=token_threshold)
    final_tok  = orig_tok - saved_tok
    saving_pct = round(saved_tok / orig_tok * 100, 1) if orig_tok else 0.0

    return {
        "original_tokens":  orig_tok,
        "estimated_final":  final_tok,
        "estimated_saving": saved_tok,
        "saving_pct":       saving_pct,
        "would_compact":    True,
        "line_count":       line_count,
    }

# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")