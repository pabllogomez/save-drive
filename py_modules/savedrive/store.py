"""Settings and credentials persistence using Decky's recommended paths."""

import json
import os
from pathlib import Path
from typing import Any

try:
    import decky
    _SETTINGS_DIR = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
    _RUNTIME_DIR = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
    _LOG_DIR = Path(decky.DECKY_PLUGIN_LOG_DIR)
except Exception:
    _home = Path.home()
    _SETTINGS_DIR = _home / ".local" / "share" / "savedrive" / "settings"
    _RUNTIME_DIR = _home / ".local" / "share" / "savedrive" / "runtime"
    _LOG_DIR = _home / ".local" / "share" / "savedrive" / "logs"

for d in (_SETTINGS_DIR, _RUNTIME_DIR, _LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = _SETTINGS_DIR / "settings.json"
CREDENTIALS_FILE = _SETTINGS_DIR / "credentials.json"

DEFAULT_SETTINGS = {
    "retention_count": 5,
    "min_interval_hours": 4,
    "enabled_games": {},
    "last_backup_ts": 0,
    "drive_root_name": "SaveDrive",
    "game_paths": {},
}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def load_settings() -> dict:
    data = load_json(SETTINGS_FILE, {})
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    save_json(SETTINGS_FILE, settings)


def load_credentials() -> dict:
    return load_json(CREDENTIALS_FILE, {}) or {}


def save_credentials(creds: dict) -> None:
    save_json(CREDENTIALS_FILE, creds)


def runtime_path(*parts: str) -> Path:
    return _RUNTIME_DIR.joinpath(*parts)
