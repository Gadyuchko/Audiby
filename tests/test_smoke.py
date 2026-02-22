"""Smoke tests for package import and entry point behavior."""

from types import SimpleNamespace

from audiby import __main__
from audiby.exceptions import ModelError


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


def test_main_setup_model_downloads_and_exits_without_starting_app(monkeypatch) -> None:
    """--setup-model routes to model download and skips normal app startup."""
    calls = {"download": None, "run_app": 0}

    def fake_download(model_name: str):
        calls["download"] = model_name
        return "ignored-path"

    def fake_run_app(_config) -> None:
        calls["run_app"] += 1

    monkeypatch.setattr(__main__.sys, "argv", ["audiby", "--setup-model", "base"])
    monkeypatch.setattr(__main__, "run_app", fake_run_app)
    monkeypatch.setattr(__main__, "Config", lambda: SimpleNamespace(config_dir="unused"))
    monkeypatch.setattr(
        __main__,
        "model_manager",
        SimpleNamespace(download=fake_download),
        raising=False,
    )

    exit_code = __main__.main()

    assert exit_code == 0
    assert calls["download"] == "base"
    assert calls["run_app"] == 0


def test_main_setup_model_returns_non_zero_on_download_failure(monkeypatch) -> None:
    """--setup-model returns non-zero exit code when model download fails."""
    calls = {"run_app": 0}

    def fake_download(_model_name: str):
        raise ModelError("download failed")

    def fake_run_app(_config) -> None:
        calls["run_app"] += 1

    monkeypatch.setattr(__main__.sys, "argv", ["audiby", "--setup-model", "base"])
    monkeypatch.setattr(__main__, "run_app", fake_run_app)
    monkeypatch.setattr(__main__, "Config", lambda: SimpleNamespace(config_dir="unused"))
    monkeypatch.setattr(
        __main__,
        "model_manager",
        SimpleNamespace(download=fake_download),
        raising=False,
    )

    exit_code = __main__.main()

    assert exit_code != 0
    assert calls["run_app"] == 0
