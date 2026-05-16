from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


def load_settings(plugin_dir: Path | None = None) -> Settings:
    if plugin_dir is not None:
        load_dotenv(plugin_dir / ".env")

    return Settings(
        scheme=os.getenv("ACTIONSCAT_BACKEND_SCHEME", "http"),
        host=os.getenv("ACTIONSCAT_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("ACTIONSCAT_BACKEND_PORT", "8080")),
        path=os.getenv("ACTIONSCAT_DISPATCH_PATH", "/v1/actions/dispatch"),
        timeout_seconds=float(os.getenv("ACTIONSCAT_TIMEOUT_SECONDS", "10")),
    )
