# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for building the EDC desktop agent executable on Windows."""
import os
import sys
from pathlib import Path

# Resolve base directories
SPEC_DIR = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_DIR.parent.parent
AGENT_DIR = REPO_ROOT / "agent"
SHARED_DIR = REPO_ROOT / "shared"

block_cipher = None

# Collect all non-Python data assets needed at runtime
datas = [
    (str(AGENT_DIR / "edc_agent" / "default_config.toml"), "edc_agent"),
]

# Ensure required libraries and dynamic platform hooks are included
hiddenimports = [
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "keyring.backends.null",
    "tzdata",
    "zoneinfo",
    "httpx",
    "edc_schemas",
    "ctypes",
    "ctypes.wintypes",
    "winreg",
    "sqlite3",
]

a = Analysis(
    [str(AGENT_DIR / "edc_agent" / "main.py")],
    pathex=[str(AGENT_DIR), str(SHARED_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="edc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
    icon=None,
)
