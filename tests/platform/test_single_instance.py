"""Tests for the file-lock single-instance guard."""

import os
import subprocess
import sys
import textwrap

from audiby.platform.single_instance import LOCK_FILENAME, SingleInstanceLock


def test_acquire_creates_lock_file_and_records_pid(tmp_path):
    lock = SingleInstanceLock(tmp_path)

    assert lock.acquire() is True
    assert lock.held
    assert (tmp_path / LOCK_FILENAME).read_text() == str(os.getpid())

    lock.release()
    assert not lock.held


def test_acquire_is_idempotent_for_the_holder(tmp_path):
    lock = SingleInstanceLock(tmp_path)
    assert lock.acquire() is True
    assert lock.acquire() is True
    lock.release()


def test_release_without_acquire_is_safe(tmp_path):
    SingleInstanceLock(tmp_path).release()


def test_second_process_cannot_acquire_while_first_holds(tmp_path):
    """The lock must be enforced by the OS across processes, not just in memory."""
    holder = SingleInstanceLock(tmp_path)
    assert holder.acquire() is True

    probe = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from audiby.platform.single_instance import SingleInstanceLock
        lock = SingleInstanceLock(Path({str(tmp_path)!r}))
        print("acquired" if lock.acquire() else "busy")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "busy"

    holder.release()
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "acquired"


def test_context_manager_acquires_and_releases(tmp_path):
    with SingleInstanceLock(tmp_path) as lock:
        assert lock.held
    assert not lock.held


def test_unopenable_lock_path_does_not_block_startup(tmp_path, caplog):
    """A filesystem problem is logged and treated as acquired."""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("")  # a file where the directory should be
    lock = SingleInstanceLock(blocked / "sub")

    with caplog.at_level("WARNING", logger="audiby.platform.single_instance"):
        assert lock.acquire() is True

    assert not lock.held
    assert "Could not open instance lock" in caplog.text
