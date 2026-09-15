"""Unit tests for the Playwright browser toolset registered on FRIDAY."""

import json
from pathlib import Path

from google.genai import types as genai_types
from livekit.agents import mcp
from livekit.plugins.google.utils import _GeminiJsonSchema

from browser_tool import (
    BROWSER_TOOLSET_ID,
    CONFIG_TOOLS,
    CORE_TOOLS,
    DEBUG_TOOLS,
    DEFAULT_BROWSER_TOOLS,
    DEVTOOLS_TOOLS,
    NETWORK_TOOLS,
    PDF_TOOLS,
    PLAYWRIGHT_MCP_CAPS,
    PLAYWRIGHT_MCP_PACKAGE,
    PLAYWRIGHT_MCP_TOOLS,
    STORAGE_TOOLS,
    TAB_TOOLS,
    TESTING_TOOLS,
    UNSUPPORTED_TOOLS,
    VISION_TOOLS,
    PlaywrightBrowserToolset,
    _sanitize_schema_for_google,
    _tool_name,
    browser_toolset,
)

FIXTURE = Path(__file__).parent / "fixtures" / "playwright_tools_0_0_80.json"

GRACE_SETS = DEBUG_TOOLS | UNSUPPORTED_TOOLS


def _probed_tools() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _make_raw_tool(name: str) -> mcp.MCPTool:
    """Build the same RawFunctionTool the MCP server would, without a session."""
    server = mcp.MCPServerStdio(command="npx", args=["-y", "probe"])
    return server._make_function_tool(  # type: ignore[attr-defined]
        name,
        f"Description for {name}",
        {"type": "object", "properties": {}, "required": []},
        None,
        options={
            "flags": mcp.ToolFlag.NONE,
            "on_duplicate": "allow",
            "duplicate_scope": "name",
            "report_progress": False,
        },
    )


def test_toolset_registered_with_expected_id() -> None:
    assert browser_toolset.id == BROWSER_TOOLSET_ID
    assert isinstance(browser_toolset, PlaywrightBrowserToolset)


def test_toolset_launches_pinned_mcp_server_headless() -> None:
    assert browser_toolset.server.command == "npx"
    assert "-y" in browser_toolset.server.args
    assert PLAYWRIGHT_MCP_PACKAGE in browser_toolset.server.args
    assert "--headless" in browser_toolset.server.args
    assert "--browser" in browser_toolset.server.args
    assert "--isolated" in browser_toolset.server.args
    assert "--image-responses" in browser_toolset.server.args


def test_toolset_requests_every_capability_group() -> None:
    assert "--caps" in browser_toolset.server.args
    assert PLAYWRIGHT_MCP_CAPS in browser_toolset.server.args
    for cap in PLAYWRIGHT_MCP_CAPS.split(","):
        assert cap in PLAYWRIGHT_MCP_CAPS


def test_capability_groups_are_all_covered() -> None:
    groups = (
        CORE_TOOLS,
        TAB_TOOLS,
        CONFIG_TOOLS,
        NETWORK_TOOLS,
        STORAGE_TOOLS,
        DEVTOOLS_TOOLS,
        VISION_TOOLS,
        PDF_TOOLS,
        TESTING_TOOLS,
    )
    assert all(groups)  # every group is non-empty
    assert frozenset().union(*groups) == PLAYWRIGHT_MCP_TOOLS


def test_capability_group_sizes_pin_the_probed_toolset() -> None:
    assert len(CORE_TOOLS) == 23
    assert len(TAB_TOOLS) == 1
    assert len(CONFIG_TOOLS) == 1
    assert len(NETWORK_TOOLS) == 4
    assert len(STORAGE_TOOLS) == 17
    assert len(DEVTOOLS_TOOLS) == 13
    assert len(VISION_TOOLS) == 6
    assert len(PDF_TOOLS) == 1
    assert len(TESTING_TOOLS) == 5
    assert len(PLAYWRIGHT_MCP_TOOLS) == 71


def test_every_capability_group_is_enabled_by_default() -> None:
    for group in (
        CONFIG_TOOLS,
        NETWORK_TOOLS,
        STORAGE_TOOLS,
        DEVTOOLS_TOOLS,
        VISION_TOOLS,
        PDF_TOOLS,
        TESTING_TOOLS,
    ):
        expected = group - GRACE_SETS
        assert expected and expected.issubset(DEFAULT_BROWSER_TOOLS)


def test_default_tools_cover_core_browser_functionality() -> None:
    for name in (
        "browser_navigate",
        "browser_navigate_back",
        "browser_click",
        "browser_type",
        "browser_press_key",
        "browser_fill_form",
        "browser_select_option",
        "browser_hover",
        "browser_snapshot",
        "browser_evaluate",
        "browser_tabs",
        "browser_wait_for",
        "browser_find",
        "browser_file_upload",
        "browser_handle_dialog",
    ):
        assert name in DEFAULT_BROWSER_TOOLS, f"{name} missing from browser tools"


def test_debug_tools_are_excluded_by_default() -> None:
    assert DEFAULT_BROWSER_TOOLS.isdisjoint(DEBUG_TOOLS)
    assert "browser_console_messages" not in DEFAULT_BROWSER_TOOLS
    assert "browser_network_requests" not in DEFAULT_BROWSER_TOOLS


