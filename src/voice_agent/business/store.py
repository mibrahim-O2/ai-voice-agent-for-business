"""A small JSON-file store for the demo CRM and calendar.

The shipped files in data/ are never modified. On first use they are copied to a working copy in
<var_dir>/state/, and every write goes there atomically (write to a temp file, then rename).
`reset()` restores the working copy from the shipped data.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..data_models import Calendar, Lead, load_calendar, load_leads

STATE_FILES = ("leads.json", "calendar.json")
Clock = Callable[[], datetime]


class DataStore:
    def __init__(self, data_dir: Path, var_dir: Path, clock: Clock | None = None) -> None:
        self.data_dir = data_dir
        self.state_dir = var_dir / "state"
        self._clock = clock
        self._lock = threading.RLock()
        self._ensure_state()

    # ----- lifecycle -----
    def _ensure_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for name in STATE_FILES:
            if not (self.state_dir / name).exists():
                shutil.copyfile(self.data_dir / name, self.state_dir / name)

    def reset(self) -> None:
        """Discard all changes and restore the shipped demo data."""
        with self._lock:
            for name in STATE_FILES:
                shutil.copyfile(self.data_dir / name, self.state_dir / name)

    # ----- reads -----
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def leads(self) -> list[Lead]:
        return load_leads(self.state_dir / "leads.json")

    def calendar(self) -> Calendar:
        return load_calendar(self.state_dir / "calendar.json")

    def now(self) -> datetime:
        """Current local time in the calendar's timezone, as a naive datetime (like slot times)."""
        if self._clock is not None:
            return self._clock()
        return datetime.now(self.calendar().tz).replace(tzinfo=None)

    # ----- writes -----
    def save_leads(self, leads: list[Lead]) -> None:
        payload = {
            "_note": "Fictional demo data. No real people, companies or phone numbers.",
            "leads": [lead.model_dump(mode="json") for lead in leads],
        }
        self._atomic_write("leads.json", payload)

    def save_calendar(self, calendar: Calendar) -> None:
        self._atomic_write("calendar.json", calendar.model_dump(mode="json"))

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
