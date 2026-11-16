"""OS Credential Store integration using keyring for secure agent API key persistence."""
import logging
from typing import Optional
import keyring

logger = logging.getLogger("edc_agent.client.keyring")

SERVICE_NAME = "edc_agent"
CREDENTIAL_USERNAME = "device_credential"

# In-memory fallback dictionary used when OS keyring is mocked or unavailable in CI
_in_memory_store: dict = {}
_use_memory_fallback = False


def enable_memory_keyring(enable: bool = True) -> None:
    """Toggle in-memory mock store for automated testing."""
    global _use_memory_fallback
    _use_memory_fallback = enable
    if not enable:
        _in_memory_store.clear()


def store_credential(api_key: str, service: str = SERVICE_NAME, username: str = CREDENTIAL_USERNAME) -> None:
    """Securely persist the per-device API key in the OS credential store."""
    if _use_memory_fallback:
        _in_memory_store[f"{service}:{username}"] = api_key
        return

    try:
        keyring.set_password(service, username, api_key)
        logger.info("Device credential successfully saved in OS credential store (%s).", service)
    except Exception as e:
        logger.warning("OS credential store unavailable (%s); falling back to memory.", e)
        _in_memory_store[f"{service}:{username}"] = api_key


def get_credential(service: str = SERVICE_NAME, username: str = CREDENTIAL_USERNAME) -> Optional[str]:
    """Retrieve the per-device API key from the OS credential store."""
    if _use_memory_fallback:
        return _in_memory_store.get(f"{service}:{username}")

    try:
        cred = keyring.get_password(service, username)
        if cred is not None:
            return cred
    except Exception as e:
        logger.warning("OS credential store retrieval error (%s); checking memory fallback.", e)

    return _in_memory_store.get(f"{service}:{username}")


def delete_credential(service: str = SERVICE_NAME, username: str = CREDENTIAL_USERNAME) -> bool:
    """Remove stored device credentials from OS credential store."""
    deleted = False
    key = f"{service}:{username}"
    if key in _in_memory_store:
        del _in_memory_store[key]
        deleted = True

    try:
        keyring.delete_password(service, username)
        deleted = True
        logger.info("Device credential deleted from OS credential store (%s).", service)
    except Exception:
        pass

    return deleted
