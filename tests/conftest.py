"""Shared pytest fixtures and configuration for Audiby tests."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that perform real network and filesystem operations.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="pass --run-integration to run integration tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
