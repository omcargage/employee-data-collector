"""WorkSense Standalone Desktop Application Launcher.

Runs the WorkSense FastAPI backend and displays the UI inside a
dedicated, borderless native desktop application window.
No browser tabs, no address bars, 100% desktop application experience.
"""
import os
import sys
import time
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
AGENT_DIR = BASE_DIR.parent / "agent"
VENV_PYTHON = AGENT_DIR / ".venv" / "Scripts" / "python.exe"

SERVER_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{SERVER_URL}/api/health"


def is_server_running() -> bool:
    """Check if the WorkSense server is already responding."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_server(timeout_sec: int = 25) -> bool:
    """Poll until the backend server is ready."""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if is_server_running():
            return True
        time.sleep(0.5)
    return False


def find_browser_app_binary():
    """Find installed Chrome or Edge executable for App Mode."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def run_standalone_app(prefer_native: bool = True):
    """Launch the app in a standalone window."""
    # 1. Try pywebview for genuine native Windows frame
    if prefer_native:
        try:
            import webview
            window = webview.create_window(
                title="WorkSense — Early-Warning Burnout Prevention",
                url=SERVER_URL,
                width=1340,
                height=880,
                min_size=(1024, 700),
                resizable=True,
                text_select=True,
                confirm_close=False,
            )
            webview.start()
            return
        except Exception as e:
            print(f"[Notice] Native webview: {e}. Launching standalone App Mode...")

    # 2. Chrome / Edge dedicated App Mode (--app=URL)
    browser_exe = find_browser_app_binary()
    if browser_exe:
        subprocess.Popen([browser_exe, f"--app={SERVER_URL}", "--window-size=1340,880"])
        return

    # 3. Fallback to default handler
    os.system(f'start "" "{SERVER_URL}"')


def main():
    print("=" * 60)
    print("  WorkSense — Early-Warning Burnout Prevention")
    print("  Desktop Application Launcher")
    print("=" * 60)

    # 1. Start server if not already running
    server_process = None
    if not is_server_running():
        print("[1/2] Starting backend engine & neural network...")
        py_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        server_process = subprocess.Popen(
            [py_exe, "-m", "uvicorn", "server:app", "--app-dir", str(BASE_DIR), "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
            cwd=str(BASE_DIR),
        )
        print("      Waiting for server initialization...")
        if not wait_for_server(timeout_sec=25):
            print("[ERROR] Server failed to start within timeout.")
            if server_process:
                server_process.terminate()
            sys.exit(1)
        print("      Backend ready.")
    else:
        print("[1/2] Backend engine is active on port 8000.")

    # 2. Launch dedicated desktop window
    print("[2/2] Launching WorkSense Desktop App window...")
    # Prefer Chrome App Mode for ultra-fast GPU acceleration and crisp Segoe UI rendering
    browser_exe = find_browser_app_binary()
    if browser_exe:
        print(f"      Launching standalone app container ({Path(browser_exe).stem})...")
        subprocess.Popen([browser_exe, f"--app={SERVER_URL}", "--window-size=1360,880"])
    else:
        run_standalone_app(prefer_native=True)

    print("\n  WorkSense is running in its own standalone window.")
    print("  Close the application window or press CTRL+C to exit.\n")


if __name__ == "__main__":
    main()
