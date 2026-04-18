"""Lightweight command safety checker — deny-list of catastrophically destructive patterns.

This is a defence-in-depth layer on top of Phase 1's explicit confirmation flow.
It does NOT replace confirmation; it blocks commands that should never run regardless
of user intent (e.g. fork bombs, disk formatters, recursive root deletes).

Enable/disable via COMMAND_SAFETY_ENABLED in .env (default: true).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Deny-list ─────────────────────────────────────────────────────────────────
# Each entry is (pattern, human_readable_reason).
# Patterns are matched case-insensitively against the full command string.
# Order matters: more specific patterns first.

_DENY_PATTERNS: list[tuple[str, str]] = [
    # Unix — recursive root delete
    (r"rm\s+.*-[a-z]*r[a-z]*f[a-z]*\s+/(?:\s|$)",   "recursive force-delete of root filesystem"),
    (r"rm\s+.*--no-preserve-root",                    "rm with --no-preserve-root"),
    # Unix — disk formatters
    (r"\bmkfs\b",                                      "filesystem formatter (mkfs)"),
    (r"\bdd\b.*\bif=",                                 "dd with input file (potential disk wipe)"),
    (r"\bdd\b.*\bof=/dev/",                            "dd writing directly to a device"),
    (r">\s*/dev/sd[a-z]",                              "redirect to raw block device"),
    # Unix — permission nuke
    (r"chmod\s+[0-7]*7[0-7]*7\s+/(?:\s|$)",           "chmod 777 on root"),
    # Fork bomb (various spellings)
    (r":\(\)\s*\{",                                    "fork bomb"),
    (r":\s*\(\s*\)\s*\{",                              "fork bomb"),
    # Windows — recursive C:\ delete
    (r"del\s+/[fFsS].*[cC]:\\",                       "Windows recursive delete of C:\\"),
    (r"rd\s+/[sS].*[cC]:\\",                          "Windows rd /s on C:\\"),
    (r"rmdir\s+/[sS].*[cC]:\\",                       "Windows rmdir /s on C:\\"),
    # Windows — disk format
    (r"\bformat\s+[cCdDeEfF]:",                        "Windows disk format"),
    # Shred / wipe utilities
    (r"\bshred\b.*-[a-z]*z[a-z]*\s+/dev/",            "shred on a device"),
    (r"\bwipefs\b",                                    "wipefs (wipe filesystem signatures)"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), reason)
    for pat, reason in _DENY_PATTERNS
]


# ── Public API ────────────────────────────────────────────────────────────────

class BlockedCommandError(ValueError):
    """Raised when a command matches a deny-list pattern."""
    def __init__(self, command: str, reason: str) -> None:
        self.command = command
        self.reason  = reason
        super().__init__(f"Blocked command: {reason!r}")


def check_command(command: str) -> None:
    """
    Raise BlockedCommandError if *command* matches any deny-list pattern.
    Call this before executing any shell command.

    Does nothing if COMMAND_SAFETY_ENABLED is false in settings.
    """
    from app.config import get_settings
    if not get_settings().command_safety_enabled:
        return

    for pattern, reason in _COMPILED:
        if pattern.search(command):
            logger.warning(
                "BLOCKED dangerous command (reason: %s): %s",
                reason, command[:200],
            )
            raise BlockedCommandError(command, reason)
