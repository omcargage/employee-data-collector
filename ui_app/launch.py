"""WorkSense Desktop Launcher.

Starts the FastAPI backend as a subprocess, waits for it to be ready,
then opens the app in a native Windows desktop window (pywebview / Edge WebView2).
No browser, no address bar — looks and feels like a real desktop app.
"""
import sys
import time
import subprocess
import socket
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
THIS_DIR  = Path(__file__).resolve().parent          # ui_app/
ROOT      = THIS_DIR.parent                          # employee-data-collector/
PYTHON    = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"

HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"


def _wait_for_server(timeout: int = 40) -> bool:
    """Poll until the server accepts TCP connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    # 1. Start FastAPI backend as a subprocess (most reliable cross-platform)
    print("WorkSense: starting backend…", flush=True)
    server_proc = subprocess.Popen(
        [
            str(PYTHON), "-m", "uvicorn",
            "server:app",
            "--host", HOST,
            "--port", str(PORT),
            "--log-level", "warning",
        ],
        cwd=str(THIS_DIR),   # server.py is in ui_app/
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 2. Wait until it accepts connections
    if not _wait_for_server(40):
        server_proc.terminate()
        print("ERROR: backend did not start within 40 s", file=sys.stderr)
        sys.exit(1)

    print(f"WorkSense: backend ready at {URL}", flush=True)

    # 3. Open native desktop window via pywebview
    try:
        import webview  # pywebview

        window = webview.create_window(
            title="WorkSense — Early-Warning Burnout Prevention",
            url=URL,
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            text_select=False,
            on_top=False,
            background_color="#ffffff",
        )
        # start() blocks until the window is closed — then we clean up
        webview.start(debug=False)

    except ImportError:
        # Graceful fallback: Chrome app-mode
        print("pywebview not found — falling back to Chrome app-mode", flush=True)
        import webbrowser

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        launched = False
        for cp in chrome_paths:
            if Path(cp).exists():
                subprocess.Popen([cp, f"--app={URL}", "--window-size=1280,820"])
                launched = True
                break
        if not launched:
            webbrowser.open(URL)

        print("Press CTRL+C to stop WorkSense.", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    finally:
        # Shut down the backend when window closes
        print("WorkSense: shutting down backend…", flush=True)
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()


if __name__ == "__main__":
    main()
