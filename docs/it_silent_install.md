# Enterprise IT Silent Installation & Provisioning Notes

This guide provides systems administrators and IT operations teams with instructions for automated, silent deployment of the Employee Data Collector (EDC) desktop agent via Microsoft Intune, SCCM/MECM, Group Policy (GPO), or automated PowerShell scripts.

---

## 1. Architectural Overview & Privilege Model

- **No Administrator / UAC Required**: The EDC agent runs strictly in user mode. It requires **no local administrator rights** or UAC elevation.
- **Recommended Install Location**: `%LOCALAPPDATA%\Programs\EDC\` (e.g. `C:\Users\<username>\AppData\Local\Programs\EDC\`).
- **Data & Log Directory**: `%USERPROFILE%\.edc\` (e.g. `C:\Users\<username>\.edc\`).
- **Credential Storage**: Windows Credential Manager (`HKCU\Software\Microsoft\Windows\CurrentVersion\Vault` via `keyring`).
- **Startup Registration**: User-level `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

---

## 2. Silent Deployment Script (PowerShell / Intune)

Save the following deployment script as `deploy_edc_agent.ps1` for execution in the user context:

```powershell
<#
.SYNOPSIS
    Silent, zero-prompt deployment of the EDC Desktop Agent.
.PARAMETER ServerUrl
    Base URL of the EDC ingestion backend (e.g. https://edc.internal.corp).
.PARAMETER EnrollmentToken
    One-time provisioning token issued for this employee/device.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ServerUrl,

    [Parameter(Mandatory=$true)]
    [string]$EnrollmentToken,

    [string]$SourceBinaryPath = "\\deploy-share\edc\edc.exe"
)

$ErrorActionPreference = "Stop"

# 1. Target installation directory (User Context)
$installDir = Join-Path -Path $env:LOCALAPPDATA -ChildPath "Programs\EDC"
if (-not (Test-Path -Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}

$targetExe = Join-Path -Path $installDir -ChildPath "edc.exe"

# 2. Copy compiled binary from network share or package
Copy-Item -Path $SourceBinaryPath -Destination $targetExe -Force

# 3. Perform silent device enrollment with one-time token
# Exchanging token for per-device credential and storing in Windows Credential Store
& $targetExe enroll $EnrollmentToken --server $ServerUrl
if ($LASTEXITCODE -ne 0) {
    Write-Error "EDC Enrollment failed with exit code $LASTEXITCODE"
}

# 4. Enable user-level auto-start in HKCU Run
& $targetExe autostart --enable
if ($LASTEXITCODE -ne 0) {
    Write-Error "EDC Auto-start configuration failed with exit code $LASTEXITCODE"
}

# 5. Launch agent in background (or will start automatically on next login)
Start-Process -FilePath $targetExe -ArgumentList "run" -WindowStyle Hidden

Write-Output "EDC Agent deployed and enrolled successfully for $env:USERNAME."
```

---

## 3. Network & Firewall Egress Requirements

The EDC agent strictly communicates outbound over standard HTTPS. No incoming ports or inbound listener firewall exceptions are required.

| Protocol | Destination Host | Port | Direction | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **HTTPS (TLS 1.3)** | `edc.internal.corp` | `443` (or `8000`) | Outbound | Device enrollment (`/devices/enroll`), heartbeats (`/devices/heartbeat`), and batch metric ingestion (`/metrics/batch`). |

### Proxy Support
The agent utilizes standard HTTP/HTTPS proxy configuration from environment variables:
- `HTTP_PROXY`: `http://proxy.corp:8080`
- `HTTPS_PROXY`: `http://proxy.corp:8080`
- `NO_PROXY`: `localhost,127.0.0.1,.corp`

---

## 4. Microsoft Intune Packaging (Win32 App / IntuneWin)

1. **Package using IntuneWinAppUtil**:
   ```cmd
   IntuneWinAppUtil.exe -c "C:\Packaging\EDC" -s "deploy_edc_agent.ps1" -o "C:\Packaging\Output"
   ```
2. **Intune Configuration**:
   - **Install Command**: `powershell.exe -ExecutionPolicy Bypass -File deploy_edc_agent.ps1 -ServerUrl "https://edc.corp" -EnrollmentToken "%ENROLL_TOKEN%"`
   - **Uninstall Command**: `powershell.exe -ExecutionPolicy Bypass -Command "edc uninstall --yes --wipe-data --wipe-credentials"`
   - **Install Behavior**: **User** (Do NOT select "System").
   - **Detection Rule**: File exists at `%LOCALAPPDATA%\Programs\EDC\edc.exe`.
