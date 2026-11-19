"""WorkSense Standalone Desktop Application Launcher.

Runs the WorkSense FastAPI backend and displays the UI inside a
dedicated, borderless native desktop application window.
No browser tabs, no address bars, 100% desktop application experience.
"""
import os
import sys
import time
import socket
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
AGENT_DIR = PROJECT_ROOT / "agent"
VENV_PYTHON = AGENT_DIR / ".venv" / "Scripts" / "python.exe"
SERVER_LOG_FILE = BASE_DIR / "server.log"

for p in [AGENT_DIR, PROJECT_ROOT / "shared", PROJECT_ROOT / "backend"]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
HEALTH_URL = f"{SERVER_URL}/api/health"


def is_port_listening(host: str = SERVER_HOST, port: int = SERVER_PORT) -> bool:
    """Instant socket check without proxy overhead."""
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def is_server_ready() -> bool:
    """Check if the FastAPI app has completed startup."""
    if not is_port_listening():
        return False
    try:
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(HEALTH_URL, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_server(proc: subprocess.Popen, timeout_sec: int = 60) -> bool:
    """Wait for server with live progress and error reporting."""
    start_time = time.time()
    print("      Initializing PyTorch engine and neural weights", end="", flush=True)

    while time.time() - start_time < timeout_sec:
        # Check if process terminated
        if proc.poll() is not None:
            print("\n[ERROR] Server process exited with code:", proc.returncode)
            if SERVER_LOG_FILE.exists():
                print("\nServer Log Output:\n" + SERVER_LOG_FILE.read_text(encoding="utf-8", errors="replace"))
            return False

        if is_server_ready():
            print(" [READY]")
            return True

        print(".", end="", flush=True)
        time.sleep(1.0)

    print("\n[ERROR] Timeout waiting for server startup.")
    if SERVER_LOG_FILE.exists():
        print("\nLast server log:\n" + SERVER_LOG_FILE.read_text(encoding="utf-8", errors="replace")[-500:])
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


def launch_window():
    """Launch dedicated desktop window using Chrome/Edge app mode or pywebview."""
    browser_exe = find_browser_app_binary()
    if browser_exe:
        print(f"      Launching standalone app container ({Path(browser_exe).stem})...")
        subprocess.Popen([
            browser_exe,
            f"--app={SERVER_URL}",
            "--window-size=1360,880",
            "--app-auto-launched"
        ])
        return

    # Fallback: pywebview
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
        )
        webview.start()
        return
    except Exception as e:
        print(f"[Notice] webview: {e}")

    # Fallback to default
    os.system(f'start "" "{SERVER_URL}"')


def main():
    print("=" * 60)
    print("  WorkSense - Early-Warning Burnout Prevention")
    print("  Desktop Application Launcher")
    print("=" * 60)

    server_process = None
    log_fp = None

    if not is_server_ready():
        print("[1/2] Starting backend engine & neural network...")
        py_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

        env = os.environ.copy()
        python_paths = [str(PROJECT_ROOT / "agent"), str(PROJECT_ROOT / "shared"), str(BASE_DIR)]
        env["PYTHONPATH"] = os.pathsep.join(python_paths)

        # Redirect to log file to avoid pipe buffer deadlocks
        log_fp = open(SERVER_LOG_FILE, "w", encoding="utf-8")

        server_process = subprocess.Popen(
            [
                py_exe,
                "-m",
                "uvicorn",
                "server:app",
                "--app-dir",
                str(BASE_DIR),
                "--host",
                SERVER_HOST,
                "--port",
                str(SERVER_PORT),
                "--log-level",
                "info",
            ],
            cwd=str(BASE_DIR),
            env=env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
        )

        if not wait_for_server(server_process, timeout_sec=60):
            if server_process:
                server_process.terminate()
            if log_fp:
                log_fp.close()
            sys.exit(1)
        print("      Backend ready.")
    else:
        print("[1/2] Backend engine is active on port 8000.")

    # 2. Launch dedicated desktop window
    print("[2/2] Launching WorkSense Desktop App window...")
    launch_window()

    print("\n" + "=" * 60)
    print("  WorkSense is running in its own standalone window.")
    print("  Close this window or press CTRL+C to stop the application.")
    print("=" * 60 + "\n")

    if server_process:
        try:
            server_process.wait()
        except KeyboardInterrupt:
            print("\nShutting down WorkSense...")
            server_process.terminate()
        finally:
            if log_fp:
                log_fp.close()


if __name__ == "__main__":
    main()
