"""Unit tests for macOS and Linux platform adapters.

Validates:
1. macOS Input Monitoring permission detection, capability reporting, and missing permission explanation.
2. Linux display server detection (Wayland vs. X11) and Wayland capability unavailability.
3. Strict AST and dynamic privacy boundary compliance (del key, anonymous EventKind only).
4. Cross-platform factory resolution (get_platform_provider).
"""
import ast
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch
import pytest
from pynput.keyboard import Key, KeyCode

from edc_agent.platforms import get_platform_provider
from edc_agent.platforms.fake import FakeInputProvider
from edc_agent.platforms.linux import (
    LinuxInputProvider,
    WAYLAND_RESTRICTION_EXPLANATION,
    detect_display_server,
    is_wayland,
    is_x11,
)
from edc_agent.platforms.macos import (
    MacOSInputProvider,
    INPUT_MONITORING_EXPLANATION,
    check_input_monitoring_permission,
    is_input_monitoring_granted,
    request_input_monitoring_permission,
)
from edc_agent.platforms.windows.provider import WindowsInputProvider
from edc_schemas import ActivityEvent, EventKind


# ==============================================================================
# 1. macOS Adapter Tests: Permission Detection & Capabilities
# ==============================================================================

def test_macos_capabilities_when_permission_granted():
    """When Input Monitoring is granted on macOS, capabilities report available."""
    provider = MacOSInputProvider(
        callback=lambda ev: None,
        permission_checker=lambda: True,
    )
    caps = provider.get_capabilities()

    assert caps["supported"] is True
    assert caps["input_monitoring_granted"] is True
    assert caps["mouse_move"] is True
    assert caps["mouse_click"] is True
    assert caps["mouse_scroll"] is True
    assert caps["key_dwell"] is False


def test_macos_capabilities_when_permission_missing():
    """When Input Monitoring is missing on macOS, capabilities are unavailable with explanation."""
    provider = MacOSInputProvider(
        callback=lambda ev: None,
        permission_checker=lambda: False,
    )
    caps = provider.get_capabilities()

    assert caps["supported"] is False
    assert caps["input_monitoring_granted"] is False
    assert caps["mouse_move"] is False
    assert caps["mouse_click"] is False
    assert caps["mouse_scroll"] is False
    assert "System Settings" in caps["message"]
    assert "Input Monitoring" in caps["message"]


def test_macos_start_blocks_when_permission_missing():
    """MacOSInputProvider refuses to start listeners if permission is missing."""
    provider = MacOSInputProvider(
        callback=lambda ev: None,
        permission_checker=lambda: False,
    )
    provider.start()

    assert provider.is_running is False
    assert provider._keyboard_listener is None
    assert provider._mouse_listener is None


def test_macos_check_input_monitoring_permission_mocked():
    """Verify check_input_monitoring_permission and request_input_monitoring_permission."""
    # When granted
    with patch("edc_agent.platforms.macos.permissions.is_input_monitoring_granted", return_value=True):
        granted, msg = check_input_monitoring_permission()
        assert granted is True
        assert "granted" in msg

    # When missing
    with patch("edc_agent.platforms.macos.permissions.is_input_monitoring_granted", return_value=False):
        granted, msg = check_input_monitoring_permission()
        assert granted is False
        assert msg == INPUT_MONITORING_EXPLANATION

    # Test ctypes logic mocking on non-darwin platform
    with patch("sys.platform", "darwin"):
        mock_lib = MagicMock()
        mock_lib.CGPreflightListenEventAccess.return_value = 1
        mock_lib.CGRequestListenEventAccess.return_value = 1

        with patch("ctypes.cdll.LoadLibrary", return_value=mock_lib):
            assert is_input_monitoring_granted() is True
            assert request_input_monitoring_permission() is True


def test_macos_ast_privacy_compliance():
    """AST check asserting macOS provider never retains key identities and calls 'del key'."""
    macos_provider_file = (
        Path(__file__).parent.parent
        / "edc_agent"
        / "platforms"
        / "macos"
        / "provider.py"
    )
    assert macos_provider_file.exists()

    source = macos_provider_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_attributes = {
        "raw_key", "key_name", "key_char", "typed_text", "keystroke_char",
        "char_value", "key_code", "vk", "scan_code"
    }

    has_del_key = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, f"Forbidden attribute {node.attr}"
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assert target.id not in forbidden_attributes
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "key":
                    has_del_key = True

    assert has_del_key, "macOS provider must explicitly contain 'del key' in callbacks"


def test_macos_dynamic_event_scrubbing():
    """Verify events emitted by MacOSInputProvider contain only anonymous categories."""
    emitted: List[ActivityEvent] = []
    provider = MacOSInputProvider(
        callback=emitted.append,
        permission_checker=lambda: True,
    )

    test_keys = [
        KeyCode.from_char("k"),
        Key.space,
        Key.backspace,
        Key.delete,
        Key.cmd if hasattr(Key, "cmd") else Key.ctrl,
        Key.enter,
    ]

    for k in test_keys:
        provider._on_press(k)
        provider._on_release(k)

    assert len(emitted) > 0
    forbidden = ["k", "space", "backspace", "delete", "cmd", "enter"]

    for ev in emitted:
        assert isinstance(ev.kind, EventKind)
        dump = ev.model_dump()
        for field_val in dump.values():
            if isinstance(field_val, str) and field_val not in {e.value for e in EventKind}:
                for f in forbidden:
                    assert f not in field_val.lower()


