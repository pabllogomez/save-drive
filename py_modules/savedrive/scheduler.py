"""Monitor shutdown/sleep signals and trigger backups at the right time."""

import asyncio
import shutil
import time
from pathlib import Path

try:
    import decky
    logger = decky.logger
except Exception:
    import logging
    logger = logging.getLogger("savedrive")


class Inhibitor:
    """Hold a systemd inhibitor in block mode while the process runs."""

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self):
        if self._proc and self._proc.returncode is None:
            return
        if not shutil.which("systemd-inhibit"):
            logger.warning("systemd-inhibit not found; sleep/shutdown backups disabled")
            return
        self._proc = await asyncio.create_subprocess_exec(
            "systemd-inhibit",
            "--what=shutdown:sleep",
            "--mode=block",
            "--who=SaveDrive",
            "--why=Backing up game saves before shutdown or sleep",
            "cat",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.info("Inhibitor active")

    def release(self):
        if self._proc and self._proc.returncode is None and self._proc.stdin:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            logger.info("Inhibitor released")

    async def restart(self):
        self.release()
        await asyncio.sleep(0.2)
        await self.start()


class SleepShutdownMonitor:
    """Watch logind PrepareForShutdown / PrepareForSleep via dbus-monitor."""

    def __init__(self, on_signal, on_cancel):
        self.on_signal = on_signal
        self.on_cancel = on_cancel
        self._proc: asyncio.subprocess.Process | None = None
        self._pending_member: str | None = None

    async def start(self):
        if not shutil.which("dbus-monitor"):
            logger.warning("dbus-monitor not found; sleep/shutdown backups disabled")
            return
        if self._proc and self._proc.returncode is None:
            return
        self._proc = await asyncio.create_subprocess_exec(
            "dbus-monitor",
            "--system",
            "type='signal',sender='org.freedesktop.login1',path='/org/freedesktop/login1',interface='org.freedesktop.login1.Manager'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.info("Sleep/shutdown monitor active")
        asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        if not self._proc or not self._proc.stdout:
            return
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if "PrepareForSleep" in text:
                    self._pending_member = "PrepareForSleep"
                elif "PrepareForShutdown" in text:
                    self._pending_member = "PrepareForShutdown"
                elif "boolean" in text and self._pending_member:
                    value = "true" in text
                    member = self._pending_member
                    self._pending_member = None
                    if value:
                        logger.info(f"{member} true: triggering backup")
                        await self.on_signal(member)
                    else:
                        logger.info(f"{member} false: re-arming inhibitor")
                        await self.on_cancel(member)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Monitor read loop error: {e}")

    def stop(self):
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()


class Scheduler:
    def __init__(self, backup_callback):
        self.backup_callback = backup_callback
        self.inhibitor = Inhibitor()
        self.monitor = SleepShutdownMonitor(
            on_signal=self._on_signal,
            on_cancel=self._on_cancel,
        )
        self._busy = False

    async def start(self):
        await self.inhibitor.start()
        await self.monitor.start()

    async def stop(self):
        self.monitor.stop()
        self.inhibitor.release()

    async def _on_signal(self, member: str):
        if self._busy:
            logger.info("Backup already running; waiting before releasing inhibitor")
            # wait for current backup without blocking the monitor
            return
        self._busy = True
        try:
            await self.backup_callback()
        except Exception as e:
            logger.exception("Pre-sleep/shutdown backup failed")
        finally:
            self._busy = False
            # Release inhibitor so shutdown/sleep can proceed.
            self.inhibitor.release()
            # If it was sleep, the process will freeze; on wake we re-arm.
            # If it was shutdown, the process will be killed soon.

    async def _on_cancel(self, member: str):
        if self._busy:
            return
        await self.inhibitor.restart()

    async def manual_backup(self):
        if self._busy:
            raise RuntimeError("Backup already in progress")
        self._busy = True
        try:
            return await self.backup_callback()
        finally:
            self._busy = False
