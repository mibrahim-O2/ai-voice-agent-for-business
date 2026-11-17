"""A small JSON-file store for the demo CRM and calendar.

The shipped files in data/ are never modified. On first use they are copied to a working copy in
<var_dir>/state/, and every write goes there atomically (write to a temp file, then rename).
`reset()` restores the working copy from the shipped data.

Several processes can share one state directory (each agent session starts its own stdio MCP
server, the HTTP server may run at the same time, and `voice-agent reset-data` can run while they
do). Every read-modify-write therefore holds `store.lock`, which combines a thread lock with an
OS-level lock on `state/.lock`, so no update is lost between processes.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

from ..data_models import Calendar, Lead, load_calendar, load_leads

STATE_FILES = ("leads.json", "calendar.json")
Clock = Callable[[], datetime]

if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt
    import time

    def _lock_file(fh: IO[bytes]) -> None:
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:  # LK_LOCK gives up after ~10 s; keep waiting
                time.sleep(0.05)

    def _unlock_file(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock_file(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class InterProcessLock:
    """Re-entrant lock that is exclusive across threads *and* processes sharing a lock file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._fh: IO[bytes] | None = None

    def __enter__(self) -> InterProcessLock:
        self._thread_lock.acquire()
        if self._depth == 0:
            try:
                fh = open(self._path, "a+b")  # noqa: SIM115 - closed in __exit__
                try:
                    _lock_file(fh)
                except BaseException:
                    fh.close()
                    raise
            except BaseException:
                self._thread_lock.release()
                raise
            self._fh = fh
        self._depth += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self._depth -= 1
        if self._depth == 0 and self._fh is not None:
            try:
                _unlock_file(self._fh)
            finally:
                self._fh.close()
                self._fh = None
        self._thread_lock.release()


class DataStore:
    def __init__(self, data_dir: Path, var_dir: Path, clock: Clock | None = None) -> None:
        self.data_dir = data_dir
        self.state_dir = var_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = InterProcessLock(self.state_dir / ".lock")
        with self._lock:
            for name in STATE_FILES:
                if not (self.state_dir / name).exists():
                    self._atomic_copy(name)
        # The timezone never changes at runtime; read it once instead of on every now().
        self._tz: ZoneInfo = self.calendar().tz

    # ----- lifecycle -----
    def reset(self) -> None:
        """Discard all changes and restore the shipped demo data."""
        with self._lock:
            for name in STATE_FILES:
                self._atomic_copy(name)

    # ----- reads -----
    @property
    def lock(self) -> InterProcessLock:
        """Hold this around every read-modify-write."""
        return self._lock

    def leads(self) -> list[Lead]:
        return load_leads(self.state_dir / "leads.json")

    def calendar(self) -> Calendar:
        return load_calendar(self.state_dir / "calendar.json")

    def now(self) -> datetime:
        """Current local time in the calendar's timezone, as a naive datetime (like slot times)."""
        if self._clock is not None:
            return self._clock()
        return datetime.now(self._tz).replace(tzinfo=None)

    # ----- writes -----
    def save_leads(self, leads: list[Lead]) -> None:
        payload = {
            "_note": "Fictional demo data. No real people, companies or phone numbers.",
            "leads": [lead.model_dump(mode="json") for lead in leads],
        }
        self._atomic_write("leads.json", payload)

    def save_calendar(self, calendar: Calendar) -> None:
        self._atomic_write("calendar.json", calendar.model_dump(mode="json"))

    def _atomic_copy(self, name: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.state_dir, prefix=f".{name}.", suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(self.data_dir / name, tmp)
            os.replace(tmp, self.state_dir / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _atomic_write(self, name: str, payload: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.state_dir, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, self.state_dir / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
