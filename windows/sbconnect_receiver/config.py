"""Configuration loading/saving and pairing-code generation."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PORT = 45800


def config_dir() -> Path:
    # Use the profile root rather than %APPDATA%: the Microsoft Store Python
    # virtualizes AppData writes into an obscure package folder, which would
    # hide the config/log from the user. The profile root is not virtualized.
    d = Path.home() / ".sbconnect"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def _generate_code(length: int = 6) -> str:
    # No ambiguous characters (0/O, 1/I/L).
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class Config:
    port: int = DEFAULT_PORT
    pairing_code: str = ""
    host: str = "0.0.0.0"

    def save(self) -> None:
        config_path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def load() -> "Config":
        p = config_path()
        cfg = Config()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                cfg = Config(
                    port=int(data.get("port", DEFAULT_PORT)),
                    pairing_code=str(data.get("pairing_code", "")),
                    host=str(data.get("host", "0.0.0.0")),
                )
            except Exception:
                cfg = Config()
        if not cfg.pairing_code:
            cfg.pairing_code = _generate_code()
            cfg.save()
        return cfg
