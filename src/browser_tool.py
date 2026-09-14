"""Browser control for FRIDAY via the official Playwright MCP server.

Wraps the ``@playwright/mcp`` Node server in an ``MCPToolset`` so the agent can
drive a headless Chromium browser through normal LiveKit function tools. Every
tool the LLM can call maps 1:1 onto a Playwright browser action (navigate,
click, type, fill forms, press keys, snapshot pages, run JavaScript, manage
tabs, and more).
"""

from __future__ import annotations

from livekit.agents import mcp
from typing_extensions import Self

BROWSER_TOOLSET_ID = "browser"

# Pinned so the exposed tool names (and behavior) stay reproducible.
PLAYWRIGHT_MCP_PACKAGE = "@playwright/mcp@0.0.80"

# Option-in capability groups requested from the MCP server. Every group below
# adds tools: config (browser_get_config), network (routing/mocks), storage
# (cookies/localStorage/sessionStorage/state), devtools (recording, tracing,
# video, highlights), vision (coordinate mouse actions), pdf (save as PDF) and
# testing (locator generation/assertions).
PLAYWRIGHT_MCP_CAPS = "config,devtools,network,pdf,storage,testing,vision"

# Tools exposed by @playwright/mcp@0.0.80, probed against the server with
# PLAYWRIGHT_MCP_CAPS enabled. Grouped by the capability that gates them.
CORE_TOOLS: frozenset[str] = frozenset(
    {
        "browser_click",
        "browser_close",
        "browser_console_messages",
        "browser_drag",
        "browser_drop",
        "browser_evaluate",
        "browser_file_upload",
        "browser_fill_form",
        "browser_find",
        "browser_handle_dialog",
        "browser_hover",
        "browser_navigate",
        "browser_navigate_back",
        "browser_network_request",
        "browser_network_requests",
        "browser_press_key",
        "browser_resize",
        "browser_run_code_unsafe",
        "browser_select_option",
        "browser_snapshot",
        "browser_take_screenshot",
        "browser_type",
        "browser_wait_for",
    }
)

TAB_TOOLS: frozenset[str] = frozenset(
    {
        "browser_tabs",
    }
)

CONFIG_TOOLS: frozenset[str] = frozenset(
    {
        "browser_get_config",
    }
)

NETWORK_TOOLS: frozenset[str] = frozenset(
    {
        "browser_network_state_set",
        "browser_route",
        "browser_route_list",
        "browser_unroute",
    }
)

STORAGE_TOOLS: frozenset[str] = frozenset(
    {
        "browser_cookie_clear",
        "browser_cookie_delete",
        "browser_cookie_get",
        "browser_cookie_list",
        "browser_cookie_set",
        "browser_localstorage_clear",
        "browser_localstorage_delete",
        "browser_localstorage_get",
        "browser_localstorage_list",
        "browser_localstorage_set",
        "browser_sessionstorage_clear",
        "browser_sessionstorage_delete",
        "browser_sessionstorage_get",
        "browser_sessionstorage_list",
        "browser_sessionstorage_set",
        "browser_set_storage_state",
        "browser_storage_state",
    }
)

DEVTOOLS_TOOLS: frozenset[str] = frozenset(
    {
        "browser_annotate",
        "browser_hide_highlight",
        "browser_highlight",
        "browser_resume",
        "browser_start_recording",
        "browser_start_tracing",
        "browser_start_video",
        "browser_stop_recording",
        "browser_stop_tracing",
        "browser_stop_video",
        "browser_video_chapter",
        "browser_video_hide_actions",
        "browser_video_show_actions",
    }
)

VISION_TOOLS: frozenset[str] = frozenset(
    {
        "browser_mouse_click_xy",
        "browser_mouse_down",
        "browser_mouse_drag_xy",
        "browser_mouse_move_xy",
        "browser_mouse_up",
        "browser_mouse_wheel",
    }
)

PDF_TOOLS: frozenset[str] = frozenset(
    {
        "browser_pdf_save",
    }
)

TESTING_TOOLS: frozenset[str] = frozenset(
    {
        "browser_generate_locator",
        "browser_verify_element_visible",
        "browser_verify_list_visible",
        "browser_verify_text_visible",
        "browser_verify_value",
    }
)

PLAYWRIGHT_MCP_TOOLS: frozenset[str] = frozenset(
    CORE_TOOLS
    | TAB_TOOLS
    | CONFIG_TOOLS
    | NETWORK_TOOLS
    | STORAGE_TOOLS
    | DEVTOOLS_TOOLS
    | VISION_TOOLS
    | PDF_TOOLS
    | TESTING_TOOLS
)

# Tools that return large payloads or are telemetry-only. They waste context
# and add latency for a voice agent, so they are excluded by default.
DEBUG_TOOLS: frozenset[str] = frozenset(
    {
        "browser_console_messages",
        "browser_network_request",
        "browser_network_requests",
    }
)

