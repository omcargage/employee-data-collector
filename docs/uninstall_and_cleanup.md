# EDC Desktop Agent Uninstall and Cleanup Guide

This document details how to completely uninstall the Employee Data Collector (EDC) desktop agent, terminate processes, delete persistent OS credentials, and permanently wipe all collected metrics and logs.

---

## 1. Quick Uninstallation Options

### Option A: Using the CLI Uninstaller (Recommended)
The compiled binary or Python module has a built-in uninstaller command:

```powershell
# Interactive mode (prompts for confirmation before wiping)
edc uninstall

# Non-interactive / Automated IT mode
edc uninstall --yes --wipe-data --wipe-credentials
```

### Option B: Using the PowerShell Cleanup Script
An automated uninstallation script is available at `scripts/uninstall_edc.ps1`:

```powershell
# Interactive uninstaller
powershell -ExecutionPolicy Bypass -File scripts/uninstall_edc.ps1

# Non-interactive / Silent cleanup
powershell -ExecutionPolicy Bypass -File scripts/uninstall_edc.ps1 -Force -WipeData -WipeCredentials
```

---

## 2. Complete Manual Cleanup Checklist

For IT administrators or security auditors who wish to verify manual removal step-by-step:

### Step 1: Terminate Active Processes
Ensure no running instances of `edc` or `python` holding locks on `agent.db`:
```powershell
Stop-Process -Name "edc" -Force -ErrorAction SilentlyContinue
```

### Step 2: Remove Auto-Start Registry Key
Remove the user-level auto-start entry from `HKCU`:
```powershell
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "EDC_Agent" -ErrorAction SilentlyContinue
```

### Step 3: Delete API Credentials from Windows Credential Store
The agent stores its per-device API token in the Windows Credential Manager under the service name `edc_agent`:
```powershell
# Via Python keyring
python -c "import keyring; keyring.delete_password('edc_agent', 'device_credential')"

# Or via Windows cmdkey
cmdkey /delete:edc_agent
```

### Step 4: Delete Local Data, SQLite Database, and Logs
All local agent data is stored strictly in the user's home profile at `%USERPROFILE%\.edc`:
- `agent.db`: Local SQLite database containing feature rollups, upload queue, gap log, and consent records.
- `logs/`: Rotating lifecycle log files (`edc_agent.log`, `edc_agent.log.1`, etc.).
- `config.toml`: User-level configuration overrides.

To completely purge all local data:
```powershell
Remove-Item -Path "$env:USERPROFILE\.edc" -Recurse -Force -ErrorAction SilentlyContinue
```

### Step 5: Remove Application Binary
If deployed to `%LOCALAPPDATA%\Programs\EDC`:
```powershell
Remove-Item -Path "$env:LOCALAPPDATA\Programs\EDC" -Recurse -Force -ErrorAction SilentlyContinue
```
