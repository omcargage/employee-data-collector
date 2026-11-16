"""Persistent hardware device identity management."""
import uuid
from edc_agent.storage.database import Database


def get_or_create_device_id(db: Database) -> str:
    """Retrieve or generate a stable unique device ID stored in agent_state."""
    device_id = db.get_agent_state("device_id")
    if device_id:
        return device_id

    # Generate persistent device ID
    new_id = f"dev-{uuid.uuid4().hex[:16]}"
    db.set_agent_state("device_id", new_id)
    return new_id
