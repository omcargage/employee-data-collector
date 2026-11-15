"""Windows system state monitor detecting session lock/unlock and suspend/resume.

Uses lightweight ctypes calls to wtsapi32 and user32 (zero external dependencies).
Registers WTSRegisterSessionNotification and handles WM_WTSSESSION_CHANGE / WM_POWERBROADCAST.
"""
from datetime import datetime, timezone
from enum import Enum
import threading
from typing import Callable, Optional
import ctypes
from ctypes import wintypes
from pydantic import BaseModel, ConfigDict, Field


class SystemState(str, Enum):
    """Permitted system power and session lock states."""
    LOCK = "lock"
    UNLOCK = "unlock"
    SUSPEND = "suspend"
    RESUME = "resume"


class SystemStateEvent(BaseModel):
    """State transition event with timestamp."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts_utc: datetime = Field(description="UTC timestamp of the system state transition")
    state: SystemState = Field(description="Transition type: lock, unlock, suspend, resume")


# 64-bit compatible Windows types
LRESULT = ctypes.c_ssize_t

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
wtsapi32 = ctypes.windll.wtsapi32

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL

wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL

wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

# Windows message constants
WM_DESTROY = 0x0002
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1

# WTS session notification constants
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

# Power broadcast event constants
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND


class WindowsSystemStateMonitor:
    """Monitors session lock/unlock and suspend/resume events via Windows messages."""

    def __init__(self, callback: Callable[[SystemStateEvent], None]):
        self._callback = callback
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._atom: Optional[int] = None
        self._wndproc_cb: Optional[WNDPROC] = None
        self._ready_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def start(self) -> None:
        """Start the background Windows message loop thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._ready_event.clear()

        self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
        self._thread.start()
        # Wait until window is registered and listening
        self._ready_event.wait(timeout=2.0)

    def stop(self) -> None:
        """Post close message to hidden window and tear down message pump."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        if self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

    def emit(self, state: SystemState, ts_utc: Optional[datetime] = None) -> None:
        """Dispatch a SystemStateEvent to the callback."""
        event = SystemStateEvent(
            ts_utc=ts_utc or datetime.now(timezone.utc),
            state=state,
        )
        try:
            self._callback(event)
        except Exception:
            pass

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """Window procedure processing session change and power broadcast messages."""
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                self.emit(SystemState.LOCK)
            elif wparam == WTS_SESSION_UNLOCK:
                self.emit(SystemState.UNLOCK)
            return 0

        elif msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                self.emit(SystemState.SUSPEND)
            elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                self.emit(SystemState.RESUME)
            return 0

        elif msg == 0x0010:  # WM_CLOSE
            try:
                wtsapi32.WTSUnRegisterSessionNotification(hwnd)
            except Exception:
                pass
            user32.DestroyWindow(hwnd)
            return 0

        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run_message_loop(self) -> None:
        """Message pump creating hidden window and registering WTS notifications."""
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"EDC_SystemState_{id(self)}"

        self._wndproc_cb = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_cb
        wc.hInstance = hinstance
        wc.lpszClassName = class_name

        self._atom = user32.RegisterClassExW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(
            0, class_name, "EDC_Hidden_State_Window", 0, 0, 0, 0, 0, 0, 0, hinstance, None
        )

        if self._hwnd:
            # Register for session notifications (lock/unlock)
            wtsapi32.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION)
        self._ready_event.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup window class
        try:
            user32.UnregisterClassW(class_name, hinstance)
        except Exception:
            pass
        self._hwnd = None