def test_allowlist_covers_full_playwright_set_minus_debug_and_unsupported() -> None:
    assert (
        DEFAULT_BROWSER_TOOLS == PLAYWRIGHT_MCP_TOOLS - DEBUG_TOOLS - UNSUPPORTED_TOOLS
    )


def test_unsupported_tools_are_excluded_by_default() -> None:
    assert DEFAULT_BROWSER_TOOLS.isdisjoint(UNSUPPORTED_TOOLS)
    assert "browser_drop" in UNSUPPORTED_TOOLS
    assert "browser_drop" not in DEFAULT_BROWSER_TOOLS


def test_tool_name_extraction() -> None:
    assert _tool_name(_make_raw_tool("browser_navigate")) == "browser_navigate"
    assert _tool_name(object()) == ""  # type: ignore[arg-type]


async def test_setup_failure_degrades_to_empty_toolset(monkeypatch) -> None:
    # A browser subprocess crash must never take the voice session down: if the
    # Playwright MCP server can't start, setup() swallows the error and exposes
    # an empty toolset so FRIDAY still comes up and talks.
    toolset = PlaywrightBrowserToolset()

    async def _fail_to_start() -> None:
        raise RuntimeError("simulated npx crash")

    monkeypatch.setattr(toolset._mcp_server, "initialize", _fail_to_start)

    result = await toolset.setup()

    assert result is toolset
    assert toolset._tools == []
    assert toolset._initialized is False


def test_filter_tools_respects_allowlist() -> None:
    toolset = PlaywrightBrowserToolset(
        allowed_tools={"browser_navigate", "browser_click"}
    )
    toolset._tools = [
        _make_raw_tool("browser_navigate"),
        _make_raw_tool("browser_click"),
        _make_raw_tool("browser_type"),
    ]
    toolset.filter_tools(lambda tool: _tool_name(tool) in toolset._allowed_tools)

    names = {_tool_name(tool) for tool in toolset._tools}
    assert names == {"browser_navigate", "browser_click"}


def test_filter_tools_keeps_zero_tools_for_empty_allowlist() -> None:
    toolset = PlaywrightBrowserToolset(allowed_tools=set())
    toolset._tools = [
        _make_raw_tool("browser_navigate"),
        _make_raw_tool("browser_click"),
    ]
    toolset.filter_tools(lambda tool: _tool_name(tool) in toolset._allowed_tools)
    assert toolset._tools == []


def test_unknown_tools_from_server_are_pruned() -> None:
    toolset = PlaywrightBrowserToolset(allowed_tools={"browser_navigate"})
    toolset._tools = [_make_raw_tool("browser_future_rename")]
    toolset.filter_tools(lambda tool: _tool_name(tool) in toolset._allowed_tools)
    assert toolset._tools == []


def _assert_required_consistent(schema: object, where: str) -> None:
    if isinstance(schema, dict):
        properties = schema.get("properties")
        required = schema.get("required")
        if isinstance(properties, dict) and isinstance(required, list):
            assert set(required) <= set(properties), (
                f"{where}: required references undeclared properties: {required}"
            )
        for key, value in schema.items():
            _assert_required_consistent(value, f"{where}.{key}")
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            _assert_required_consistent(item, f"{where}[{index}]")


def test_fixture_contains_every_exposed_tool() -> None:
    names = {tool["name"] for tool in _probed_tools()}
    assert names == PLAYWRIGHT_MCP_TOOLS


def test_every_default_tool_schema_survives_google_validation() -> None:
    # Locks in the crash guard: every enabled tool's schema must pass the exact
    # Google realtime startup path (sanitize -> _GeminiJsonSchema.simplify ->
    # FunctionDeclaration.model_validate). If a pinned tool ever breaks that
    # validation again, this fails before a live session can crash.
    for tool in _probed_tools():
        name = tool["name"]
        if name not in DEFAULT_BROWSER_TOOLS:
            continue
        parameters = _sanitize_schema_for_google(tool["inputSchema"])
        _assert_required_consistent(parameters, tool["name"])
        simplified = _GeminiJsonSchema(parameters).simplify()
        declaration = genai_types.FunctionDeclaration.model_validate(
            {
                "name": name,
                "description": tool.get("description") or "",
                "parameters": simplified or None,
            }
        )
        assert declaration.name == name


def test_sanitizer_preserves_property_names_that_look_like_keywords() -> None:
    # browser_video_chapter has a parameter literally named "title" (and listed
    # in required). Property names are not JSON Schema keywords, so they must
    # survive sanitization or Google's Live API rejects required[] for a
    # property it never sees.
    sanitized = _sanitize_schema_for_google(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Chapter title"},
                "description": {"type": "string"},
                "duration": {"type": "number"},
            },
            "required": ["title"],
        }
    )

    assert "title" in sanitized["properties"]
    assert sanitized["required"] == ["title"]

    simplified = _GeminiJsonSchema(sanitized).simplify()
    declaration = genai_types.FunctionDeclaration.model_validate(
        {
            "name": "browser_video_chapter",
            "description": "",
            "parameters": simplified or None,
        }
    )
    assert declaration.name == "browser_video_chapter"


def test_sanitizer_prunes_required_referencing_undeclared_properties() -> None:
    sanitized = _sanitize_schema_for_google(
        {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target", "ghost"],
        }
    )

    assert sanitized["required"] == ["target"]
