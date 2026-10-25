"""Backup/restore engine: zip, hash, upload, retention, restore."""

import hashlib
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import gdrive
from . import scanner
from . import store

try:
    import decky
    logger = decky.logger
except Exception:
    import logging
    logger = logging.getLogger("savedrive")


def _content_hash(path: Path) -> str:
    """Hash determinístico do conteúdo (caminho relativo + tamanho + sha256)."""
    h = hashlib.sha256()
    if not path.exists():
        return ""
    if path.is_file():
        h.update(path.name.encode("utf-8"))
        h.update(str(path.stat().st_size).encode("utf-8"))
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    else:
        for p in sorted(path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(path).as_posix()
                h.update(rel.encode("utf-8"))
                h.update(str(p.stat().st_size).encode("utf-8"))
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
    return h.hexdigest()


def _zip_paths(paths: list[Path], dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in paths:
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, arcname=src.name)
            else:
                for p in sorted(src.rglob("*")):
                    if p.is_file():
                        arc = p.relative_to(src).as_posix()
                        zf.write(p, arcname=arc)


def _ensure_credentials() -> dict:
    creds = store.load_credentials()
    if not creds.get("client_id") or not creds.get("client_secret") or not creds.get("refresh_token"):
        raise RuntimeError("Google Drive not authenticated")
    return creds


def _get_drive(drive: gdrive.GDrive | None = None) -> gdrive.GDrive:
    if drive:
        return drive
    creds = _ensure_credentials()
    tokens = gdrive.refresh_access_token(creds["client_id"], creds["client_secret"], creds["refresh_token"])
    access = tokens.get("access_token")
    if not access:
        raise RuntimeError("Failed to refresh access token")
    return gdrive.GDrive(access)


def list_snapshots(game_id: str) -> list[dict]:
    settings = store.load_settings()
    drive = _get_drive()
    root_id = drive.get_or_create_folder(settings["drive_root_name"])
    folder_id = drive.get_or_create_folder(game_id, root_id)
    files = drive.list_files(folder_id)
    snaps = []
    for f in files:
        name = f.get("name", "")
        if name.endswith(".zip"):
            snaps.append({
                "id": f["id"],
                "name": name,
                "created": f.get("createdTime", ""),
                "size": f.get("size", "0"),
            })
    snaps.sort(key=lambda x: x["name"], reverse=True)
    return snaps


def backup_game(game: dict, drive: gdrive.GDrive | None = None) -> dict:
    settings = store.load_settings()
    paths = scanner.resolve_paths(game, settings.get("game_paths", {}))
    if not paths:
        return {"status": "skipped", "reason": "no paths", "game": game["id"]}

    # hash current state to detect no-op
    hashes = [(_content_hash(p), str(p)) for p in paths]
    state_hash = hashlib.sha256("".join(f"{h}:{p}" for h, p in hashes).encode("utf-8")).hexdigest()

    game_meta = settings.setdefault("game_meta", {})
    last = game_meta.get(game["id"], {})
    if last.get("hash") == state_hash:
        return {"status": "up_to_date", "game": game["id"]}

    # zip
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    zip_name = f"{stamp}.zip"
    tmp = store.runtime_path("uploads")
    tmp.mkdir(parents=True, exist_ok=True)
    local_zip = tmp / f"{game['id']}_{zip_name}"
    _zip_paths(paths, local_zip)

    # upload
    drive = _get_drive(drive)
    root_id = drive.get_or_create_folder(settings["drive_root_name"])
    folder_id = drive.get_or_create_folder(game["id"], root_id)
    file_id = drive.upload_file(local_zip, zip_name, folder_id)

    # retention
    files = drive.list_files(folder_id)
    zips = [f for f in files if f.get("name", "").endswith(".zip")]
    zips.sort(key=lambda x: x["name"], reverse=True)
    keep = max(1, int(settings.get("retention_count", 5)))
    for old in zips[keep:]:
        try:
            drive.delete_file(old["id"])
        except Exception as e:
            logger.warning(f"Failed to delete old snapshot {old['id']}: {e}")

    # cleanup local tmp
    try:
        local_zip.unlink()
    except Exception:
        pass

    # record success
    game_meta[game["id"]] = {
        "hash": state_hash,
        "last_backup": time.time(),
        "last_snapshot": file_id,
    }
    store.save_settings(settings)

    return {"status": "ok", "game": game["id"], "snapshot": file_id, "name": zip_name}


def backup_all(game_filter: list[str] | None = None) -> list[dict]:
    settings = store.load_settings()
    games = scanner.discover_games()
    enabled = settings.get("enabled_games", {})
    results = []
    drive: gdrive.GDrive | None = None

    for game in games:
        gid = game["id"]
        if game_filter and gid not in game_filter:
            continue
        if not enabled.get(gid, False):
            continue
        try:
            if drive is None:
                drive = _get_drive()
            res = backup_game(game, drive)
            results.append(res)
        except Exception as e:
            logger.exception(f"Backup failed for {gid}")
            results.append({"status": "error", "game": gid, "error": str(e)})

    if any(r["status"] in ("ok", "up_to_date") for r in results):
        settings["last_backup_ts"] = time.time()
        store.save_settings(settings)
    return results


def restore_game(game_id: str, snapshot_id: str) -> dict:
    settings = store.load_settings()
    games = {g["id"]: g for g in scanner.discover_games()}
    game = games.get(game_id)
    if not game:
        raise RuntimeError("Game not found")

    paths = scanner.resolve_paths(game, settings.get("game_paths", {}))
    if not paths:
        raise RuntimeError("No save paths configured")

    # archive current local state
    archive_dir = store.runtime_path("backups", game_id)
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_zip = archive_dir / f"pre-restore-{stamp}.zip"
    _zip_paths(paths, archive_zip)

    # download snapshot
    drive = _get_drive()
    tmp = store.runtime_path("downloads")
    tmp.mkdir(parents=True, exist_ok=True)
    dl = tmp / f"{game_id}_{snapshot_id}.zip"
    drive.download_file(snapshot_id, dl)

    # extract over paths[0] parent (assumes snapshot contains relative paths from save root)
    # For v1, if only one path, extract into it; else extract into paths[0]
    target = paths[0]
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dl, "r") as zf:
        zf.extractall(target)

    try:
        dl.unlink()
    except Exception:
        pass

    # update hash
    settings.setdefault("game_meta", {})[game_id] = {
        "hash": _content_hash(target),
        "last_backup": time.time(),
    }
    store.save_settings(settings)

    return {"status": "ok", "game": game_id, "archive": str(archive_zip)}
