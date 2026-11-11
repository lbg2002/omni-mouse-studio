"""UI entrypoints for Delux M618XSD (on-demand Full 3D Studio + minimal System Tray)."""

from __future__ import annotations


def run_gui() -> int:
    from .app import run_gui as _run_gui

    return _run_gui()


def run_tray() -> int:
    from .tray import run_tray as _run_tray

    return _run_tray()


__all__ = ["run_gui", "run_tray"]
