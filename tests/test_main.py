"""Entry-point behavior tests for audiby.__main__."""

from pathlib import Path

from audiby import __main__


def test_multiprocessing_child_request_runs_bootstrap_and_exits(mocker):
    """`<exe> -c "from multiprocessing..."` must act as a helper, never boot the app.

    Inside the PyInstaller bundle sys.executable is Audiby itself; the
    resource tracker and spawn children are launched this way.
    """
    import pytest

    ran: list[str] = []
    mocker.patch.object(
        __main__.sys, "argv",
        ["Audiby", "-B", "-S", "-I", "-c", "from multiprocessing import _probe; ran.append('x')", "extra"],
    )
    run_app = mocker.patch.object(__main__, "run_app")
    freeze = mocker.patch.object(__main__.multiprocessing, "freeze_support")
    exec_calls: list = []
    mocker.patch("builtins.exec", side_effect=lambda code, g: exec_calls.append((code, g)))

    with pytest.raises(SystemExit) as excinfo:
        __main__.main()

    assert excinfo.value.code == 0
    freeze.assert_called_once()
    run_app.assert_not_called()
    assert exec_calls[0][0].startswith("from multiprocessing")
    assert exec_calls[0][1]["__name__"] == "__main__"
    # The helper sees the arguments that followed the code, as python would.
    assert __main__.sys.argv == ["Audiby", "extra"]


def test_plain_dash_c_without_multiprocessing_is_not_hijacked(mocker):
    mocker.patch.object(__main__, "Config", return_value=mocker.Mock(config_dir=Path(".")))
    run_app = mocker.patch.object(__main__, "run_app", return_value=0)
    mocker.patch.object(__main__.multiprocessing, "freeze_support")
    mocker.patch.object(__main__.sys, "argv", ["audiby", "-c", "print('hi')"])

    assert __main__.main() == 0
    run_app.assert_called_once()


def test_main_returns_nonzero_when_run_app_fails(mocker, capsys):
    """main() should return run_app's non-zero status for startup failures."""
    mocker.patch.object(__main__, "Config", return_value=mocker.Mock(config_dir=Path(".")))
    mocker.patch.object(__main__, "run_app", return_value=1)
    mocker.patch.object(__main__, "APP_NAME", "Audiby")
    mocker.patch.object(__main__, "_VERSION", "dev")
    mocker.patch.object(__main__.sys, "argv", ["audiby"])

    exit_code = __main__.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Config loaded from" not in out


def test_main_prints_config_path_only_on_success(mocker, capsys):
    """main() should print config path when run_app succeeds."""
    cfg = mocker.Mock(config_dir=Path("C:/tmp/Audiby"))
    mocker.patch.object(__main__, "Config", return_value=cfg)
    mocker.patch.object(__main__, "run_app", return_value=0)
    mocker.patch.object(__main__, "APP_NAME", "Audiby")
    mocker.patch.object(__main__, "_VERSION", "dev")
    mocker.patch.object(__main__.sys, "argv", ["audiby"])

    exit_code = __main__.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Config loaded from" in out
