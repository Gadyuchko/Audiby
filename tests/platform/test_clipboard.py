"""Behavior-focused tests for clipboard module.

Tests validate Win32 clipboard get/set/backup/restore operations,
error handling, CloseClipboard guarantee, and InjectionError wrapping.
All Win32 API calls are fully mocked — no real clipboard access.
"""
from unittest.mock import patch

import pytest

from audiby.exceptions import InjectionError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# All Win32 function aliases patched at the clipboard module level
_P = "audiby.platform.clipboard"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def win32():
    """Patch all Win32 aliases and ctypes in clipboard module.

    Yields a namespace with mock handles for each Win32 function.
    All mocks default to success returns.
    """
    with patch(f"{_P}.OpenClipboard") as m_open, \
         patch(f"{_P}.CloseClipboard") as m_close, \
         patch(f"{_P}.GetClipboardData") as m_get, \
         patch(f"{_P}.SetClipboardData") as m_set, \
         patch(f"{_P}.EmptyClipboard") as m_empty, \
         patch(f"{_P}.GlobalAlloc") as m_alloc, \
         patch(f"{_P}.GlobalLock") as m_lock, \
         patch(f"{_P}.GlobalUnlock") as m_unlock, \
         patch(f"{_P}.GlobalFree") as m_free, \
         patch(f"{_P}.ctypes.sizeof") as m_sizeof, \
         patch(f"{_P}.ctypes.wstring_at") as m_wstring_at, \
         patch(f"{_P}.ctypes.create_unicode_buffer") as m_create_unicode_buffer, \
         patch(f"{_P}.ctypes.memmove") as m_memmove:

        # Sensible defaults — all operations succeed
        m_open.return_value = True
        m_close.return_value = True
        m_empty.return_value = True
        m_set.return_value = 1  # non-null handle
        m_alloc.return_value = 1  # non-null handle
        m_lock.return_value = 1  # non-null pointer
        m_unlock.return_value = True
        m_sizeof.return_value = 2  # wchar size
        m_wstring_at.return_value = "clipboard-text"
        m_create_unicode_buffer.side_effect = lambda text: text
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
            sizeof = m_sizeof
            wstring_at = m_wstring_at
            create_unicode_buffer = m_create_unicode_buffer
            memmove = m_memmove

        yield _Win32()


def _get_text():
    from audiby.platform.clipboard import get_text
    return get_text

def _set_text():
    from audiby.platform.clipboard import set_text
    return set_text

def _backup():
    from audiby.platform.clipboard import backup
    return backup

def _restore():
    from audiby.platform.clipboard import restore
    return restore


# ---------------------------------------------------------------------------
# Task 4.1 — get/set/backup/restore round-trip with mocked Win32 API
# ---------------------------------------------------------------------------

class TestClipboardGetText:
    """get_text() reads CF_UNICODETEXT from clipboard via Win32 API."""

    def test_get_text_returns_clipboard_string(self, win32):
        """get_text() must return the clipboard text when CF_UNICODETEXT is available."""
        win32.GetClipboardData.return_value = 1
        win32.wstring_at.return_value = "hello world"

        result = _get_text()()

        assert result == "hello world"
        win32.OpenClipboard.assert_called_once()
        win32.CloseClipboard.assert_called_once()

    def test_get_text_calls_get_clipboard_data_with_cf_unicodetext(self, win32):
        """get_text() must request CF_UNICODETEXT (13) from GetClipboardData."""
        win32.GetClipboardData.return_value = 1
        win32.wstring_at.return_value = "test"

        _get_text()()

        win32.GetClipboardData.assert_called_once_with(CF_UNICODETEXT)


class TestClipboardSetText:
    """set_text() writes text to clipboard via Win32 API."""

    def test_set_text_writes_to_clipboard(self, win32):
        """set_text() must call EmptyClipboard then SetClipboardData."""
        _set_text()("hello")

        win32.OpenClipboard.assert_called_once()
        win32.EmptyClipboard.assert_called_once()
        win32.SetClipboardData.assert_called_once()
        win32.CloseClipboard.assert_called_once()

    def test_set_text_uses_cf_unicodetext_format(self, win32):
        """SetClipboardData must be called with CF_UNICODETEXT format."""
        _set_text()("test")

        args, _ = win32.SetClipboardData.call_args
        assert args[0] == CF_UNICODETEXT

    def test_set_text_allocates_global_memory(self, win32):
        """set_text() must allocate global moveable memory for the text data."""
        _set_text()("abc")

        win32.GlobalAlloc.assert_called_once()
        alloc_args, _ = win32.GlobalAlloc.call_args
        assert alloc_args[0] == GMEM_MOVEABLE


class TestClipboardBackupRestore:
    """backup() and restore() convenience wrappers handle None gracefully."""

    def test_backup_returns_current_clipboard_text(self, win32):
        """backup() must return whatever get_text() returns."""
        win32.GetClipboardData.return_value = 1
        win32.wstring_at.return_value = "original"

        result = _backup()()

        assert result == "original"

    def test_restore_sets_clipboard_to_backup_value(self, win32):
        """restore(text) must write the backup text back to clipboard."""
        _restore()("original text")

        win32.SetClipboardData.assert_called_once()

    def test_restore_none_clears_clipboard_gracefully(self, win32):
        """restore(None) must clear clipboard text without crashing."""
        # Must not raise
        _restore()(None)

        win32.OpenClipboard.assert_called_once()
        win32.EmptyClipboard.assert_called_once()
        win32.CloseClipboard.assert_called_once()
        # SetClipboardData should NOT be called for None restore
        win32.SetClipboardData.assert_not_called()

    def test_backup_restore_round_trip(self, win32):
        """backup → set_text → restore must leave clipboard in original state."""
        win32.GetClipboardData.return_value = 1
        win32.wstring_at.return_value = "original"

        saved = _backup()()
        _set_text()("injected")
        _restore()(saved)

        # SetClipboardData called twice: once for set_text, once for restore
        assert win32.SetClipboardData.call_count == 2


