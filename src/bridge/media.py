import ctypes
import logging

logger = logging.getLogger("bridge.media")

_VK_MEDIA_PLAY_PAUSE = 0xB3
_VK_MEDIA_NEXT = 0xB0
_VK_MEDIA_PREV = 0xB1
_VK_VOLUME_UP = 0xAF
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_MUTE = 0xAD

_ACTIONS = {
    "play_pause": _VK_MEDIA_PLAY_PAUSE,
    "next": _VK_MEDIA_NEXT,
    "previous": _VK_MEDIA_PREV,
    "volume_up": _VK_VOLUME_UP,
    "volume_down": _VK_VOLUME_DOWN,
    "mute": _VK_VOLUME_MUTE,
}


def _send_key(code: int) -> None:
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event(code, 0, 0, 0)
    keybd_event(code, 0, 2, 0)


def media_control(action: str) -> tuple[bool, str]:
    key = action.strip().lower()
    code = _ACTIONS.get(key)
    if code is None:
        return (
            False,
            f"'{action}' is not a media action. Use one of: {', '.join(_ACTIONS)}.",
        )
    try:
        _send_key(code)
    except (AttributeError, OSError) as exc:
        logger.warning("Failed to send media key '%s': %s", action, exc)
        return False, f"I could not control the media player: {exc}"
    label = key.replace("_", " ")
    return True, f"Media: {label}."
