import json
import os

from google.genai import types as genai_types
from livekit.agents.types import NOT_GIVEN
from livekit.agents.worker import ServerEnvOption
from livekit.plugins.google.realtime import RealtimeModel

import agent
from agent import Assistant, server
from browser_tool import DEFAULT_BROWSER_TOOLS, _sanitize_schema_for_google
from memory import MemoryStore

_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _to_gemini_types(schema: object) -> object:
    """Minimal re-implementation of the plugin's JSON-Schema-to-Gemini mapping.

    Mirrors what the Google realtime plugin does before validating a raw tool
    schema as a ``FunctionDeclaration`` (the exact step that crashed on the
    un-sanitized ``browser_drop`` map parameter).
    """

    if isinstance(schema, dict):
        mapped: dict[str, object] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str) and value in _TYPE_MAP:
                mapped[key] = _TYPE_MAP[value]
            else:
                mapped[key] = _to_gemini_types(value)
        return mapped
    if isinstance(schema, list):
        return [_to_gemini_types(item) for item in schema]
    return schema


def test_assistant_uses_supported_gemini_realtime_model() -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    assistant = Assistant()

    assert isinstance(assistant.llm, RealtimeModel)
    assert assistant.llm.model == "gemini-2.5-flash-native-audio-preview-12-2025"
    assert assistant.llm._opts.voice == "Rasalgethi"
    # Respond as soon as the user stops talking: shorter end-of-turn silence.
    assert (
        assistant.llm._opts.realtime_input_config.automatic_activity_detection.silence_duration_ms
        == 400
    )
    # Thinking transcripts must not leak into the conversation.
    assert assistant.llm._opts.thinking_config.include_thoughts is False
    # Native audio models auto-select the spoken language, so a fixed language
    # code (e.g. the old malformed "en-GB,") must not be sent.
    assert assistant.llm._opts.language is NOT_GIVEN
    assert assistant.llm.capabilities.audio_output is True


def test_browser_drop_is_not_exposed_by_default() -> None:
    # Google's realtime API can't express browser_drop's `data` map parameter
    # (propertyNames/additionalProperties), which crashed FunctionDeclaration
    # validation at session start. It must never be in the default toolset.
    assert "browser_drop" not in DEFAULT_BROWSER_TOOLS


def test_sanitizer_strips_google_unsupported_schema_keys() -> None:
    sanitized = _sanitize_schema_for_google(
        {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "propertyNames": {"type": "string"},
                    "additionalProperties": {"type": "string"},
                },
                "target": {"type": "string"},
            },
            "required": ["target"],
        }
    )

    assert "propertyNames" not in json.dumps(sanitized)
    assert "additionalProperties" not in json.dumps(sanitized)
    assert sanitized["properties"]["target"] == {"type": "string"}
    assert sanitized["required"] == ["target"]


def test_sanitized_schema_validates_as_function_declaration() -> None:
    # Mirrors create_tools_config's FunctionDeclaration.model_validate(), the
    # site of the browser_drop crash.
    declaration = genai_types.FunctionDeclaration.model_validate(
        {
            "name": "browser_drag",
            "description": "",
            "parameters": _to_gemini_types(
                _sanitize_schema_for_google(
                    {
                        "type": "object",
                        "properties": {
                            "data": {
                                "type": "object",
                                "propertyNames": {"type": "string"},
                                "additionalProperties": {"type": "string"},
                            }
                        },
                    }
                )
            ),
        }
    )

    assert declaration.name == "browser_drag"


def _tool_names(assistant: Assistant) -> set[str]:
    names: set[str] = set()
    for tool in assistant.tools:
        functions = getattr(tool, "functions", None)
        if functions is not None:
            names.update(getattr(fn, "name", "") for fn in functions)
            continue
        info = getattr(tool, "info", None)
        if info is not None and info.name:
            names.add(info.name)
        elif getattr(tool, "__name__", None):
            names.add(tool.__name__)
    return names


def test_memory_tools_are_registered(tmp_path) -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    assistant = Assistant(memory_path=str(tmp_path / "none.db"))

    names = _tool_names(assistant)
    assert {"get_current_datetime", "remember_fact", "forget_fact"} <= names
    assert "search_web" in names


def test_bridge_tools_are_registered(tmp_path) -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    assistant = Assistant(memory_path=str(tmp_path / "none.db"))

    names = _tool_names(assistant)
    assert {
        "get_system_status",
        "create_note",
        "list_notes",
        "delete_note",
        "start_timer",
        "list_timers",
        "cancel_timer",
        "schedule_reminder",
        "list_reminders",
        "cancel_reminder",
        "launch_app",
        "search_files",
        "open_file",
        "take_screenshot",
        "media_control",
    } <= names