# ==============================================================================
# 2. Linux Adapter Tests: Display Server Detection & Capabilities
# ==============================================================================

def test_linux_detect_display_server():
    """Verify detection of Wayland vs X11 from environment variables."""
    # XDG_SESSION_TYPE takes precedence
    assert detect_display_server({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert is_wayland({"XDG_SESSION_TYPE": "wayland"}) is True
    assert is_x11({"XDG_SESSION_TYPE": "wayland"}) is False

    assert detect_display_server({"XDG_SESSION_TYPE": "x11"}) == "x11"
    assert is_x11({"XDG_SESSION_TYPE": "x11"}) is True
    assert is_wayland({"XDG_SESSION_TYPE": "x11"}) is False

    # WAYLAND_DISPLAY socket fallback
    assert detect_display_server({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"

    # DISPLAY socket fallback
    assert detect_display_server({"DISPLAY": ":0"}) == "x11"

    # Unknown when no env vars set
    assert detect_display_server({}) == "unknown"


def test_linux_capabilities_on_wayland():
    """On Wayland, LinuxInputProvider reports all capabilities unavailable with explanation."""
    provider = LinuxInputProvider(
        callback=lambda ev: None,
        display_server_checker=lambda: "wayland",
    )
    caps = provider.get_capabilities()

    assert caps["supported"] is False
    assert caps["wayland_detected"] is True
    assert caps["display_server"] == "wayland"
    assert caps["mouse_move"] is False
    assert caps["mouse_click"] is False
    assert caps["mouse_scroll"] is False
    assert "Ubuntu on Xorg" in caps["message"]
    assert "GNOME on X11" in caps["message"]


def test_linux_capabilities_on_x11():
    """On X11, LinuxInputProvider reports standard capabilities available."""
    provider = LinuxInputProvider(
        callback=lambda ev: None,
        display_server_checker=lambda: "x11",
    )
    caps = provider.get_capabilities()

    assert caps["supported"] is True
    assert caps["wayland_detected"] is False
    assert caps["display_server"] == "x11"
    assert caps["mouse_move"] is True
    assert caps["mouse_click"] is True
    assert caps["mouse_scroll"] is True
    assert caps["key_dwell"] is False


def test_linux_start_refuses_on_wayland():
    """LinuxInputProvider refuses to start listeners under Wayland."""
    provider = LinuxInputProvider(
        callback=lambda ev: None,
        display_server_checker=lambda: "wayland",
    )
    provider.start()

    assert provider.is_running is False
    assert provider._keyboard_listener is None
    assert provider._mouse_listener is None


def test_linux_ast_privacy_compliance():
    """AST check asserting Linux provider never retains key identities and calls 'del key'."""
    linux_provider_file = (
        Path(__file__).parent.parent
        / "edc_agent"
        / "platforms"
        / "linux"
        / "provider.py"
    )
    assert linux_provider_file.exists()

    source = linux_provider_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_attributes = {
        "raw_key", "key_name", "key_char", "typed_text", "keystroke_char",
        "char_value", "key_code", "vk", "scan_code"
    }

    has_del_key = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, f"Forbidden attribute {node.attr}"
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assert target.id not in forbidden_attributes
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "key":
                    has_del_key = True

    assert has_del_key, "Linux provider must explicitly contain 'del key' in callbacks"


def test_linux_dynamic_event_scrubbing():
    """Verify events emitted by LinuxInputProvider contain only anonymous categories."""
    emitted: List[ActivityEvent] = []
    provider = LinuxInputProvider(
        callback=emitted.append,
        display_server_checker=lambda: "x11",
    )

    test_keys = [
        KeyCode.from_char("q"),
        Key.space,
        Key.backspace,
        Key.delete,
        Key.ctrl,
        Key.alt,
    ]

    for k in test_keys:
        provider._on_press(k)
        provider._on_release(k)

    assert len(emitted) > 0
    forbidden = ["q", "space", "backspace", "delete", "ctrl", "alt"]

    for ev in emitted:
        assert isinstance(ev.kind, EventKind)
        dump = ev.model_dump()
        for field_val in dump.values():
            if isinstance(field_val, str) and field_val not in {e.value for e in EventKind}:
                for f in forbidden:
                    assert f not in field_val.lower()


# ==============================================================================
# 3. Factory Resolution Tests
# ==============================================================================

def test_get_platform_provider_factory():
    """Verify get_platform_provider resolves the right provider per OS name."""
    cb = lambda ev: None

    p_win = get_platform_provider(callback=cb, platform_name="win32")
    assert isinstance(p_win, WindowsInputProvider)

    p_mac = get_platform_provider(callback=cb, platform_name="darwin")
    assert isinstance(p_mac, MacOSInputProvider)

    p_linux = get_platform_provider(callback=cb, platform_name="linux")
    assert isinstance(p_linux, LinuxInputProvider)

    p_fake = get_platform_provider(callback=cb, platform_name="freebsd")
    assert isinstance(p_fake, FakeInputProvider)
