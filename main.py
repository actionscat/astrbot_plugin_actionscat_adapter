from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from actionscat_adapter.client import ActionsCatClient
from actionscat_adapter.env import load_settings


PLUGIN_DIR = Path(__file__).resolve().parent


@register(
    "actionscat_adapter",
    "purouity",
    "Minimal AstrBot adapter for ActionsCat/core.",
    "0.1.0",
)
class ActionsCatAdapter(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.settings = load_settings(PLUGIN_DIR)
        self.client = ActionsCatClient(self.settings)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def forward_to_actionscat(self, event: AstrMessageEvent):
        payload = build_actionscat_payload(event)

        try:
            result = await self.client.dispatch(payload)
        except Exception as exc:
            # Do not disturb the chat when ActionsCat/core is unavailable.
            print(f"[actionscat-adapter] dispatch failed: {exc}")
            return

        async for response in build_astrbot_response(event, result):
            yield response

    async def terminate(self):
        await self.client.close()


def build_actionscat_payload(event: AstrMessageEvent) -> dict[str, str]:
    """Build the only contract this adapter sends to ActionsCat/core.

    raw_msg is passed through exactly as obtained from AstrBot. This function does
    not strip, normalize, replace, or parse it.
    """
    return {
        "sender_qq": _extract_sender_qq(event),
        "current_group": _extract_current_group(event),
        "raw_msg": _extract_raw_msg(event),
    }


def _extract_sender_qq(event: AstrMessageEvent) -> str:
    value = _call(event, "get_sender_id")
    if value is not None:
        return str(value)

    sender = _getattr_chain(event, "message_obj", "sender")
    value = _first_attr(sender, "user_id", "id", "sender_id")
    if value is not None:
        return str(value)

    value = _first_attr(event, "sender_id", "user_id")
    return "" if value is None else str(value)


def _extract_current_group(event: AstrMessageEvent) -> str:
    value = _call(event, "get_group_id")
    if value:
        return str(value)

    value = _first_attr(event, "group_id")
    if value:
        return str(value)

    value = _getattr_chain(event, "message_obj", "group_id")
    if value:
        return str(value)

    return "dm"


def _extract_raw_msg(event: AstrMessageEvent) -> str:
    value = _call(event, "get_message_str")
    if value is not None:
        return str(value)

    value = _first_attr(event, "message_str", "raw_message", "raw_msg")
    if value is not None:
        return str(value)

    value = _first_attr(_getattr_chain(event, "message_obj"), "message_str", "raw_message", "raw_msg")
    if value is not None:
        return str(value)

    return ""


async def build_astrbot_response(
    event: AstrMessageEvent,
    result: Any,
) -> AsyncGenerator[Any, None]:
    if result is None:
        return

    if isinstance(result, str):
        if result:
            yield event.plain_result(result)
        return

    if not isinstance(result, dict):
        yield event.plain_result(str(result))
        return

    if _is_no_match(result):
        return

    messages = result.get("messages")
    if isinstance(messages, list):
        for item in messages:
            response = _message_to_result(event, item)
            if response is not None:
                yield response
        return

    response = _message_to_result(event, result)
    if response is not None:
        yield response


def _is_no_match(result: dict[str, Any]) -> bool:
    code = str(result.get("code") or result.get("status") or "").upper()
    if code == "NO_MATCH":
        return True
    if result.get("ok") is False and not result.get("messages"):
        return True
    return False


def _message_to_result(event: AstrMessageEvent, item: Any) -> Any | None:
    if item is None:
        return None

    if isinstance(item, str):
        return event.plain_result(item) if item else None

    if not isinstance(item, dict):
        return event.plain_result(str(item))

    msg_type = str(item.get("type") or "text")

    if msg_type in {"text", "plain"}:
        text = item.get("text") or item.get("content") or item.get("reply")
        return event.plain_result(str(text)) if text is not None else None

    if msg_type in {"image", "image_url"}:
        url = item.get("url") or item.get("image_url")
        return event.image_result(str(url)) if url else None

    text = item.get("text") or item.get("content") or item.get("reply")
    return event.plain_result(str(text)) if text is not None else None


def _call(obj: Any, name: str) -> Any:
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            return None
    return None


def _first_attr(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _getattr_chain(obj: Any, *names: str) -> Any:
    current = obj
    for name in names:
        if current is None or not hasattr(current, name):
            return None
        current = getattr(current, name)
    return current
