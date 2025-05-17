# File: tests/test_logging.py
import json
import logging
from pathlib import Path

import pytest

from a2a_server.logging import configure_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_root_logger():
    """Remove handlers & reset level so each test starts clean."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.NOTSET)


def _flush_handlers():
    """Flush all handlers so capsys sees the latest log lines."""
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:  # pragma: no cover
            pass


@pytest.fixture(autouse=True)
def _clean_root():
    _reset_root_logger()
    yield
    _reset_root_logger()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_verbose_module_sets_debug():
    module_name = "foo.bar"

    # Ensure logger starts with WARNING
    logging.getLogger(module_name).setLevel(logging.WARNING)
    assert logging.getLogger(module_name).level == logging.WARNING

    configure_logging(level_name="info", verbose_modules=[module_name])
    assert logging.getLogger(module_name).level == logging.DEBUG


def test_quiet_module_overrides_default():
    module_name = "uvicorn"  # defaults to WARNING in implementation

    configure_logging(level_name="debug", quiet_modules={module_name: "ERROR"})
    assert logging.getLogger(module_name).level == logging.ERROR


def test_plain_text_format(capsys):
    configure_logging(level_name="info")
    logging.getLogger("foo").info("hello world")
    _flush_handlers()
    out, err = capsys.readouterr()

    log_data = err or out  # console handler writes to stderr by default
    assert "foo" in log_data and "hello world" in log_data

    tokens = log_data.split()
    # Level name should appear near the start (timestamp formats vary)
    assert "INFO" in tokens[:4]


@pytest.mark.skipif(
    pytest.importorskip("pythonjsonlogger", reason="python-json-logger not installed") is None,
    reason="python-json-logger not installed",
)
def test_json_format_env(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")

    configure_logging(level_name="info")
    logging.getLogger("foo").info("hello json")
    _flush_handlers()
    out, err = capsys.readouterr()
    log_data = err or out

    # should be valid JSON with expected keys
    record = json.loads(log_data.strip())
    assert record["name"] == "foo"
    assert record["levelname"] == "INFO"
    assert record["message"] == "hello json"


def test_file_logging(tmp_path: Path):
    log_file = tmp_path / "test.log"

    configure_logging(level_name="info", file_path=str(log_file))
    logging.getLogger("foo").info("file output")
    _flush_handlers()

    content = log_file.read_text()
    assert "file output" in content
