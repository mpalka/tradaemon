"""Optional outbound alert webhook (off unless ALERT_WEBHOOK_URL is set).

Sends a generic JSON payload that works for Discord ("content"), Slack/Mattermost
("text"), and most simple webhooks. Best-effort: never raises, short timeout, so
a webhook outage cannot stall the trading loop. Sending to an external service is
the user's explicit opt-in via the env var — there is no default endpoint.
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def send_webhook(url: str | None, message: str, timeout: float = 3.0) -> bool:
    if not url:
        return False
    payload = json.dumps({"content": message, "text": message}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 - best-effort; a webhook outage must not stall trading
        log.warning("alert webhook failed (non-fatal)", exc_info=False)
        return False
