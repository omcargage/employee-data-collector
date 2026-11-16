# Windows Packaging and Auto-Start Guide

This document describes how to compile the Employee Data Collector (EDC) desktop agent into a standalone Windows executable (`edc.exe`) and configure user-level auto-start without requiring Administrator / UAC privileges.

---

## 1. PyInstaller Build Script

The agent is compiled using PyInstaller into a single-file executable containing Python runtime, all dependencies (`pynput`, `keyring`, `httpx`, `pydantic`), and the shared schema contracts.

### Build Pre-Requisites
- Windows 10 or 11 (x64).
- Python 3.12 installed in `agent/.venv`.
- PyInstaller 6.0+ installed (`pip install pyinstaller`).

### Automated Compilation
From the repository root:
```powershell
Set-Location "d:\FLAME_UG\UG4\IMP_Data\employee-data-collector"
& "agent\.venv\Scripts\python.exe" scripts/build_windows_exe.py
```

### Build Artifacts
- **Executable**: `dist/edc.exe` (~15-25 MB standalone binary).
- **Spec File**: `packaging/windows/edc.spec` defines all data files (`default_config.toml`), hidden imports (`keyring.backends.Windows`, `tzdata`, `ctypes.wintypes`), and build exclusions.
- **Verification**: The build script automatically executes `edc.exe --help` after compiling to confirm runtime initialization.

---

## 2. User-Level Auto-Start Architecture

Enterprise deployment and privacy considerations require that the collector can start automatically upon user login **without requiring local administrator rights or UAC prompts**.

### Registry Key
The agent registers in the current user's personal Run key:
- **Registry Hive**: `HKEY_CURRENT_USER` (HKCU)
- **Path**: `Software\Microsoft\Windows\CurrentVersion\Run`
- **Value Name**: `EDC_Agent`
- **Value Type**: `REG_SZ`
- **Value Data**: `"C:\Users\<Username>\AppData\Local\Programs\EDC\edc.exe" run`

Because this key is inside `HKEY_CURRENT_USER`, any standard enterprise user account can read, write, and delete this key without administrative elevation.

### Managing Auto-Start via CLI
The `edc` binary includes built-in commands to inspect and toggle auto-start:

1. **Check Auto-Start Status**:
   ```powershell
   edc autostart --status
   ```
2. **Enable Auto-Start**:
   ```powershell
   edc autostart --enable
   ```
3. **Disable Auto-Start**:
   ```powershell
   edc autostart --disable
   ```
