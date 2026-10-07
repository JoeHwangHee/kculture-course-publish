"""Tests for tools.register_all: the eleven tools of spec 2.2 in contract order."""

from __future__ import annotations

import pytest

from common.schema import TOOL_NAMES, SchemaError
from common.tooling import TOOL_ARGS, ToolRegistry
from tools import register_all


def test_register_all_registers_eleven_tools_in_contract_order():
    registry = ToolRegistry()
    register_all(registry)
    assert len(registry) == 11
    assert registry.names() == list(TOOL_NAMES)


def test_every_spec_has_description_and_contract_args():
    registry = ToolRegistry()
    register_all(registry)
    for name in TOOL_NAMES:
        spec = registry.get(name)
        assert isinstance(spec.description, str) and spec.description.strip(), name
        assert "\n" not in spec.description, name
        assert spec.args == TOOL_ARGS[name], name


def test_register_all_twice_is_rejected():
    registry = ToolRegistry()
    register_all(registry)
    with pytest.raises(SchemaError, match="already registered"):
        register_all(registry)
