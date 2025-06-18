# File: tests/test_config.py
import os
import textwrap

import pytest
import yaml

from a2a_server.config import load_config, DEFAULT_CONFIG

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path, content: str) -> str:
    """Write *content* to a fresh YAML file under *tmp_path* and return its path."""
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent(content))
    return str(p)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_default_config():
    """Calling without a path returns an *exact* copy of DEFAULT_CONFIG."""
    cfg = await load_config(None)
    # Do *not* compare identity - we want a **copy**
    assert cfg == DEFAULT_CONFIG and cfg is not DEFAULT_CONFIG


@pytest.mark.asyncio
async def test_load_nonexistent_path(tmp_path):
    """Non-existent file path should fall back to defaults (silently)."""
    cfg = await load_config(tmp_path / "does_not_exist.yml")
    assert cfg == DEFAULT_CONFIG


@pytest.mark.asyncio
async def test_simple_merge(tmp_path):
    """Top-level keys in YAML override defaults while others stay intact."""
    yaml_path = _write_yaml(
        tmp_path,
        """
        logging:
          level: debug
        """,
    )
    cfg = await load_config(yaml_path)
    assert cfg["logging"]["level"] == "debug"
    # Unset keys survive
    assert cfg["handlers"] == DEFAULT_CONFIG["handlers"]


@pytest.mark.asyncio
async def test_deep_merge_nested(tmp_path):
    """Nested dictionaries are merged recursively (not overwritten)."""
    yaml_path = _write_yaml(
        tmp_path,
        """
        logging:
          quiet_modules:
            google.adk: WARNING
        """,
    )
    cfg = await load_config(yaml_path)
    # Existing + new key both present
    assert cfg["logging"]["quiet_modules"]["google.adk"] == "WARNING"
    # Other default quiet modules remain
    assert "httpx" in cfg["logging"]["quiet_modules"]


@pytest.mark.asyncio
async def test_override_and_add_keys(tmp_path):
    """We can add completely new top-level sections via YAML."""
    yaml_path = _write_yaml(
        tmp_path,
        """
        custom:
          foo: bar
        """,
    )
    cfg = await load_config(yaml_path)
    assert cfg["custom"] == {"foo": "bar"}
