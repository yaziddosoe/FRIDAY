import json
import os

from google.genai import types as genai_types
from livekit.agents.types import NOT_GIVEN
from livekit.plugins.google.realtime import RealtimeModel

from agent import Assistant
from browser_tool import DEFAULT_BROWSER_TOOLS, _sanitize_schema_for_google

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
