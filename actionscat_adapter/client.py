from __future__ import annotations

from typing import Any

import httpx

from .env import Settings


class ActionsCatClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def dispatch(self, payload: dict[str, Any]) -> Any:
        response = await self._client.post(self.settings.dispatch_url, json=payload)
        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return None

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return response.text
