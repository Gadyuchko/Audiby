"""Tests for the macOS main-thread keycode context shim around pynput."""

import contextlib
import sys
import threading
import types

import pytest

from audiby.platform import _pynput_mac as shim


@pytest.fixture(autouse=True)
def _reset_shim(monkeypatch):
    monkeypatch.setattr(shim, "_cached_context", None)
    monkeypatch.setattr(shim, "_installed", False)


@pytest.fixture
def fake_pynput(monkeypatch):
    """Install fake pynput darwin modules whose keycode_context records its caller thread."""
    calls: list[threading.Thread] = []

    @contextlib.contextmanager
    def original_keycode_context():
        calls.append(threading.current_thread())
        yield (42, b"layout-bytes")

    util_darwin = types.ModuleType("pynput._util.darwin")
    util_darwin.keycode_context = original_keycode_context
    keyboard_darwin = types.ModuleType("pynput.keyboard._darwin")
    keyboard_darwin.keycode_context = original_keycode_context

    pynput = types.ModuleType("pynput")
    util = types.ModuleType("pynput._util")
    keyboard = types.ModuleType("pynput.keyboard")
    util.darwin = util_darwin
    keyboard._darwin = keyboard_darwin
    pynput._util = util
    pynput.keyboard = keyboard

    for name, module in {
        "pynput": pynput,
        "pynput._util": util,
        "pynput._util.darwin": util_darwin,
        "pynput.keyboard": keyboard,
        "pynput.keyboard._darwin": keyboard_darwin,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    return util_darwin, keyboard_darwin, calls


def test_noop_off_mac(monkeypatch, fake_pynput):
    monkeypatch.setattr(sys, "platform", "win32")
    util_darwin, _, calls = fake_pynput

    assert shim.install_main_thread_keycode_context() is False
    assert calls == []


def test_primes_once_on_main_thread_and_serves_cache_to_other_threads(monkeypatch, fake_pynput):
    monkeypatch.setattr(sys, "platform", "darwin")
    util_darwin, keyboard_darwin, calls = fake_pynput

    assert shim.install_main_thread_keycode_context() is True
    assert calls == [threading.main_thread()]

    seen: list = []

    def worker():
        with keyboard_darwin.keycode_context() as context:
            seen.append(context)
        with util_darwin.keycode_context() as context:
            seen.append(context)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    # The original Carbon lookup ran exactly once, on the main thread; the
    # worker thread only ever saw the cached tuple.
    assert calls == [threading.main_thread()]
    assert seen == [(42, b"layout-bytes"), (42, b"layout-bytes")]


def test_second_install_is_skipped(monkeypatch, fake_pynput):
    monkeypatch.setattr(sys, "platform", "darwin")
    _, _, calls = fake_pynput

    assert shim.install_main_thread_keycode_context() is True
    assert shim.install_main_thread_keycode_context() is False
    assert len(calls) == 1


def test_refuses_to_prime_off_main_thread(monkeypatch, fake_pynput):
    monkeypatch.setattr(sys, "platform", "darwin")
    _, _, calls = fake_pynput
    results: list[bool] = []

    thread = threading.Thread(target=lambda: results.append(shim.install_main_thread_keycode_context()))
    thread.start()
    thread.join()

    assert results == [False]
    assert calls == []


def test_lookup_failure_leaves_pynput_untouched(monkeypatch, fake_pynput):
    monkeypatch.setattr(sys, "platform", "darwin")
    util_darwin, keyboard_darwin, _ = fake_pynput
    original = util_darwin.keycode_context

    @contextlib.contextmanager
    def broken():
        raise OSError("no layout")
        yield  # pragma: no cover

    util_darwin.keycode_context = broken
    keyboard_darwin.keycode_context = broken

    assert shim.install_main_thread_keycode_context() is False
    assert util_darwin.keycode_context is broken
    assert keyboard_darwin.keycode_context is broken
    assert original is not broken
