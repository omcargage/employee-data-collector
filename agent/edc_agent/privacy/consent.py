"""Privacy consent management and plain-language disclosure notices.

Enforces the privacy boundary: no collection may begin before explicit consent acknowledgement.
Stores timestamped consent decisions and schema versions in SQLite consent_records.
"""
from datetime import datetime, timezone
from typing import Optional
import sys

from edc_agent.storage.database import Database

CONSENT_NOTICE_VERSION = "1.0.0"

CONSENT_NOTICE_TEXT = f"""
======================================================================
         EMPLOYEE DATA COLLECTOR (EDC) - PRIVACY NOTICE
                       Version {CONSENT_NOTICE_VERSION}
======================================================================

Before data collection can begin on this device, please review and
acknowledge this plain-language disclosure.

WHAT IS COLLECTED:
  • Keyboard behavioral rhythms: typing flight times, dwell times, burst
    lengths, pause intervals, and correction frequencies (backspace/delete).
  • Mouse behavioral dynamics: pointer speed, acceleration, click intervals,
    double-click counts, and scroll tick counts.
  • Work rhythm & focus patterns: session durations, break lengths,
    continuous stretches, focus blocks, and lunch intervals.
  • Time metadata: logical day, hour of day, weekend flags, after-hours
    active minutes, and configured shift coverage ratios.
  • System power state transitions: lock/unlock and suspend/resume events.
  • Voluntary end-of-day check-in ratings (stress, energy, workload).

WHAT IS NEVER COLLECTED (STRICT PRIVACY GUARANTEE):
  • NO typed text, words, characters, numbers, letters, or passwords.
    Key identities are converted to abstract anonymous categories in
    volatile memory and immediately destroyed; raw keys are NEVER stored.
  • NO window titles, application names, process names, or URLs.
  • NO screen captures, screenshots, video, or webcam streams.
  • NO microphone recordings, audio, or speech data.
  • NO email contents, chat messages, or document texts.
  • NO clipboard contents, file contents, or network packet data.

YOUR RIGHTS & CONTROLS:
  • You can pause collection at any time by running: edc pause
  • You can resume collection at any time by running: edc resume
  • You can inspect all locally collected metrics via: edc export-data
  • You can permanently delete all local data via:   edc delete-all-data

======================================================================
"""


def get_consent_notice() -> str:
    """Return the formatted plain-language privacy disclosure notice."""
    return CONSENT_NOTICE_TEXT


def has_consent(db: Database) -> bool:
    """Return True if explicit user consent has been acknowledged and is currently active."""
    row = db.get_latest_consent_record()
    if row is None:
        return False
    return row["status"] == "consented"


def record_consent(db: Database, version: str = CONSENT_NOTICE_VERSION) -> None:
    """Persist explicit user consent acknowledgement in SQLite."""
    now_utc = datetime.now(timezone.utc).isoformat()
    db.insert_consent_record(consented_at=now_utc, version=version, status="consented")


def revoke_consent(db: Database, version: str = CONSENT_NOTICE_VERSION) -> None:
    """Record consent revocation in SQLite."""
    now_utc = datetime.now(timezone.utc).isoformat()
    db.insert_consent_record(consented_at=now_utc, version=version, status="revoked")


def prompt_for_consent(db: Database, auto_ack: bool = False) -> bool:
    """Display the plain-language disclosure and prompt for acknowledgement.

    Returns True if consent is acknowledged, False if declined.
    """
    sys.stdout.write(get_consent_notice())
    sys.stdout.flush()

    if auto_ack:
        record_consent(db, version=CONSENT_NOTICE_VERSION)
        sys.stdout.write("[EDC] Consent acknowledged and recorded.\n")
        sys.stdout.flush()
        return True

    try:
        sys.stdout.write("Do you acknowledge and agree to this data collection? [y/N]: ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if answer in ("y", "yes"):
            record_consent(db, version=CONSENT_NOTICE_VERSION)
            sys.stdout.write("[EDC] Consent acknowledged and recorded. Collection is now permitted.\n")
            sys.stdout.flush()
            return True
        else:
            sys.stdout.write("[EDC] Consent declined. No data will be collected.\n")
            sys.stdout.flush()
            return False
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n[EDC] Consent prompt cancelled. No data will be collected.\n")
        sys.stdout.flush()
        return False
