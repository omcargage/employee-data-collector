"""Interactive and verification script for Windows session lock/unlock and power states.

Registers Windows session notifications via ctypes and logs state events with timestamps.
Can run in live monitoring mode or self-test verification mode.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

# Ensure agent and shared are in python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "agent"))
sys.path.insert(0, str(repo_root / "shared"))

from edc_agent.platforms.windows.system_state import (
    SystemState,
    SystemStateEvent,
    WindowsSystemStateMonitor,
)
from edc_agent.collectors.gap_classifier import GapType, classify_gap


def main(listen_seconds: int = 5):
    print("=" * 70)
    print("EDC Windows System State Monitor - Lock / Unlock / Suspend Detection")
    print("Listening via ctypes wtsapi32.WTSRegisterSessionNotification...")
    print("=" * 70)

    logged_events = []

    def on_state_event(event: SystemStateEvent) -> None:
        local_time_str = event.ts_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{local_time_str}] STATE EVENT: {event.state.value.upper()} (UTC: {event.ts_utc.isoformat()})")
        logged_events.append(event)

    monitor = WindowsSystemStateMonitor(callback=on_state_event)
    monitor.start()
    print(f"\n[INFO] Monitor active for {listen_seconds} seconds.")
    print("       (Lock your screen with Win+L to test live detection, or wait for simulated test)")

    try:
        # If running in non-interactive/quick test mode, emit a verification cycle
        time.sleep(1.0)
        t_lock = datetime.now(timezone.utc)
        print(f"[TEST LOG] Emitting verification LOCK event at {t_lock.isoformat()}...")
        monitor.emit(SystemState.LOCK, ts_utc=t_lock)

        time.sleep(1.0)
        t_unlock = datetime.now(timezone.utc)
        print(f"[TEST LOG] Emitting verification UNLOCK event at {t_unlock.isoformat()}...")
        monitor.emit(SystemState.UNLOCK, ts_utc=t_unlock)

        # Allow remaining listen time
        remaining = max(0.0, listen_seconds - 2.0)
        if remaining > 0:
            time.sleep(remaining)
    finally:
        monitor.stop()
        print("\n[INFO] Monitor stopped.")

    print("\n" + "=" * 70)
    print(f"Logged {len(logged_events)} state transition events:")
    for idx, ev in enumerate(logged_events, 1):
        print(f"  {idx}. {ev.state.value.upper():<7} at {ev.ts_utc.isoformat()}")

    # Classify a sample gap spanning the lock/unlock period
    if len(logged_events) >= 2:
        gap_start = logged_events[0].ts_utc
        gap_end = logged_events[-1].ts_utc
        classification = classify_gap(gap_start, gap_end, state_events=logged_events)
        print(f"\nGap Classification across [{gap_start.isoformat()} to {gap_end.isoformat()}]:")
        print(f"  Result -> {classification.value.upper()} (expected: AWAY)")
        assert classification == GapType.AWAY, "Expected gap to be classified as AWAY"
    print("=" * 70)
    print("System state monitoring verification complete.")


if __name__ == "__main__":
    dur = 5
    if len(sys.argv) > 1:
        try:
            dur = int(sys.argv[1])
        except ValueError:
            dur = 5
    main(dur)
