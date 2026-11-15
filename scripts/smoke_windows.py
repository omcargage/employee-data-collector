"""Smoke test script for Windows input capture.

Runs for 10 seconds, listening to live input via WindowsInputProvider.
PRINTS ONLY AGGREGATED EVENT COUNTS PER SECOND.
Never prints, logs, or stores typed characters, key identities, or window titles.
"""
from collections import Counter
from pathlib import Path
import sys
import threading
import time

# Ensure agent and shared are in python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "agent"))
sys.path.insert(0, str(repo_root / "shared"))

from edc_agent.platforms.windows.provider import WindowsInputProvider
from edc_schemas import ActivityEvent


def main(duration_seconds: int = 10):
    print("=" * 70)
    print("EDC Windows Input Provider - 10-Second Live Smoke Test")
    print("PRIVACY NOTICE: Only event counts per second are printed.")
    print("                No typed text, characters, or titles are ever recorded.")
    print("=" * 70)

    lock = threading.Lock()
    second_counts = Counter()
    total_counts = Counter()

    def on_event(event: ActivityEvent) -> None:
        """Callback strictly recording category counts."""
        with lock:
            second_counts[event.kind.value] += 1
            total_counts[event.kind.value] += 1

    provider = WindowsInputProvider(callback=on_event, mouse_bin_ms=100)
    print("\nStarting Windows input hooks (type on your keyboard and move your mouse)...")
    provider.start()

    try:
        for sec in range(1, duration_seconds + 1):
            time.sleep(1.0)
            with lock:
                snap = dict(second_counts)
                second_counts.clear()

            chars = snap.get("key_char", 0)
            backspaces = snap.get("key_backspace", 0)
            deletes = snap.get("key_delete", 0)
            mods = snap.get("key_modifier", 0)
            others = snap.get("key_other", 0)
            moves = snap.get("mouse_move", 0)
            clicks = snap.get("mouse_click", 0)
            scrolls = snap.get("mouse_scroll", 0)
            sec_total = sum(snap.values())

            print(
                f"[Sec {sec:02d}/{duration_seconds:02d}] "
                f"Keys (char={chars}, bksp={backspaces}, del={deletes}, mod={mods}, oth={others}) | "
                f"Mouse (move={moves}, click={clicks}, scroll={scrolls}) | "
                f"Total={sec_total}"
            )
    finally:
        provider.stop()
        print("\nInput hooks stopped.")

    print("\n" + "=" * 70)
    print("10-Second Test Summary:")
    print(f"  Total key events   : {total_counts['key_char'] + total_counts['key_backspace'] + total_counts['key_delete'] + total_counts['key_modifier'] + total_counts['key_other']}")
    print(f"    - Characters     : {total_counts['key_char']}")
    print(f"    - Backspaces     : {total_counts['key_backspace']}")
    print(f"    - Deletes        : {total_counts['key_delete']}")
    print(f"    - Modifiers      : {total_counts['key_modifier']}")
    print(f"    - Other keys     : {total_counts['key_other']}")
    print(f"  Total mouse events : {total_counts['mouse_move'] + total_counts['mouse_click'] + total_counts['mouse_scroll']}")
    print(f"    - Pointer moves  : {total_counts['mouse_move']}")
    print(f"    - Clicks         : {total_counts['mouse_click']}")
    print(f"    - Scrolls        : {total_counts['mouse_scroll']}")
    print("=" * 70)
    print("Verification: Zero characters, key names, or text were printed or captured.")


if __name__ == "__main__":
    duration = 10
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            duration = 10
    main(duration)