# Tools whose parameter schemas Google's realtime API cannot express. For
# example browser_drop's ``data`` map uses propertyNames/additionalProperties,
# which breaks FunctionDeclaration validation and kills the session before it
# connects. Keep them out until the upstream schema changes.
UNSUPPORTED_TOOLS: frozenset[str] = frozenset(
    {
        "browser_drop",
    }
)

DEFAULT_BROWSER_TOOLS: frozenset[str] = frozenset(
    PLAYWRIGHT_MCP_TOOLS - DEBUG_TOOLS - UNSUPPORTED_TOOLS
)

# JSON Schema keywords Google's FunctionDeclaration/Schema pydantic models
# forbid (they use extra="forbid"). The google plugin already drops some of
# these on its own; this set covers the rest so a schema mismatch can never
# silently kill the agent again.
_UNSUPPORTED_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalItems",
        "additionalProperties",
        "allOf",
        "const",
        "contains",
        "contentEncoding",
        "contentMediaType",
        "default",
        "definitions",
        "dependentRequired",
        "dependentSchemas",
        "discriminator",
        "else",
        "example",
        "examples",
        "format",
        "if",
        "maxContains",
        "minContains",
        "not",
        "oneOf",
        "patternProperties",
        "propertyNames",
        "readOnly",
        "then",
        "title",
        "unevaluatedItems",
        "unevaluatedProperties",
        "writeOnly",
    }
)


def _sanitize_schema_for_google(node: object) -> object:
    """Drop JSON Schema keywords Google's tool schema cannot parse.

    Recurses the schema so maps (``{"type": "object", "propertyNames": ...,
    "additionalProperties": ...}``) collapse to a plain object instead of
    crashing ``FunctionDeclaration.model_validate``. Property names inside
    ``properties`` are only ever schema values' keys — never dropped, even when
    a parameter is literally named like a keyword (e.g. "title"). ``required``
    lists are kept consistent with the surviving properties so Google's server
    won't reject the connect.
    """

    if isinstance(node, dict):
        result: dict[str, object] = {}
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                result[key] = {
                    name: _sanitize_schema_for_google(schema)
                    for name, schema in value.items()
                }
            elif key in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            else:
                result[key] = _sanitize_schema_for_google(value)
        _prune_required(result)
        return result
    if isinstance(node, list):
        return [_sanitize_schema_for_google(item) for item in node]
    return node


def _prune_required(node: dict[str, object]) -> None:
    """Drop ``required`` entries that don't name a surviving property.

    Mirrors Google's server-side check: every name in ``required`` must exist in
    ``properties``. Guards against upstream schemas (or sanitizer side effects)
    that reference a property Google will never see.
    """

    properties = node.get("properties")
    required = node.get("required")
    if isinstance(properties, dict) and isinstance(required, list):
        kept = [name for name in required if name in properties]
        if kept:
            node["required"] = kept
        else:
            node.pop("required", None)


def _tool_name(tool: mcp.MCPTool) -> str:
    info = getattr(tool, "info", None)
    return getattr(info, "name", "") if info is not None else ""


class PlaywrightMCPServer(mcp.MCPServerStdio):
    """Launches the Playwright MCP server headless in an isolated profile.

    ``--isolated`` keeps the browser profile in memory and throws it away on
    exit, so each session starts from a clean, logged-out browser. Image
    responses are omitted so screenshot payloads don't bloat the voice context.
    """

    def __init__(self, *, timeout_seconds: float = 120) -> None:
        super().__init__(
            command="npx",
            args=[
                "-y",
                PLAYWRIGHT_MCP_PACKAGE,
                "--headless",
                "--browser",
                "chromium",
                "--isolated",
                "--image-responses",
                "omit",
                "--caps",
                PLAYWRIGHT_MCP_CAPS,
            ],
            client_session_timeout_seconds=timeout_seconds,
        )


class PlaywrightBrowserToolset(mcp.MCPToolset):
    """Exposes the Playwright browser tools to FRIDAY as a single toolset.

    Args:
        allowed_tools: Tool names to expose after the server connects. Defaults
            to every Playwright MCP tool except the noisy debug/telemetry ones.
    """

    def __init__(self, *, allowed_tools: set[str] | None = None) -> None:
        self._allowed_tools = (
            allowed_tools if allowed_tools is not None else set(DEFAULT_BROWSER_TOOLS)
        )
        server = PlaywrightMCPServer()
        super().__init__(id=BROWSER_TOOLSET_ID, mcp_server=server)
        self.server: PlaywrightMCPServer = server

    async def setup(self, *, reload: bool = False) -> Self:
        toolset = await super().setup(reload=reload)
        self.filter_tools(lambda tool: _tool_name(tool) in self._allowed_tools)
        for tool in self._tools:
            if not isinstance(tool, mcp.MCPTool):
                continue
            parameters = tool.info.raw_schema.get("parameters")
            if isinstance(parameters, dict):
                tool.info.raw_schema["parameters"] = _sanitize_schema_for_google(
                    parameters
                )
        return toolset


browser_toolset = PlaywrightBrowserToolset()
