"""Privacy subpackage enforcing strict data redaction, consent, and BAT-12 burnout surveys."""
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
    BAT12_QUESTIONS,
    LIKERT_LABELS,
    BAT12Summary,
    compute_bat12_scores,
    get_all_bat12_by_day,
    get_all_checkins_by_day,
    get_bat12_for_day,
    get_checkin_for_day,
    prompt_bat12_checkin,
    prompt_checkin,
    record_bat12_checkin,
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
    "BAT12_QUESTIONS",
    "LIKERT_LABELS",
    "BAT12Summary",
    "compute_bat12_scores",
    "record_bat12_checkin",
    "get_bat12_for_day",
    "get_all_bat12_by_day",
    "prompt_bat12_checkin",
    "record_checkin",
    "get_checkin_for_day",
    "get_all_checkins_by_day",
    "prompt_checkin",
    "validate_rating",
]
