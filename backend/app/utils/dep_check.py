
"""Startup dependency checker.

Verifies that optional but important packages are installed.
Prints a clear, actionable warning for anything missing — the app
continues running with reduced functionality rather than crashing.
"""

from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Dependency manifest ───────────────────────────────────────────────────────
# Each entry: (import_name, pip_package_name, skills_that_need_it, critical)
# critical=True  → log ERROR and suggest fix prominently
# critical=False → log WARNING only

@dataclass
class _Dep:
    import_name:  str
    pip_name:     str
    used_by:      str
    critical:     bool = False


_OPTIONAL_DEPS: list[_Dep] = [
    _Dep("bs4",        "beautifulsoup4>=4.12.3", "shopping_price_compare, shopping_deal_finder, shopping_price_alert, learning_course_search", critical=True),
    _Dep("requests",   "requests>=2.31.0",        "shopping_*, learning_course_search, learning_explain", critical=True),
    _Dep("yt_dlp",     "yt-dlp>=2024.1.0",        "learning_course_search",  critical=False),
    _Dep("playwright", "playwright>=1.49.0",       "browser_agent",           critical=False),
    _Dep("googlemaps", "googlemaps>=4.10.0",       "maps, places skills",     critical=False),
    _Dep("cv2",        "opencv-python>=4.8.0",     "gesture_control",         critical=False),
    _Dep("mediapipe",  "mediapipe>=0.10.0",        "gesture_control",         critical=True),
]


def check_dependencies() -> list[str]:
    """
    Check all optional dependencies.  Returns a list of missing pip package names.
    Logs a WARNING for each missing package and a consolidated ERROR with the
    install command if any critical packages are absent.
    """
    missing_critical: list[str] = []
    missing_optional: list[str] = []

    for dep in _OPTIONAL_DEPS:
        try:
            importlib.import_module(dep.import_name)
        except ImportError:
            if dep.critical:
                missing_critical.append(dep.pip_name)
                logger.error(
                    "Missing required package '%s' (needed by: %s). "
                    "Run: pip install \"%s\"",
                    dep.import_name, dep.used_by, dep.pip_name,
                )
            else:
                missing_optional.append(dep.pip_name)
                logger.warning(
                    "Optional package '%s' not installed (needed by: %s). "
                    "Run: pip install \"%s\"",
                    dep.import_name, dep.used_by, dep.pip_name,
                )

    all_missing = missing_critical + missing_optional

    if missing_critical:
        install_cmd = "pip install " + " ".join(f'"{p}"' for p in missing_critical)
        logger.error(
            "\n"
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  JARVIS — MISSING DEPENDENCIES                               ║\n"
            "║                                                              ║\n"
            "║  Some skills will not work until you install:                ║\n"
            "║                                                              ║\n"
            "║  %s\n"
            "║                                                              ║\n"
            "║  The server will continue with limited functionality.        ║\n"
            "╚══════════════════════════════════════════════════════════════╝",
            install_cmd.ljust(62),
        )

    return all_missing


def require(import_name: str, pip_name: str) -> None:
    """
    Raise a clear ImportError with install instructions if *import_name* is missing.
    Use this inside skill execute() methods for a user-friendly error message.

    Example:
        from app.utils.dep_check import require
        require("bs4", "beautifulsoup4")
    """
    try:
        importlib.import_module(import_name)
    except ImportError:
        raise ImportError(
            f"Missing package '{import_name}'. "
            f"Install it with:  pip install \"{pip_name}\""
        ) from None
