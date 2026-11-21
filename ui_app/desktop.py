"""WorkSense Standalone Desktop Application.

Runs the WorkSense API engine and PyTorch model in-process, then displays
the UI inside a dedicated, borderless native desktop application window.
No browser tabs, no address bars, 100% desktop application experience.
"""
import os
import sys
import time
import json
import socket
import threading
import subprocess
import webbrowser
import urllib.request
from pathlib import Path
from typing import Optional

# Ensure all packages are discoverable
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
for p in [PROJECT_ROOT / "agent", PROJECT_ROOT / "shared", PROJECT_ROOT / "backend", BASE_DIR]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

SERVER_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Dedicated profile directory for WorkSense so Chromium runs as an isolated desktop app
# and never clashes with active everyday Chrome/Edge sessions.
APP_PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WorkSense" / "desktop_profile"


def find_browser_app_binary() -> Optional[str]:
    """Find installed Chrome, Edge, or Chromium executable for dedicated App Mode."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def is_worksense_healthy(port: int, timeout: float = 1.0) -> bool:
    """Check if the WorkSense API is actively running and responding with HTTP 200."""
    try:
        url = f"http://{SERVER_HOST}:{port}/api/health"
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(url, headers={"User-Agent": "WorkSense-Desktop-Launcher"})
        with opener.open(req, timeout=timeout) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("status") == "healthy"
    except Exception:
        pass
    return False


def find_available_port(start_port: int = 8000, max_attempts: int = 50) -> int:
    """Find the first available TCP port on 127.0.0.1 starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((SERVER_HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Could not bind to any port in range {start_port}-{start_port + max_attempts}")


def get_active_worksense_port() -> Optional[int]:
    """Detect if a WorkSense server instance is already running on ports 8000-8010."""
    for port in range(8000, 8011):
        if is_worksense_healthy(port, timeout=0.3):
            return port
    return None


def main():
    print("=" * 66)
    print("   WorkSense - Early-Warning Burnout Prevention")
    print("   FLAME University Research Prototype | Desktop Application")
    print("=" * 66)
    print()

    server = None
    server_thread = None
    started_server = False

    # Step 1: Check if WorkSense is already active on a local port
    active_port = get_active_worksense_port()
    if active_port:
        print(f"[1/3] WorkSense engine is already running on port {active_port}.", flush=True)
    else:
        active_port = find_available_port(DEFAULT_PORT)
        print(f"[1/3] Loading neural network, baseline models & master dataset...", flush=True)
        t0 = time.time()

        import uvicorn
        from server import app, load_application_state

        load_application_state()
        print(f"      Engine initialized successfully in {time.time() - t0:.1f}s.")

        # Step 2: Start Uvicorn in daemon thread with verified readiness
        print(f"[2/3] Starting local WorkSense server on port {active_port}...", flush=True)
        config = uvicorn.Config(
            app=app,
            host=SERVER_HOST,
            port=active_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        started_server = True

        # Robust wait loop: poll health endpoint up to 35 seconds
        server_ready = False
        for _ in range(175):
            time.sleep(0.2)
            if not server_thread.is_alive():
                print("\n[ERROR] Server thread terminated unexpectedly during startup.")
                sys.exit(1)
            if is_worksense_healthy(active_port, timeout=0.5):
                server_ready = True
                break

        if not server_ready:
            print(f"\n[ERROR] WorkSense server failed to respond on http://{SERVER_HOST}:{active_port}/api/health.")
            print("Please ensure no firewall or security tool is blocking 127.0.0.1.")
            sys.exit(1)

        print(f"      Server is verified ready and connected to ML pipeline.")

    # Target URL for the application
    target_url = f"http://{SERVER_HOST}:{active_port}"

    # Step 3: Launch standalone window
    print(f"[3/3] Opening WorkSense Desktop Application window...", flush=True)
    browser_exe = find_browser_app_binary()

    window_proc = None
    if browser_exe:
        APP_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        browser_name = Path(browser_exe).stem.title()
        print(f"      Launching native window container ({browser_name} App Mode)...")
        cmd = [
            browser_exe,
            f"--app={target_url}",
            f"--user-data-dir={APP_PROFILE_DIR}",
            "--window-size=1360,880",
            "--app-auto-launched",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
        ]
        window_proc = subprocess.Popen(cmd)
    else:
        # Fallback to pywebview if installed, or system browser
        try:
            import webview
            print("      Launching native pywebview window...")
            icon_path = str(BASE_DIR / "static" / "worksense.ico")
            webview_kwargs = {
                "title": "WorkSense — Early-Warning Burnout Prevention",
                "url": target_url,
                "width": 1340,
                "height": 880,
                "min_size": (1024, 700),
                "resizable": True,
                "text_select": True,
            }
            if os.path.exists(icon_path):
                webview_kwargs["icon"] = icon_path
            webview.create_window(**webview_kwargs)
            webview.start()
            if started_server and server:
                server.should_exit = True
            return
        except Exception:
            print("      Opening in default browser container...")
            webbrowser.open(target_url)

    # If this invocation didn't start the server, its only job was to launch/focus the window
    if not started_server:
        print()
        print("=" * 66)
        print("  WorkSense window brought to focus.")
        print(f"  Active server URL: {target_url}")
        print("=" * 66)
        print()
        time.sleep(1)
        return

    print()
    print("=" * 66)
    print("  WorkSense is running!")
    print(f"  URL: {target_url}")
    print("  Close the application window or press CTRL+C to exit.")
    print("=" * 66)
    print()

    # Step 4: Keep script alive and monitor the application lifecycle
    try:
        if window_proc:
            window_proc.wait()
            print("WorkSense application window closed by user.")
        elif server_thread:
            while True:
                time.sleep(1)
        else:
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopping WorkSense...")
    finally:
        if window_proc and window_proc.poll() is None:
            try:
                window_proc.terminate()
            except Exception:
                pass
        if started_server and server:
            print("Shutting down local WorkSense server...")
            server.should_exit = True
            if server_thread and server_thread.is_alive():
                server_thread.join(timeout=3.0)
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
