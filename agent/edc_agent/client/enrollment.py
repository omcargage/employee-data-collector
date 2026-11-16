"""Client agent enrollment workflow exchanging one-time token for OS-stored API credentials."""
from datetime import datetime, timezone
import logging
import platform
import sys
from typing import Any, Dict, Optional
import httpx

from edc_agent.client.device_identity import get_or_create_device_id
from edc_agent.client.keyring_store import store_credential
from edc_agent.storage.database import Database

logger = logging.getLogger("edc_agent.client.enrollment")


def enroll_agent(
    server_url: str,
    enrollment_token: str,
    db: Database,
    device_id: Optional[str] = None,
    timeout_s: float = 10.0,
    http_client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Enroll the desktop agent with the backend server using a one-time token."""
    base_url = server_url.rstrip("/")
    enroll_endpoint = f"{base_url}/devices/enroll"

    actual_device_id = device_id or get_or_create_device_id(db)
    client_platform = sys.platform  # "win32", "darwin", "linux"
    os_ver = platform.platform()

    payload = {
        "enrollment_token": enrollment_token.strip(),
        "device_id": actual_device_id,
        "platform": client_platform,
        "os_version": os_ver,
        "agent_version": "0.1.0",
    }

    client = http_client or httpx.Client(timeout=timeout_s)
    try:
        response = client.post(enroll_endpoint, json=payload)
    except Exception as e:
        logger.error("Failed to connect to enrollment server at %s: %s", enroll_endpoint, e)
        raise ConnectionError(f"Could not connect to server at {enroll_endpoint}: {e}") from e
    finally:
        if http_client is None:
            client.close()

    if response.status_code != 200:
        err_msg = response.text
        try:
            err_msg = response.json().get("detail", err_msg)
        except Exception:
            pass
        logger.error("Enrollment rejected by server (%d): %s", response.status_code, err_msg)
        raise ValueError(f"Enrollment failed ({response.status_code}): {err_msg}")

    data = response.json()
    api_key = data.get("api_key")
    if not api_key:
        raise ValueError("Server response missing required 'api_key'")

    # Securely persist API key in the OS credential store
    store_credential(api_key)

    # Record enrollment metadata in agent_state
    now_iso = datetime.now(timezone.utc).isoformat()
    db.set_agent_state("server_url", base_url)
    db.set_agent_state("enrolled_at", now_iso)
    db.set_agent_state("employee_id", data.get("employee_id", ""))
    db.set_agent_state("employee_code", data.get("employee_code", ""))

    logger.info("Agent successfully enrolled with device_id=%s, employee=%s", actual_device_id, data.get("employee_code"))
    return data
