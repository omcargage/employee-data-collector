"""Tests for user-level auto-start (HKCU Run) and uninstallation routines."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from edc_agent.autostart import (
    disable_autostart,
    enable_autostart,
    get_autostart_entry,
    get_default_command,
    is_autostart_enabled,
    is_autostart_supported,
)
from edc_agent.client.keyring_store import (
    delete_credential,
    enable_memory_keyring,
    get_credential,
    store_credential,
)
from edc_agent.main import cmd_autostart, cmd_uninstall


@pytest.fixture(autouse=True)
def setup_memory_keyring():
    enable_memory_keyring(True)
    delete_credential()
    yield
    delete_credential()
    enable_memory_keyring(False)


def test_autostart_command_generation():
    """Verify default startup command includes entrypoint and run subcommand."""
    cmd = get_default_command(args="run")
    assert "edc_agent.main" in cmd or "edc" in cmd
    assert "run" in cmd


def test_autostart_enable_and_disable_mocked():
    """Mock winreg to test enabling, checking, and disabling auto-start."""
    registry_store = {}

    class MockKey:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_open_key(hkey, subkey, reserved, access):
        return MockKey()

    def mock_set_value(key, value_name, reserved, val_type, value):
        registry_store[value_name] = value

    def mock_query_value(key, value_name):
        if value_name in registry_store:
            return registry_store[value_name], 1
        raise FileNotFoundError(f"Key not found: {value_name}")

    def mock_delete_value(key, value_name):
        if value_name in registry_store:
            del registry_store[value_name]
        else:
            raise FileNotFoundError(f"Key not found: {value_name}")

    with patch("sys.platform", "win32"), \
         patch("winreg.OpenKey", side_effect=mock_open_key), \
         patch("winreg.SetValueEx", side_effect=mock_set_value), \
         patch("winreg.QueryValueEx", side_effect=mock_query_value), \
         patch("winreg.DeleteValue", side_effect=mock_delete_value):

        assert is_autostart_supported() is True
        assert is_autostart_enabled() is False

        # Enable
        ok, cmd = enable_autostart(command='C:\\EDC\\edc.exe run')
        assert ok is True
        assert cmd == 'C:\\EDC\\edc.exe run'
        assert is_autostart_enabled() is True
        assert get_autostart_entry() == 'C:\\EDC\\edc.exe run'

        # Disable
        ok_dis, _ = disable_autostart()
        assert ok_dis is True
        assert is_autostart_enabled() is False
        assert get_autostart_entry() is None


def test_cmd_autostart_cli(monkeypatch):
    """Test cmd_autostart dispatch."""
    monkeypatch.setattr("edc_agent.main.is_autostart_supported", lambda: True)
    monkeypatch.setattr("edc_agent.main.is_autostart_enabled", lambda: True)
    monkeypatch.setattr("edc_agent.main.get_autostart_entry", lambda: "edc.exe run")
    monkeypatch.setattr("edc_agent.main.enable_autostart", lambda args: (True, "edc.exe run"))
    monkeypatch.setattr("edc_agent.main.disable_autostart", lambda: (True, "Disabled"))

    assert cmd_autostart(action="status") == 0
    assert cmd_autostart(action="enable") == 0
    assert cmd_autostart(action="disable") == 0


def test_cmd_uninstall_full_cleanup(tmp_path, monkeypatch):
    """Verify cmd_uninstall wipes registry, stored credentials, and local data directory."""
    test_db_dir = tmp_path / ".edc"
    test_db_dir.mkdir()
    (test_db_dir / "agent.db").write_text("dummy db data")
    (test_db_dir / "logs").mkdir()
    (test_db_dir / "logs" / "edc.log").write_text("dummy log")

    store_credential("secret-key-12345")
    assert get_credential() == "secret-key-12345"

    autostart_disabled = False

    def mock_disable_autostart():
        nonlocal autostart_disabled
        autostart_disabled = True
        return True, "Disabled"

    monkeypatch.setattr("edc_agent.main.is_autostart_supported", lambda: True)
    monkeypatch.setattr("edc_agent.main.disable_autostart", mock_disable_autostart)

    rc = cmd_uninstall(
        wipe_data=True,
        wipe_credentials=True,
        confirmed=True,
        db_path=str(test_db_dir / "agent.db"),
    )

    assert rc == 0
    assert autostart_disabled is True
    assert get_credential() is None
    assert not test_db_dir.exists()
