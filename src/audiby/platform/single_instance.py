"""Single-instance guard backed by an OS file lock.

Two Audiby processes would both listen for the hotkey, both record, and both
paste, so the second launch must bow out. The guard locks a file in the app
data directory for the life of the process; the OS drops the lock when the
process exits for any reason, so a crash never leaves a stale lock behind.

The lock is taken on an open file descriptor, not by the file's existence, so
the file itself is left in place between runs and carries no state.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILENAME = "audiby.lock"


class SingleInstanceLock:
    """Hold an exclusive lock on ``<directory>/audiby.lock`` while acquired."""

    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / LOCK_FILENAME
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Try to take the lock without blocking.

        Returns True when this process now holds it, False when another
        process already does. Any unexpected OS error is logged and treated
        as "acquired" so a filesystem quirk never blocks startup.
        """
        if self._fd is not None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            logger.warning("Could not open instance lock %s: %s", self.path, exc)
            return True

        try:
            _lock_exclusive_nonblocking(fd)
        except BlockingIOError:
            os.close(fd)
            return False
        except OSError as exc:
            logger.warning("Could not lock %s; assuming single instance: %s", self.path, exc)
            os.close(fd)
            return True

        self._fd = fd
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass  # The pid is informational only.
        return True

    def release(self) -> None:
        """Drop the lock. Safe to call when not held."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _unlock(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    import msvcrt

    def _lock_exclusive_nonblocking(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            # msvcrt reports a held lock as a plain OSError (EACCES/EDEADLK).
            raise BlockingIOError(str(exc)) from exc

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_exclusive_nonblocking(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
