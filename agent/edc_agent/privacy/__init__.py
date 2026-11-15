"""Privacy subpackage enforcing strict data redaction and consent verification rules.

Manages plain-language consent disclosure, voluntary daily check-in labels,
registry-compliant CSV exports, and full local data wiping.
"""
from .consent import (
    CONSENT_NOTICE_TEXT,
    CONSENT_NOTICE_VERSION,
    get_consent_notice,
    has_consent,
    prompt_for_consent,
    record_consent,
    revoke_consent,
)
from .delete import delete_all_data
from .export import export_data_to_csv, load_registry_columns
from .self_report import (
    get_all_checkins_by_day,
    get_checkin_for_day,
    prompt_checkin,
    record_checkin,
    validate_rating,
)

__all__ = [
    "CONSENT_NOTICE_TEXT",
    "CONSENT_NOTICE_VERSION",
    "get_consent_notice",
    "has_consent",
    "prompt_for_consent",
    "record_consent",
    "revoke_consent",
    "delete_all_data",
    "export_data_to_csv",
    "load_registry_columns",
    "record_checkin",
    "get_checkin_for_day",
    "get_all_checkins_by_day",
    "prompt_checkin",
    "validate_rating",
]