def test_browser_mcp_toolset_excluded_from_default_session(tmp_path) -> None:
    # The Playwright MCP subprocess has repeatedly crashed mid-session
    # (anyio.BrokenResourceError), taking calls down. It is excluded until Phase 3
    # ships a supervised, crash-proof browser channel.
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    assistant = Assistant(memory_path=str(tmp_path / "none.db"))

    assert "PlaywrightBrowserToolset" not in _tool_names(assistant)


def test_memory_facts_are_injected_into_instructions(tmp_path) -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    db = tmp_path / "friday.db"
    MemoryStore(db).add_fact("The user is called Steve")
    assistant = Assistant(memory_path=str(db))

    instructions = assistant.instructions
    assert "The user is called Steve" in instructions
    assert "# Things you remember about the user" in instructions


def test_worker_prewarms_idle_process() -> None:
    # A warm process removes the multi-second cold start (process spawn +
    # dependency imports) that delayed agent joins and triggered client-side
    # publish timeouts. It must stay enabled in dev mode too.
    assert ServerEnvOption.getvalue(server._num_idle_processes, devmode=True) == 1
    assert ServerEnvOption.getvalue(server._num_idle_processes, devmode=False) == 1
    # The idle executor's setup pass must not be a no-op: it pre-warms it.
    assert server._setup_fnc is agent._prewarm_job_process


def test_worker_setup_fnc_prewarms_native_models() -> None:
    # The setup pass must eagerly load the native VAD/EOT inference models so
    # the first session doesn't block the agent loop loading them mid-join
    # (which delayed publishing and tripped client-side connect timeouts).
    assert server._setup_fnc(None) is None


def test_ssl_context_cache_reuses_built_context() -> None:
    # Creating the default SSL context costs ~1-3s of CPU per call here, and
    # google-genai rebuilds one inside every RealtimeSession on the agent
    # loop; the stacked stalls delayed joins and even aborted the worker via a
    # FFI ReadyForRoom timeout. Identical calls must reuse one context.
    import ssl

    assert ssl.create_default_context is agent._cached_create_default_context
    server_auth = agent._cached_create_default_context()
    assert agent._cached_create_default_context() is server_auth
    # Purposes are configured differently, so each key builds its own context.
    client_auth = agent._cached_create_default_context(ssl.Purpose.CLIENT_AUTH)
    assert client_auth is not server_auth


def test_sfu_keep_warm_host_parsing() -> None:
    # Keep-warm pokes the endpoint named by LIVEKIT_URL so the Rust room
    # engine's join attempts ride a warm DNS/nat path. Host parsing is pure.
    assert agent._sfu_netloc("wss://friday-u9lr9kmy.livekit.cloud") == (
        "friday-u9lr9kmy.livekit.cloud",
        443,
    )
    assert agent._sfu_netloc("wss://foo.example:7880/some?x=1") == ("foo.example", 7880)
    assert agent._sfu_netloc("ws://a.b") == ("a.b", 443)
    assert agent._sfu_netloc("nonsense") is None
    assert agent._sfu_netloc("") is None


def test_empty_memory_adds_privacy_note_only(tmp_path) -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "test-key")

    assistant = Assistant(memory_path=str(tmp_path / "none.db"))

    instructions = assistant.instructions
    assert "# Things you remember about the user" not in instructions
    assert "Never reveal private data such as passwords" in instructions


def test_call_greeting_is_welcome_back_sir(tmp_path) -> None:
    assistant = Assistant(memory_path=str(tmp_path / "none.db"))
    assert "Welcome back, sir" in assistant.instructions


def test_introduction_script_is_present(tmp_path) -> None:
    assistant = Assistant(memory_path=str(tmp_path / "none.db"))
    assert "virtual artificial intelligence" in assistant.instructions
    assert "Allow me to introduce myself" in assistant.instructions


def test_weather_tool_pointed_in_instructions(tmp_path) -> None:
    assistant = Assistant(memory_path=str(tmp_path / "none.db"))
    assert "get_weather" in assistant.instructions


def test_weather_tool_registered(tmp_path) -> None:
    assistant = Assistant(memory_path=str(tmp_path / "none.db"))
    names = [
        getattr(getattr(tool, "info", None), "name", "") or getattr(tool, "name", "")
        for tool in assistant.tools
    ]
    assert any("get_weather" in name for name in names)
