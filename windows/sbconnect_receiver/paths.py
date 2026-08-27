"""Filesystem helpers: real Downloads folder and collision-safe naming."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - only ever runs on Windows
    winreg = None  # type: ignore[assignment]

_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"


def downloads_dir() -> Path:
    """Return the user's actual Downloads folder (handles OneDrive redirection)."""
    if winreg is not None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, _DOWNLOADS_GUID)
                if value:
                    expanded = os.path.expandvars(value)
                    p = Path(expanded)
                    if p.is_absolute():
                        return p
        except Exception:
            pass
    return Path.home() / "Downloads"


def unique_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path inside `directory` for `filename`."""
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name or "received_file"
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    i = 1
    while True:
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1
