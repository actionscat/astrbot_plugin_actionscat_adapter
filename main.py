from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

__all__ = ["ActionsCatAdapter"]

PLUGIN_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    scheme: str
    host: str
    port: int
    path: str
    timeout_seconds: float

    @property
    def dispatch_url(self) -> str:
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        return f"{self.scheme}://{self.host}:{self.port}{path}"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_settings(config: dict = None) -> Settings:
    config = config or {}
    load_dotenv(PLUGIN_DIR / ".env")
    
    scheme = config.get("scheme")
    host = config.get("host")
    port = config.get("port")
    path = config.get("path")
    timeout = config.get("timeout_seconds")
    
    return Settings(
        scheme=scheme if scheme else os.getenv("ACTIONSCAT_BACKEND_SCHEME", "http"),
        host=host if host else os.getenv("ACTIONSCAT_BACKEND_HOST", "127.0.0.1"),
        port=int(port) if port is not None else int(os.getenv("ACTIONSCAT_BACKEND_PORT", "8080")),
        path=path if path else os.getenv("ACTIONSCAT_DISPATCH_PATH", "/v1/dispatch"),
        timeout_seconds=float(timeout) if timeout is not None else float(os.getenv("ACTIONSCAT_TIMEOUT_SECONDS", "10")),
    )


class ActionsCatClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def dispatch(self, payload: dict[str, str]) -> tuple[Any, str | None]:
        """Dispatch payload to ActionsCat backend.
        
        Returns:
            tuple: (result, error_message)
                - result: Response data if successful, None otherwise
                - error_message: None if successful, error description if failed
        """
        try:
            response = await self._client.post(self.settings.dispatch_url, json=payload)
            response.raise_for_status()

            if response.status_code == 204 or not response.content:
                return None, None

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json(), None
            return response.text, None
        except httpx.TimeoutException:
            error_msg = f"Backend timeout ({self.settings.timeout_seconds}s) at {self.settings.dispatch_url}"
            return None, error_msg
        except httpx.ConnectError:
            error_msg = f"Cannot connect to backend at {self.settings.dispatch_url}"
            return None, error_msg
        except httpx.HTTPStatusError as e:
            error_msg = f"Backend returned HTTP {e.response.status_code} at {self.settings.dispatch_url}"
            return None, error_msg
        except httpx.RequestError as e:
            error_msg = f"Request failed: {e}"
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {e}"
            return None, error_msg


@register(
    "actionscat_adapter",
    "purouity",
    "Minimal AstrBot adapter for ActionsCat/core.",
    "0.1.1",
)
class ActionsCatAdapter(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.settings = load_settings(config)
        self.client = ActionsCatClient(self.settings)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def forward_to_actionscat(self, event: AstrMessageEvent):
        payload = build_actionscat_payload(event)

        result, error = await self.client.dispatch(payload)
        
        if error:
            logger.error(f"[actionscat-adapter] {error}")
            # Keep chat quiet when backend is unavailable.
            return

        logger.info(f"[actionscat-adapter] Dispatched payload to {self.client.settings.dispatch_url} : {payload}")
        logger.info(f"[actionscat-adapter] Received raw result from backend: {result} (type: {type(result)})")

        async for response in build_astrbot_response(event, result):
            yield response

    async def terminate(self):
        await self.client.close()


def build_actionscat_payload(event: AstrMessageEvent) -> dict[str, str]:
    """The only JSON contract sent to ActionsCat/core.

    raw_msg is passed through exactly as obtained from AstrBot. This function does
    not strip, normalize, replace, parse, or rewrite it.
    """
    return {
        "sender_qq": extract_sender_qq(event),
        "current_group": extract_current_group(event),
        "raw_msg": extract_raw_msg(event),
    }


def extract_sender_qq(event: AstrMessageEvent) -> str:
    value = call_noargs(event, "get_sender_id")
    if value is not None:
        return str(value)

    sender = getattr_chain(event, "message_obj", "sender")
    value = first_attr(sender, "user_id", "id", "sender_id")
    if value is not None:
        return str(value)

    value = first_attr(event, "sender_id", "user_id")
    return "" if value is None else str(value)


def extract_current_group(event: AstrMessageEvent) -> str:
    value = call_noargs(event, "get_group_id")
    if value:
        return str(value)

    value = first_attr(event, "group_id")
    if value:
        return str(value)

    value = getattr_chain(event, "message_obj", "group_id")
    if value:
        return str(value)

    return "dm"


def extract_raw_msg(event: AstrMessageEvent) -> str:
    value = call_noargs(event, "get_message_str")
    if value is not None:
        return str(value)

    value = first_attr(event, "message_str", "raw_message", "raw_msg")
    if value is not None:
        return str(value)

    message_obj = getattr_chain(event, "message_obj")
    value = first_attr(message_obj, "message_str", "raw_message", "raw_msg")
    if value is not None:
        return str(value)

    return ""


async def build_astrbot_response(
    event: AstrMessageEvent,
    result: Any,
) -> AsyncGenerator[Any, None]:
    if result is None:
        return

    # 如果后端返回的不是标准 JSON dict，则静默
    #if not isinstance(result, dict):
    #    return

    # 如果后端返回了业务级别的错误信息（如 detail、error、traceback），拒绝下发到群聊中
    # if "detail" in result or "error" in result or "traceback" in result:
    #    return
        
    # 如果后端返回的是它内部用来测试的 debug_echo，我们也可以在这里直接屏蔽它
    # if result.get("action") == "debug_echo":
    #     return

    if is_no_match(result):
        return

    messages = result.get("messages")
    if isinstance(messages, list):
        for item in messages:
            response = message_to_result(event, item)
            if response is not None:
                yield response
    
    # 严格按照契约：要求后端必须返回 {"messages": [...]} 才执行发送。
    # 丢弃了此前的“将整个 result 字典作为单个消息体解析”的保底逻辑，避免误发调试 JSON。


def is_no_match(result: dict[str, Any]) -> bool:
    code = str(result.get("code") or result.get("status") or "").upper()
    if code == "NO_MATCH":
        return True
    if result.get("ok") is False and not result.get("messages"):
        return True
    return False


def message_to_result(event: AstrMessageEvent, item: Any) -> Any | None:
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


def call_noargs(obj: Any, name: str) -> Any:
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            return None
    return None


def first_attr(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def getattr_chain(obj: Any, *names: str) -> Any:
    current = obj
    for name in names:
        if current is None or not hasattr(current, name):
            return None
        current = getattr(current, name)
    return current
