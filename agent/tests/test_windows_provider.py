"""Tests for WindowsInputProvider enforcing non-negotiable privacy boundaries and auto-repeat rules."""
import ast
from pathlib import Path
import time
from typing import List
import pytest
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from edc_agent.platforms.windows.provider import WindowsInputProvider
from edc_schemas import ActivityEvent, EventKind


def test_static_ast_privacy_check():
    """Static AST check asserting that provider.py never stores or retains raw key identities."""
    provider_file = (
        Path(__file__).parent.parent
        / "edc_agent"
        / "platforms"
        / "windows"
        / "provider.py"
    )
    assert provider_file.exists(), f"File not found: {provider_file}"

    source = provider_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_attributes = {
        "raw_key", "key_name", "key_char", "typed_text", "keystroke_char",
        "char_value", "key_code", "vk", "scan_code"
    }

    has_del_key = False

    for node in ast.walk(tree):
        # 1. Assert no forbidden attribute assignment on self or any object
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, (
                f"Forbidden attribute access found: {node.attr} on line {node.lineno}"
            )

        # 2. Assert no dict or list is storing key objects
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assert target.id not in forbidden_attributes, (
                        f"Forbidden variable assignment found: {target.id} on line {node.lineno}"
                    )

        # 3. Detect 'del key' statement ensuring explicit reference destruction
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "key":
                    has_del_key = True

    assert has_del_key, "provider.py must explicitly contain 'del key' in callbacks"


def test_dynamic_event_inspection_no_key_identity():
    """Verify dynamically emitted ActivityEvents never contain key identity or text."""
    emitted: List[ActivityEvent] = []
    provider = WindowsInputProvider(callback=emitted.append)

    test_keys = [
        KeyCode.from_char("a"),
        KeyCode.from_char("Z"),
        KeyCode.from_char("9"),
        KeyCode.from_char("@"),
        Key.space,
        Key.enter,
        Key.backspace,
        Key.delete,
        Key.shift,
        Key.ctrl,
    ]

    for k in test_keys:
        provider._on_press(k)
        provider._on_release(k)

    assert len(emitted) > 0

    forbidden_strings = ["a", "Z", "9", "@", "space", "enter", "backspace", "delete", "shift", "ctrl"]

    for ev in emitted:
        # 1. Event kind must be valid anonymous EventKind
        assert isinstance(ev.kind, EventKind)

        # 2. Coordinate and button fields must be None for keyboard events
        assert ev.x is None
        assert ev.y is None
        assert ev.button is None
        assert ev.scroll_ticks is None

        # 3. No field or serialized payload may contain raw key identities
        payload_dump = ev.model_dump()
        for k, val in payload_dump.items():
            if isinstance(val, str) and val not in {e.value for e in EventKind}:
                for forbidden in forbidden_strings:
                    assert forbidden not in val.lower(), f"Leaked key identity '{val}' in field '{k}'"

    # Verify provider internal state only tracks anonymous class or None
    assert provider._held_non_modifier is None or isinstance(provider._held_non_modifier, EventKind)


def test_held_key_auto_repeat_rules():
    """Verify that held-key auto-repeats collapse for characters but count for backspace/delete."""
    emitted: List[ActivityEvent] = []
    provider = WindowsInputProvider(callback=emitted.append)

    # 1. Held printable character 'x' (3 key-down presses without key-up)
    key_x = KeyCode.from_char("x")
    provider._on_press(key_x)
    provider._on_press(key_x)  # auto-repeat
    provider._on_press(key_x)  # auto-repeat

    # Must collapse: exactly 1 event emitted
    assert len(emitted) == 1
    assert emitted[0].kind == EventKind.KEY_CHAR

    # Release 'x'
    provider._on_release(key_x)
    assert provider._held_non_modifier is None

    # Next single press of 'x' is counted
    provider._on_press(key_x)
    assert len(emitted) == 2
    provider._on_release(key_x)

    # 2. Held Backspace (3 key-down presses without key-up)
    emitted.clear()
    provider._on_press(Key.backspace)
    provider._on_press(Key.backspace)  # auto-repeat
    provider._on_press(Key.backspace)  # auto-repeat
    provider._on_release(Key.backspace)

    # Must NOT collapse: all 3 backspaces count as corrections
    assert len(emitted) == 3
    assert all(e.kind == EventKind.KEY_BACKSPACE for e in emitted)

    # 3. Held Delete (2 key-down presses without key-up)
    emitted.clear()
    provider._on_press(Key.delete)
    provider._on_press(Key.delete)  # auto-repeat
    provider._on_release(Key.delete)

    # Must NOT collapse: both delete presses count as corrections
    assert len(emitted) == 2
    assert all(e.kind == EventKind.KEY_DELETE for e in emitted)


def test_mouse_events_coalesce_and_click_rules():
    """Verify mouse moves are coalesced, clicks emit on button-down, and scrolls are signed."""
    emitted: List[ActivityEvent] = []
    provider = WindowsInputProvider(callback=emitted.append, mouse_bin_ms=20)

    # 1. Mouse move coalescing: 10 moves within 10ms -> only 1 event emitted
    for i in range(10):
        provider._on_move(100.0 + i, 200.0 + i)
    assert len(emitted) == 1
    assert emitted[0].kind == EventKind.MOUSE_MOVE
    assert emitted[0].x == 100.0
    assert emitted[0].y == 200.0

    # Move after coalesce interval expires (20ms)
    time.sleep(0.08)
    provider._on_move(350.0, 450.0)
    assert len(emitted) == 2
    assert emitted[1].x == 350.0
    assert emitted[1].y == 450.0

    # 2. Clicks: only button-down (pressed=True) emits
    emitted.clear()
    provider._on_click(120.0, 240.0, Button.left, pressed=True)   # button 1
    provider._on_click(120.0, 240.0, Button.left, pressed=False)  # button release ignored
    provider._on_click(125.0, 245.0, Button.right, pressed=True)  # button 2
    provider._on_click(125.0, 245.0, Button.middle, pressed=True) # button 3

    assert len(emitted) == 3
    assert [e.button for e in emitted] == [1, 2, 3]

    # 3. Scroll: signed ticks
    emitted.clear()
    provider._on_scroll(100.0, 100.0, 0, 3)   # scroll up
    provider._on_scroll(100.0, 100.0, 0, -5)  # scroll down
    assert len(emitted) == 2
    assert emitted[0].scroll_ticks == 3
    assert emitted[1].scroll_ticks == -5
