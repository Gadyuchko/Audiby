"""Entry-point behavior tests for audiby.__main__."""

from pathlib import Path

from audiby import __main__


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
