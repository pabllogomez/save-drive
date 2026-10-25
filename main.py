"""Save Drive Decky plugin backend."""

import os
import sys
import asyncio
from pathlib import Path

# Ensure bundled py_modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "py_modules"))

import decky

from savedrive import store
from savedrive import gdrive
from savedrive import scanner
from savedrive import backup
from savedrive import scheduler


class Plugin:
    async def ping(self) -> str:
        return "pong"

    # ---------- Settings ----------

    async def get_settings(self) -> dict:
        return store.load_settings()

    async def set_settings(self, settings: dict) -> bool:
        store.save_settings(settings)
        return True

    # ---------- Credentials ----------

    async def get_credentials_status(self) -> dict:
        creds = store.load_credentials()
        has = bool(creds.get("refresh_token"))
        email = None
        if has:
            try:
                tokens = gdrive.refresh_access_token(
                    creds["client_id"], creds["client_secret"], creds["refresh_token"]
                )
                drive = gdrive.GDrive(tokens["access_token"])
                email = drive.get_user_email()
            except Exception as e:
                decky.logger.warning(f"Failed to verify credentials: {e}")
        return {"authenticated": has, "email": email}

    async def set_credentials(self, client_id: str, client_secret: str) -> bool:
        creds = store.load_credentials()
        creds["client_id"] = client_id.strip()
        creds["client_secret"] = client_secret.strip()
        store.save_credentials(creds)
        return True

    async def start_oauth(self) -> dict:
        creds = store.load_credentials()
        if not creds.get("client_id"):
            raise RuntimeError("Missing client_id")
        resp = gdrive.start_device_auth(creds["client_id"])
        # spawn polling task
        asyncio.create_task(self._poll_oauth(resp))
        return {
            "verification_url": resp.get("verification_url", "https://g.co/device"),
            "user_code": resp["user_code"],
            "expires_in": resp.get("expires_in", 1800),
        }

    async def _poll_oauth(self, resp: dict):
        creds = store.load_credentials()
        try:
            tokens = gdrive.poll_for_token(
                creds["client_id"],
                creds["client_secret"],
                resp["device_code"],
                resp.get("interval", 5),
                resp.get("expires_in", 1800),
            )
            creds["refresh_token"] = tokens["refresh_token"]
            store.save_credentials(creds)
            await decky.emit("oauth_complete", {"success": True})
        except Exception as e:
            decky.logger.exception("OAuth failed")
            await decky.emit("oauth_complete", {"success": False, "error": str(e)})

    async def logout(self) -> bool:
        creds = store.load_credentials()
        rt = creds.get("refresh_token")
        if rt:
            gdrive.revoke_token(rt)
        store.save_credentials({})
        return True

    # ---------- Games ----------

    async def get_games(self) -> list:
        settings = store.load_settings()
        games = scanner.discover_games()
        enabled = settings.get("enabled_games", {})
        paths = settings.get("game_paths", {})
        for g in games:
            g["enabled"] = enabled.get(g["id"], False)
            g["paths"] = paths.get(g["id"], [])
            g["resolved_paths"] = [str(p) for p in scanner.resolve_paths(g, paths)]
        return games

    async def set_game_paths(self, game_id: str, paths: list[str]) -> bool:
        settings = store.load_settings()
        settings.setdefault("game_paths", {})[game_id] = paths
        store.save_settings(settings)
        return True

    async def set_game_enabled(self, game_id: str, enabled: bool) -> bool:
        settings = store.load_settings()
        settings.setdefault("enabled_games", {})[game_id] = enabled
        store.save_settings(settings)
        return True

    # ---------- Backup / Restore ----------

    async def backup_now(self, game_ids: list[str] | None = None) -> list:
        return await self.scheduler.manual_backup() if game_ids is None else backup.backup_all(game_ids)

    async def list_snapshots(self, game_id: str) -> list:
        return backup.list_snapshots(game_id)

    async def restore_snapshot(self, game_id: str, snapshot_id: str) -> dict:
        return backup.restore_game(game_id, snapshot_id)

    # ---------- Lifecycle ----------

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self.scheduler = scheduler.Scheduler(self._on_scheduled_backup)
        await self.scheduler.start()
        decky.logger.info("Save Drive plugin loaded")

    async def _on_scheduled_backup(self):
        return backup.backup_all()

    async def _unload(self):
        decky.logger.info("Save Drive unloading")
        await self.scheduler.stop()

    async def _uninstall(self):
        decky.logger.info("Save Drive uninstalling")
        await self.scheduler.stop()

    async def _migration(self):
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "save-drive.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "save-drive"),
        )
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "data", "save-drive"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "save-drive"),
        )
