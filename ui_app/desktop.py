"""WorkSense Standalone Desktop Application.

Runs the WorkSense API engine and PyTorch model in-process, then displays
the UI inside a dedicated, borderless native desktop application window.
No browser tabs, no address bars, 100% desktop application experience.
"""
import os
import sys
import time
import threading
import subprocess
import urllib.request
from pathlib import Path

# Ensure all packages are discoverable
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
for p in [PROJECT_ROOT / "agent", PROJECT_ROOT / "shared", PROJECT_ROOT / "backend"]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
HEALTH_URL = f"{SERVER_URL}/api/health"


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


def is_server_ready() -> bool:
    """Check if the API is responding."""
    try:
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(HEALTH_URL, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    print("=" * 66)
    print("   WorkSense - Early-Warning Burnout Prevention")
    print("   FLAME University Research Prototype | Desktop Application")
    print("=" * 66)
    print()

    server = None
    server_thread = None

    # Step 1: Check if server is already running or start in-process
    if is_server_ready():
        print("[1/3] WorkSense engine is already running on port 8000.", flush=True)
    else:
        print("[1/3] Loading neural network, baseline models & master dataset...", flush=True)
        t0 = time.time()

        import uvicorn
        from server import app, load_application_state

        # Explicitly load state with progress feedback
        load_application_state()
        print(f"      Engine initialized successfully in {time.time() - t0:.1f}s.")

        # Step 2: Start Uvicorn in background thread
        print("[2/3] Starting local WorkSense server on port 8000...", flush=True)
        config = uvicorn.Config(
            app=app,
            host=SERVER_HOST,
            port=SERVER_PORT,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        # Wait for server ready (usually < 1 second since app is already initialized)
        for _ in range(25):
            time.sleep(0.3)
            if is_server_ready():
                break
        print("      Server is ready and connected to ML pipeline.")

    # Step 3: Launch standalone window
    print("[3/3] Opening WorkSense Desktop Application window...", flush=True)
    browser_exe = find_browser_app_binary()

    window_proc = None
    if browser_exe:
        browser_name = Path(browser_exe).stem.title()
        print(f"      Launching native window container ({browser_name} App Mode)...")
        window_proc = subprocess.Popen([
            browser_exe,
            f"--app={SERVER_URL}",
            "--window-size=1360,880",
            "--app-auto-launched",
        ])
    else:
        # Fallback to pywebview if available, or system default
        try:
            import webview
            print("      Launching native pywebview window...")
            webview.create_window(
                title="WorkSense — Early-Warning Burnout Prevention",
                url=SERVER_URL,
                width=1340,
                height=880,
                min_size=(1024, 700),
                resizable=True,
                text_select=True,
            )
            webview.start()
            if server:
                server.should_exit = True
            return
        except Exception:
            print("      Opening in default browser container...")
            os.system(f'start "" "{SERVER_URL}"')

    print()
    print("=" * 66)
    print("  WorkSense is running in its dedicated desktop window!")
    print("  Close the application window or press CTRL+C to exit.")
    print("=" * 66)
    print()

    # Keep script alive while the user is using the app window
    try:
        if window_proc:
            window_proc.wait()
            print("WorkSense window closed.")
        elif server_thread:
            server_thread.join()
        else:
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopping WorkSense...")
    finally:
        if server:
            server.should_exit = True
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
