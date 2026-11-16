"""User-level auto-start management for Windows (HKCU Run registry).

Enables or disables auto-starting the EDC desktop agent on user login without
requiring Administrator / UAC privileges.
"""
import logging
import os
import sys
from typing import Optional, Tuple

logger = logging.getLogger("edc_agent.autostart")

REG_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "EDC_Agent"


def is_autostart_supported() -> bool:
    """Return True if auto-start management is supported on this platform."""
    return sys.platform == "win32"


def get_default_command(args: str = "run") -> str:
    """Determine the command string to execute on startup."""
    if getattr(sys, "frozen", False):
        # Running as a compiled PyInstaller standalone executable
        exe_path = sys.executable
        return f'"{exe_path}" {args}'
    else:
        # Running as a Python module/script
        py_exe = sys.executable
        return f'"{py_exe}" -m edc_agent.main {args}'


def is_autostart_enabled() -> bool:
    """Check if the user-level auto-start registry key exists."""
    if not is_autostart_supported():
        return False

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_RUN_KEY_PATH,
            0,
            winreg.KEY_READ,
        ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("Failed to query HKCU auto-start key: %s", exc)
        return False


def get_autostart_entry() -> Optional[str]:
    """Retrieve the current command string configured in HKCU Run registry, if any."""
    if not is_autostart_supported():
        return None

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_RUN_KEY_PATH,
            0,
            winreg.KEY_READ,
        ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return str(val)
    except Exception:
        return None


def enable_autostart(
    command: Optional[str] = None,
    args: str = "run",
) -> Tuple[bool, str]:
    """Register the agent to start automatically on user login via HKCU.

    Args:
        command: Optional full command string. If None, auto-generated based on runtime.
        args: Subcommand/arguments to pass (default: "run").

    Returns:
        Tuple of (success: bool, command_string: str).
    """
    if not is_autostart_supported():
        return False, "Auto-start via HKCU is only supported on Windows"

    import winreg

    cmd_to_set = command or get_default_command(args=args)

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                REG_APP_NAME,
                0,
                winreg.REG_SZ,
                cmd_to_set,
            )
        logger.info("Auto-start successfully registered in HKCU: %s", cmd_to_set)
        return True, cmd_to_set
    except Exception as exc:
        err = f"Failed to set HKCU auto-start registry value: {exc}"
        logger.error(err)
        return False, err


def disable_autostart() -> Tuple[bool, str]:
    """Remove the agent from HKCU auto-start.

    Returns:
        Tuple of (success: bool, message: str).
    """
    if not is_autostart_supported():
        return False, "Auto-start via HKCU is only supported on Windows"

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, REG_APP_NAME)
        logger.info("Auto-start successfully removed from HKCU")
        return True, "Auto-start disabled"
    except FileNotFoundError:
        return True, "Auto-start was not registered"
    except Exception as exc:
        err = f"Failed to delete HKCU auto-start registry value: {exc}"
        logger.error(err)
        return False, err
