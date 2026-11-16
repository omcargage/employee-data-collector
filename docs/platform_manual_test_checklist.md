# Platform Adapters Manual Test Checklist

This checklist provides step-by-step instructions for manually verifying the Employee Data Collector (EDC) input providers across **macOS**, **Linux**, and **Windows**.

---

## 1. macOS Manual Test Checklist

macOS Catalina (10.15) and newer enforce **Input Monitoring (`kTCCServiceListenEvent`)** permissions to protect user privacy. Background apps cannot observe global keyboard or mouse events without explicit user authorization in System Settings.

### Pre-Requisites
- macOS 10.15 (Catalina) or later (Monterey, Ventura, Sonoma, Sequoia).
- Python 3.12+ installed.
- Terminal, iTerm2, or VS Code.

### Test 1.1: Missing Input Monitoring Permission (Expected Refusal & Explanation)
1. Open **System Settings** &rarr; **Privacy & Security** &rarr; **Input Monitoring**.
2. If Terminal / iTerm2 / Python is listed, toggle it **OFF** or remove it (`-`).
3. Launch the agent in your terminal:
   ```bash
   python -m edc_agent.main run
   ```
4. **Expected Behavior**:
   - The agent detects missing Input Monitoring permission.
   - It outputs an explanation:
     ```
     Cannot start macOS input listeners: Input Monitoring permission missing.
     macOS (Catalina 10.15+) restricts global keystroke and mouse event capture...
     To grant Input Monitoring permission:
       1. Open System Settings -> Privacy & Security -> Input Monitoring.
       2. Toggle ON the switch next to Terminal / iTerm2 / EDC.
       3. Quit & Reopen.
     ```
   - No input listener threads crash.
   - Capabilities query returns `{"supported": false, "input_monitoring_granted": false}`.

### Test 1.2: Granting Permission and Verifying Collection
1. Open **System Settings** &rarr; **Privacy & Security** &rarr; **Input Monitoring**.
2. Toggle **ON** the switch for Terminal / iTerm2 / VS Code.
3. Completely quit and restart your terminal application (required by macOS TCC).
4. Launch the agent again:
   ```bash
   python -m edc_agent.main run
   ```
5. Type test text and move the mouse in another application (e.g., Safari or TextEdit).
6. **Expected Behavior**:
   - The live status line updates active keystroke and mouse movement counts.
   - Check the local database after window closure (`python -m edc_agent.main status`):
     - Keystrokes and mouse movements are counted.
     - Coverage ratio reflects active time.
     - **Privacy verification**: Verify SQLite `rollups_15min` contains only aggregated numerical features; zero raw characters or titles are stored.

### Test 1.3: Revoking Permission Mid-Flight
1. While the agent is running, toggle Input Monitoring **OFF** in System Settings.
2. Observe terminal behavior:
   - macOS TCC will notify the app or terminate the process safely without data corruption.

---

## 2. Linux Manual Test Checklist

Linux desktops run either the traditional **X11 (Xorg)** display server or the modern **Wayland** compositor. Wayland by design prevents unprivileged background applications from snooping on keystrokes and mouse events from other windows.

### Pre-Requisites
- Linux distribution (e.g., Ubuntu 22.04/24.04, Fedora 38+, Debian 12, or Arch Linux).
- Python 3.12+ installed.

### Test 2.1: Wayland Session Detection (Expected Capability Unavailability)
1. Verify you are running under a Wayland session:
   ```bash
   echo $XDG_SESSION_TYPE
   # Expected output: wayland
   ```
2. Launch the agent:
   ```bash
   python -m edc_agent.main run
   ```
3. **Expected Behavior**:
   - The agent detects Wayland (`wayland_detected: True`).
   - It reports capabilities as unavailable (`supported: False`):
     ```
     Cannot start Linux input listeners: Wayland display server detected.
     The Wayland protocol enforces strict client-to-client security isolation.
     To enable activity metric collection on Linux:
       1. Log out of your current desktop session.
       2. At the login screen, select 'Ubuntu on Xorg' or 'GNOME on X11'.
       3. Log in and re-launch EDC.
     ```
   - The agent does NOT attempt to attach broken pynput listeners, avoiding X11 bad window / crash loops.

### Test 2.2: X11 Session Execution
1. Log out of your desktop session.
2. At the GDM / LightDM / SDDM login screen:
   - Click on your user account.
   - Click the gear/cog icon in the bottom-right or top-right.
   - Select **"Ubuntu on Xorg"** (or **"GNOME on Xorg"** / **"X11"**).
   - Enter your password and log in.
3. Verify session type:
   ```bash
   echo $XDG_SESSION_TYPE
   # Expected output: x11
   ```
4. Launch the agent:
   ```bash
   python -m edc_agent.main run
   ```
5. **Expected Behavior**:
   - Provider detects X11 (`wayland_detected: False`, `supported: True`).
   - Capabilities report `mouse_move=True`, `mouse_click=True`, `mouse_scroll=True`.
   - Peripheral events are accurately captured and binned.

---

## 3. Windows Manual Test Checklist

Windows uses low-level Win32 hooks (`WH_KEYBOARD_LL` and `WH_MOUSE_LL`).

### Pre-Requisites
- Windows 10 or Windows 11.
- PowerShell 7 or Windows PowerShell 5.1.

### Test 3.1: Standard Collection
1. Open PowerShell and run:
   ```powershell
   & ".venv\Scripts\python.exe" -m edc_agent.main run --auto-consent
   ```
2. Switch to a browser or text editor, type a paragraph, and move the mouse.
3. **Expected Behavior**:
   - The status line increments keystroke and movement counts.
   - Press `Ctrl+C` to stop gracefully.

### Test 3.2: Privacy Verification
1. Inspect the generated SQLite database:
   ```powershell
   & ".venv\Scripts\python.exe" -c "from edc_agent.storage.database import Database; db = Database('~/.edc/agent.db'); print(db.get_rollups_15min_count())"
   ```
2. Verify log files (`~/.edc/logs/edc_agent.log`):
   - Confirm only lifecycle messages exist.
   - Confirm zero raw keys, typed words, or active window titles appear in logs.
