"""Activity event models representing in-memory input occurrences.

Strips all key identifiers, characters, and text at capture time; extra fields are forbidden.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class EventKind(str, Enum):
    """Permitted anonymous event categories."""
    KEY_CHAR = "key_char"
    KEY_BACKSPACE = "key_backspace"
    KEY_DELETE = "key_delete"
    KEY_OTHER = "key_other"
    KEY_MODIFIER = "key_modifier"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"


class ActivityEvent(BaseModel):
    """In-memory event capturing anonymized input timing and coordinates.

    Strictly forbids any textual, character, or key identifier payload.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts_utc: datetime = Field(description="UTC timestamp of the input event")
    kind: EventKind = Field(description="Anonymized category of the event")
    x: Optional[float] = Field(default=None, description="Pointer horizontal coordinate in logical px")
    y: Optional[float] = Field(default=None, description="Pointer vertical coordinate in logical px")
    button: Optional[int] = Field(default=None, description="Mouse button index (e.g. 1=left, 2=right, 3=middle)")
    scroll_ticks: Optional[int] = Field(default=None, description="Vertical/horizontal scroll tick magnitude")
    key_up_ts: Optional[datetime] = Field(default=None, description="Optional key release timestamp for dwell time")
    is_enter: Optional[bool] = Field(default=None, description="True if key is Enter/Return (for message detection)")
