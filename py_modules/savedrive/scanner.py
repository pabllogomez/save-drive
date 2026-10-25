"""Find installed Steam and non-Steam games plus configured save paths."""

import re
import struct
from pathlib import Path
from typing import Any

try:
    import decky
    _USER_HOME = Path(decky.DECKY_USER_HOME)
except Exception:
    _USER_HOME = Path.home()

STEAM_DIR = _USER_HOME / ".local" / "share" / "Steam"


def _parse_vdf(data: bytes) -> dict[str, Any]:
    """Minimal recursive text VDF/ACF parser."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace")
    tokens = re.findall(r'"([^"]*)"|(\{|\})', text)
    stack: list[dict | list] = [{}]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t[1] == "{":
            new = {}
            key = tokens[i - 1][0]
            if isinstance(stack[-1], dict):
                stack[-1][key] = new
            else:
                stack[-1].append(new)
            stack.append(new)
            i += 1
        elif t[1] == "}":
            stack.pop()
            i += 1
        else:
            key = t[0]
            i += 1
            if i >= len(tokens):
                break
            nxt = tokens[i]
            if nxt[1] == "{":
                continue
            val = nxt[0]
            if isinstance(stack[-1], dict):
                stack[-1][key] = val
            else:
                stack[-1].append({key: val})
            i += 1
    return stack[0] if stack else {}


def _read_text_vdf(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _parse_vdf(path.read_bytes())


def _steam_users() -> list[str]:
    userdata = STEAM_DIR / "userdata"
    if not userdata.exists():
        return []
    return [d.name for d in userdata.iterdir() if d.is_dir() and d.name.isdigit() and d.name != "0"]


def _library_folders() -> list[Path]:
    """Return all Steam library folders (steamapps paths)."""
    base = STEAM_DIR / "steamapps"
    folders = [base]
    vdf = _read_text_vdf(STEAM_DIR / "steamapps" / "libraryfolders.vdf")
    root = vdf.get("libraryfolders", {})
    for key, section in root.items():
        if isinstance(section, dict):
            p = section.get("path")
            if p:
                folders.append(Path(p) / "steamapps")
    return list(dict.fromkeys(folders))


def _installed_steam_games() -> list[dict]:
    games: list[dict] = []
    seen = set()
    for lib in _library_folders():
        if not lib.exists():
            continue
        for acf in lib.glob("appmanifest_*.acf"):
            data = _read_text_vdf(acf)
            appstate = data.get("AppState", {})
            appid = appstate.get("appid")
            name = appstate.get("name")
            if not appid or appid in seen:
                continue
            seen.add(appid)
            games.append({
                "id": f"steam_{appid}",
                "appid": appid,
                "name": name or f"Steam app {appid}",
                "source": "steam",
            })
    return games


def _read_shortcuts_vdf(path: Path) -> list[dict]:
    """Parse binary shortcuts.vdf."""
    if not path.exists():
        return []
    data = path.read_bytes()
    pos = 0

    def read_cstring() -> str:
        nonlocal pos
        end = data.index(b"\x00", pos)
        s = data[pos:end].decode("utf-8", errors="replace")
        pos = end + 1
        return s

    def parse_section() -> dict:
        nonlocal pos
        result: dict[str, Any] = {}
        while pos < len(data):
            t = data[pos]
            pos += 1
            if t == 0x08:
                break
            key = read_cstring()
            if t == 0x00:
                result[key] = read_cstring()
            elif t == 0x01:
                result[key] = struct.unpack("<I", data[pos:pos + 4])[0]
                pos += 4
            elif t == 0x02:
                pos += 4
            elif t == 0x04:
                result[key] = parse_section()
            elif t in (0x05, 0x06, 0x07):
                pos += 8
            else:
                break
        return result

    if pos >= len(data) or data[pos] != 0x04:
        return []
    pos += 1
    key = read_cstring()
    if key != "shortcuts":
        return []
    root = parse_section()
    return list(root.values())


def _non_steam_games() -> list[dict]:
    users = _steam_users()
    if not users:
        return []
    shortcuts_path = STEAM_DIR / "userdata" / users[0] / "config" / "shortcuts.vdf"
    entries = _read_shortcuts_vdf(shortcuts_path)
    games = []
    for entry in entries:
        appid = entry.get("appid") or entry.get("appID") or entry.get("AppID")
        name = entry.get("AppName") or entry.get("appname") or f"Non-Steam {appid}"
        if not appid:
            continue
        games.append({
            "id": f"nonsteam_{appid}",
            "appid": str(appid),
            "name": name,
            "source": "non-steam",
        })
    return games


def _compatdata_prefix(appid: str) -> Path | None:
    for lib in _library_folders():
        pfx = lib / "compatdata" / appid / "pfx"
        if pfx.exists():
            return pfx
    return None


def discover_games() -> list[dict]:
    games = _installed_steam_games() + _non_steam_games()
    games.sort(key=lambda g: g["name"].lower())
    return games


def resolve_paths(game: dict, game_paths: dict) -> list[Path]:
    """Return concrete local save paths for a game."""
    gid = game["id"]
    configured = game_paths.get(gid, [])
    if configured:
        return [Path(p) for p in configured if p]

    paths: list[Path] = []
    if game["source"] == "steam":
        for uid in _steam_users():
            p = STEAM_DIR / "userdata" / uid / game["appid"]
            if p.exists():
                paths.append(p)

    pfx = _compatdata_prefix(game["appid"])
    if pfx and pfx.exists():
        paths.append(pfx)

    return paths
