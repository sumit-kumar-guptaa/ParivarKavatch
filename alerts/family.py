"""Family alert sender. Mock implementation writes to a local log only."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.llm import LIVE_SETUP_TODO, ProviderNotConfigured


async def send_family_alert(
    *,
    parent_id: int,
    contact_name: str,
    channel: str,
    message: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Send a mock family alert. Live delivery is a documented TODO."""
    if settings.use_mocks:
        await asyncio.to_thread(
            _append_mock_alert,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "parent_id": parent_id,
                "contact_name": contact_name,
                "channel": channel,
                "session_id": session_id,
                "message": message,
                "provider": "mock",
            },
        )
        return {
            "sent": True,
            "provider": "mock",
            "contact_name": contact_name,
            "channel": channel,
            "message": message,
        }

    # TODO(FAMILY ALERT PROVIDER): replace with the chosen SMS/WhatsApp provider.
    # Check provider docs for endpoint, auth, template approval, and consent rules.
    # Never send real personal data from this training app.
    raise ProviderNotConfigured(LIVE_SETUP_TODO)


def _append_mock_alert(payload: dict[str, Any]) -> None:
    path = Path(settings.alert_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
