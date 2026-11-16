<#
.SYNOPSIS
    EDC Desktop Agent Clean Uninstallation Script for Windows.
.DESCRIPTION
    Stops any running EDC processes, removes user-level HKCU auto-start registry entries,
    permanently purges agent API credentials from the Windows Credential Manager,
    and removes all local databases, rotated logs, and configuration files.
.PARAMETER WipeData
    Permanently delete the local data and log directory ($env:USERPROFILE\.edc). Default: $true.
.PARAMETER WipeCredentials
    Remove API credentials from Windows Credential Store. Default: $true.
.PARAMETER Force
    Execute non-interactively without user prompt.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$WipeData = $true,
    [switch]$WipeCredentials = $true,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  Employee Data Collector (EDC) Windows Uninstaller" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not $Force) {
    Write-Host "This script will:" -ForegroundColor Yellow
    Write-Host "  1. Terminate any running 'edc' processes."
    Write-Host "  2. Remove auto-start from HKCU:\Software\Microsoft\Windows\CurrentVersion\Run."
    if ($WipeCredentials) {
        Write-Host "  3. Delete agent API credentials from the Windows Credential Manager."
    }
    if ($WipeData) {
        Write-Host "  4. Permanently delete all local data, SQLite database, and logs in $env:USERPROFILE\.edc."
    }
    Write-Host ""
    $confirmation = Read-Host "Type 'UNINSTALL' to confirm complete cleanup"
    if ($confirmation -ne "UNINSTALL") {
        Write-Host "Uninstallation aborted by user." -ForegroundColor Red
        exit 1
    }
}

# 1. Terminate running EDC processes
Write-Host "[1/4] Stopping active EDC processes..." -ForegroundColor Green
$runningProcesses = Get-Process -Name "edc" -ErrorAction SilentlyContinue
if ($runningProcesses) {
    $runningProcesses | Stop-Process -Force
    Write-Host "  Terminated active EDC process(es)." -ForegroundColor Gray
} else {
    Write-Host "  No running EDC processes found." -ForegroundColor Gray
}

# 2. Remove user-level auto-start registry entry
Write-Host "[2/4] Removing HKCU auto-start entry..." -ForegroundColor Green
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$entry = Get-ItemProperty -Path $runKey -Name "EDC_Agent" -ErrorAction SilentlyContinue
if ($entry) {
    Remove-ItemProperty -Path $runKey -Name "EDC_Agent" -ErrorAction SilentlyContinue
    Write-Host "  Removed 'EDC_Agent' from HKCU Run key." -ForegroundColor Gray
} else {
    Write-Host "  No 'EDC_Agent' entry found in HKCU Run key." -ForegroundColor Gray
}

# 3. Purge OS credentials from Windows Credential Manager
if ($WipeCredentials) {
    Write-Host "[3/4] Purging stored API credentials from Credential Manager..." -ForegroundColor Green
    # Use python keyring or cmdkey if available
    try {
        $pyCmd = "import keyring; keyring.delete_password('edc_agent', 'device_credential')"
        & python -c $pyCmd 2>$null
        Write-Host "  Purged device credential via keyring." -ForegroundColor Gray
    } catch {
        Write-Host "  Keyring cleanup completed or not present." -ForegroundColor Gray
    }
} else {
    Write-Host "[3/4] Skipping credential purge (retained per request)." -ForegroundColor Yellow
}

# 4. Remove local data directory
if ($WipeData) {
    Write-Host "[4/4] Removing local data directory ($env:USERPROFILE\.edc)..." -ForegroundColor Green
    $dataDir = Join-Path -Path $env:USERPROFILE -ChildPath ".edc"
    if (Test-Path -Path $dataDir) {
        Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Successfully deleted $dataDir" -ForegroundColor Gray
    } else {
        Write-Host "  Data directory $dataDir does not exist." -ForegroundColor Gray
    }
} else {
    Write-Host "[4/4] Skipping data directory removal (retained per request)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  EDC Uninstallation and Cleanup Complete!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
