"""Environment-driven configuration for the GLPI connector."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class GLPIConfig:
    base_url: str
    app_token: str
    user_token: str
    page_size: int = 100
    request_timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 1.5
    verify_ssl: bool = True

    @staticmethod
    def from_env(dotenv_path: str | None = None) -> "GLPIConfig":
        load_dotenv(dotenv_path=dotenv_path, override=False)

        base_url = os.getenv("GLPI_BASE_URL", "").strip().rstrip("/")
        app_token = os.getenv("GLPI_APP_TOKEN", "").strip()
        user_token = os.getenv("GLPI_USER_TOKEN", "").strip()

        missing = [
            n for n, v in [
                ("GLPI_BASE_URL", base_url),
                ("GLPI_APP_TOKEN", app_token),
                ("GLPI_USER_TOKEN", user_token),
            ] if not v
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Set them in your .env file (see .env.example)."
            )

        return GLPIConfig(
            base_url=base_url,
            app_token=app_token,
            user_token=user_token,
            page_size=int(os.getenv("GLPI_PAGE_SIZE", "100")),
            request_timeout=float(os.getenv("GLPI_TIMEOUT", "30")),
            max_retries=int(os.getenv("GLPI_MAX_RETRIES", "3")),
            retry_backoff=float(os.getenv("GLPI_RETRY_BACKOFF", "1.5")),
            verify_ssl=os.getenv("GLPI_VERIFY_SSL", "true").lower() != "false",
        )
