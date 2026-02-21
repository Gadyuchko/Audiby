"""Smoke tests for package import and entry point behavior."""

from audiby import __main__


def test_package_import_smoke() -> None:
    """Package can be imported successfully."""
    import audiby  # noqa: F401


def test_main_prints_startup_message(capsys, monkeypatch) -> None:
    """Entry point prints startup messages and exits cleanly."""
    monkeypatch.setattr(__main__, "run_app", lambda _config: None)
    exit_code = __main__.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Audiby v0.1.0 - starting up..." in captured.out
    assert "Config loaded from" in captured.out
