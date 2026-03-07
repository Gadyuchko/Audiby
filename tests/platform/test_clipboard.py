"""Tests for clipboard factory dispatch and Windows backend behavior."""

import subprocess
from unittest.mock import patch

import pytest

from audiby.exceptions import InjectionError
from audiby.platform._clipboard_mac import MacClipboard
from audiby.platform._clipboard_win import WindowsClipboard
from audiby.platform.clipboard import get_clipboard


@pytest.fixture
def win32():
    """Patch all Win32 aliases used by WindowsClipboard."""
    with (
        patch("audiby.platform._clipboard_win.OpenClipboard") as m_open,
        patch("audiby.platform._clipboard_win.CloseClipboard") as m_close,
        patch("audiby.platform._clipboard_win.GetClipboardData") as m_get,
        patch("audiby.platform._clipboard_win.SetClipboardData") as m_set,
        patch("audiby.platform._clipboard_win.EmptyClipboard") as m_empty,
        patch("audiby.platform._clipboard_win.GlobalAlloc") as m_alloc,
        patch("audiby.platform._clipboard_win.GlobalLock") as m_lock,
        patch("audiby.platform._clipboard_win.GlobalUnlock") as m_unlock,
        patch("audiby.platform._clipboard_win.GlobalFree") as m_free,
        patch("audiby.platform._clipboard_win.ctypes.sizeof") as m_sizeof,
        patch("audiby.platform._clipboard_win.ctypes.wstring_at") as m_wstring_at,
        patch("audiby.platform._clipboard_win.ctypes.create_unicode_buffer") as m_create,
        patch("audiby.platform._clipboard_win.ctypes.memmove") as m_memmove,
    ):
        m_open.return_value = True
        m_close.return_value = True
        m_empty.return_value = True
        m_set.return_value = 1
        m_alloc.return_value = 1
        m_lock.return_value = 1
        m_unlock.return_value = True
        m_sizeof.return_value = 2
        m_wstring_at.return_value = "clipboard-text"
        m_create.side_effect = lambda text: text
        m_memmove.return_value = None
        m_free.return_value = True

        class _Win32:
            OpenClipboard = m_open
            CloseClipboard = m_close
            GetClipboardData = m_get
            SetClipboardData = m_set
            EmptyClipboard = m_empty
            GlobalAlloc = m_alloc
            GlobalLock = m_lock
            GlobalUnlock = m_unlock
            GlobalFree = m_free
            wstring_at = m_wstring_at

        yield _Win32()


def test_factory_returns_windows_backend_on_win32(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    backend = get_clipboard()

    assert isinstance(backend, WindowsClipboard)


def test_factory_returns_mac_backend_on_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")

    backend = get_clipboard()

    assert isinstance(backend, MacClipboard)


def test_factory_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")

    with pytest.raises(NotImplementedError):
        get_clipboard()


def test_windows_get_text_reads_clipboard(win32):
    cb = WindowsClipboard()
    win32.GetClipboardData.return_value = 1
    win32.wstring_at.return_value = "hello"

    assert cb.get_text() == "hello"
    win32.OpenClipboard.assert_called_once()
    win32.CloseClipboard.assert_called_once()


def test_windows_set_text_writes_clipboard(win32):
    cb = WindowsClipboard()

    cb.set_text("hello")

    win32.EmptyClipboard.assert_called_once()
    win32.SetClipboardData.assert_called_once()


def test_windows_backup_restore_round_trip(win32):
    cb = WindowsClipboard()
    win32.GetClipboardData.return_value = 1
    win32.wstring_at.return_value = "orig"

    saved = cb.backup()
    cb.set_text("new")
    cb.restore(saved)

    assert saved == "orig"
    assert win32.SetClipboardData.call_count == 2


def test_windows_set_text_failure_raises_injection_error(win32):
    cb = WindowsClipboard()
    win32.SetClipboardData.return_value = 0

    with pytest.raises(InjectionError):
        cb.set_text("test")


# ---------------------------------------------------------------------------
# MacClipboard behavioral tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mac_cb():
    """Create a MacClipboard with subprocess mocked."""
    with patch("audiby.platform._clipboard_mac.subprocess") as m_sub:
        yield MacClipboard(), m_sub


def test_mac_get_text_reads_clipboard(mac_cb):
    cb, m_sub = mac_cb
    m_sub.run.return_value.stdout = "hello"
    m_sub.CalledProcessError = subprocess.CalledProcessError

    assert cb.get_text() == "hello"
    m_sub.run.assert_called_once_with(["pbpaste"], capture_output=True, text=True, check=True)


def test_mac_get_text_returns_none_for_empty(mac_cb):
    cb, m_sub = mac_cb
    m_sub.run.return_value.stdout = ""
    m_sub.CalledProcessError = subprocess.CalledProcessError

    assert cb.get_text() is None


def test_mac_set_text_writes_clipboard(mac_cb):
    cb, m_sub = mac_cb
    m_sub.CalledProcessError = subprocess.CalledProcessError

    cb.set_text("hello")

    m_sub.run.assert_called_once_with(["pbcopy"], input="hello", text=True, check=True)


def test_mac_backup_restore_round_trip(mac_cb):
    cb, m_sub = mac_cb
    m_sub.run.return_value.stdout = "orig"
    m_sub.CalledProcessError = subprocess.CalledProcessError

    saved = cb.backup()
    cb.set_text("new")
    cb.restore(saved)

    assert saved == "orig"
    assert m_sub.run.call_count == 3


def test_mac_get_text_failure_raises_injection_error(mac_cb):
    cb, m_sub = mac_cb
    m_sub.run.side_effect = subprocess.CalledProcessError(1, "pbpaste", stderr="fail")
    m_sub.CalledProcessError = subprocess.CalledProcessError

    with pytest.raises(InjectionError):
        cb.get_text()