# ---------------------------------------------------------------------------
# Task 4.2 — Non-text clipboard handling returns None gracefully
# ---------------------------------------------------------------------------

class TestClipboardNonTextHandling:
    """get_text() handles non-text clipboard contents gracefully."""

    def test_get_text_returns_none_when_no_unicodetext(self, win32):
        """get_text() must return None when GetClipboardData returns null."""
        win32.GetClipboardData.return_value = 0  # null — no CF_UNICODETEXT

        result = _get_text()()

        assert result is None

    def test_get_text_returns_none_for_empty_clipboard(self, win32):
        """get_text() must return None when clipboard is empty (null handle)."""
        win32.GetClipboardData.return_value = None

        result = _get_text()()

        assert result is None

    def test_backup_returns_none_for_nontext_clipboard(self, win32):
        """backup() must return None when clipboard has non-text content."""
        win32.GetClipboardData.return_value = 0

        result = _backup()()

        assert result is None


# ---------------------------------------------------------------------------
# Task 4.3 — CloseClipboard is always called even on error
# ---------------------------------------------------------------------------

class TestCloseClipboardGuarantee:
    """CloseClipboard must be called in finally block regardless of errors."""

    def test_close_called_when_get_clipboard_data_raises(self, win32):
        """CloseClipboard must be called even when GetClipboardData throws."""
        win32.GetClipboardData.side_effect = OSError("read failed")

        with pytest.raises(InjectionError):
            _get_text()()

        win32.CloseClipboard.assert_called_once()

    def test_close_called_when_set_clipboard_data_raises(self, win32):
        """CloseClipboard must be called even when SetClipboardData throws."""
        win32.SetClipboardData.side_effect = OSError("write failed")

        with pytest.raises(InjectionError):
            _set_text()("test")

        win32.CloseClipboard.assert_called_once()

    def test_close_called_when_empty_clipboard_raises(self, win32):
        """CloseClipboard must be called even when EmptyClipboard throws."""
        win32.EmptyClipboard.side_effect = OSError("empty failed")

        with pytest.raises(InjectionError):
            _set_text()("test")

        win32.CloseClipboard.assert_called_once()

    def test_close_called_when_global_alloc_raises(self, win32):
        """CloseClipboard must be called even when GlobalAlloc fails."""
        win32.GlobalAlloc.return_value = 0  # null — allocation failed

        with pytest.raises(InjectionError):
            _set_text()("test")

        win32.CloseClipboard.assert_called_once()

    def test_close_called_when_global_lock_fails(self, win32):
        """CloseClipboard must be called even when GlobalLock returns null."""
        win32.GlobalLock.return_value = 0

        with pytest.raises(InjectionError):
            _set_text()("test")

        win32.CloseClipboard.assert_called_once()


# ---------------------------------------------------------------------------
# Task 4.4 — InjectionError raised on Win32 API failures
# ---------------------------------------------------------------------------

class TestInjectionErrorOnFailure:
    """All Win32 API failures must surface as InjectionError."""

    def test_injection_error_on_open_clipboard_failure(self, win32):
        """Failed OpenClipboard must raise InjectionError."""
        win32.OpenClipboard.return_value = False  # failure

        with pytest.raises(InjectionError, match="[Oo]pen"):
            _get_text()()

    def test_injection_error_on_set_clipboard_data_failure(self, win32):
        """Failed SetClipboardData must raise InjectionError."""
        win32.SetClipboardData.return_value = 0  # null — failure

        with pytest.raises(InjectionError):
            _set_text()("test")

    def test_injection_error_on_global_alloc_failure(self, win32):
        """Failed GlobalAlloc (null return) must raise InjectionError."""
        win32.GlobalAlloc.return_value = 0  # null — failure

        with pytest.raises(InjectionError, match="[Aa]lloc|[Mm]emory"):
            _set_text()("test")

    def test_injection_error_preserves_original_cause(self, win32):
        """Wrapped InjectionError must chain the original OS exception via __cause__."""
        original = OSError("win32 error")
        win32.GetClipboardData.side_effect = original

        with pytest.raises(InjectionError) as exc_info:
            _get_text()()

        assert exc_info.value.__cause__ is original

    def test_injection_error_on_open_for_set_text(self, win32):
        """Failed OpenClipboard during set_text must raise InjectionError."""
        win32.OpenClipboard.return_value = False

        with pytest.raises(InjectionError, match="[Oo]pen"):
            _set_text()("test")

    def test_injection_error_on_global_lock_failure(self, win32):
        """Failed GlobalLock (null pointer) must raise InjectionError."""
        win32.GlobalLock.return_value = 0

        with pytest.raises(InjectionError, match="[Ll]ock"):
            _set_text()("test")

    def test_get_text_uses_global_lock_and_unlock(self, win32):
        """get_text() must lock and unlock clipboard data handle."""
        win32.GetClipboardData.return_value = 123
        win32.wstring_at.return_value = "locked text"

        result = _get_text()()

        assert result == "locked text"
        win32.GlobalLock.assert_called_once_with(123)
        win32.GlobalUnlock.assert_called_once_with(123)

    def test_set_text_frees_memory_when_set_clipboard_data_fails(self, win32):
        """set_text() must free allocated memory if SetClipboardData fails."""
        win32.SetClipboardData.return_value = 0

        with pytest.raises(InjectionError):
            _set_text()("test")

        win32.GlobalFree.assert_called_once()
