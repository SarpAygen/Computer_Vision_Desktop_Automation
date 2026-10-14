"""
Hallows' Eve Macro  -  Fish! An Anime RNG  (4 Roblox windows)

A small desktop program that:
  * watches the TOP-LEFT Roblox window for the Hallows' Eve banner (screen OCR)
  * when the event starts  -> clicks into each window and presses your character key (default 2)
  * when the event ends    -> clicks into each window and presses it again (unequips)
  * closes the "Welcome Back" popup whenever it shows (red X only, never YES)
  * clicks each window every few minutes so Roblox doesn't kick you for being idle
  * CHECKS every window's hotbar (blue outline = character held) and fixes any window whose
    character is equipped when it shouldn't be, or missing when it should be
  * optional REBIRTH macro per window: tries a rebirth every minute (never touches the Robux buttons)
  * ALWAYS closes any Robux purchase prompt ("Buy item") with its X, on every window
  * locates the hotbar dynamically and skips Dracula characters (slot 2 onward)
  * counts how many Hallows' Eves it has seen this session
  * has bindable Start / Stop hotkeys, diagnostics and a rounded, animated Qt desktop UI
  * saves rotating activity logs under the HallowsEveMacro/logs folder in Local AppData

First run (Windows): missing Python packages install automatically in a private environment.
Tesseract installs through winget if available (Windows may ask for approval).
Requires Python with Tcl/Tk to launch this .py file; first-time downloads require internet.
If automatic Tesseract setup fails, the setup window offers downloads and path selection.
Run:      python hallows_eve_macro.py
Windows .exe: run BUILD_WINDOWS.cmd from the project bundle; share the generated app ZIP.
"""

import ctypes
import difflib
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
try:
    import tkinter as tk
    from tkinter import filedialog, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:
    message = "Python's Tcl/Tk component is missing. Repair Python and enable Tcl/Tk to run this macro."
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Hallows' Eve setup", 0x10)
    else:
        print(message)
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# First-run setup. Standard library only: this must precede third-party imports.
# ---------------------------------------------------------------------------
import hashlib
import subprocess

_PYTHON_PACKAGES = ("pyautogui", "pywin32", "mss", "opencv-python", "numpy", "pytesseract",
                    "PySide6-Essentials>=6.6,<7")
_IMPORT_PROBE = ("import cv2, mss, numpy, pyautogui, pytesseract, "
                 "win32api, win32con, win32gui, win32process; "
                 "from PySide6 import QtCore, QtGui, QtWidgets")
_TESSERACT_HELP = "https://github.com/UB-Mannheim/tesseract/wiki"
_BOOTSTRAP_TESSERACT = ""


def _app_folder():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))


def _setup_folder():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                        "HallowsEveMacro")


def _console_python(executable):
    # pythonw has no usable console streams for pip/venv. Use its sibling python.
    if os.path.basename(executable).lower() == "pythonw.exe":
        sibling = os.path.join(os.path.dirname(executable), "python.exe")
        if os.path.isfile(sibling):
            return sibling
    return executable


def _setup_command(command, log_path, timeout=900):
    """No shell interpolation. Keep installer output available even after a failure."""
    with open(log_path, "a", encoding="utf-8") as out:
        out.write("\n" + subprocess.list2cmdline(command) + "\n")
        out.flush()
        result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode


def _python_ready(executable, log_path):
    try:
        return _setup_command([executable, "-c", _IMPORT_PROBE], log_path, timeout=60) == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _prepare_python(status, log_path):
    if getattr(sys, "frozen", False):
        return None  # PyInstaller bundles imports; never run the exe as `python -m pip`.
    current = _console_python(sys.executable)
    status("Checking Python packages…")
    if _python_ready(current, log_path):
        return None
    base = _console_python(getattr(sys, "_base_executable", sys.executable))
    identity = hashlib.sha256(os.path.normcase(base).encode("utf-8")).hexdigest()[:10]
    env_dir = os.path.join(_setup_folder(),
                           f"python-{sys.version_info.major}.{sys.version_info.minor}-{identity}")
    python = os.path.join(env_dir, "Scripts", "python.exe")
    if os.path.isfile(python) and _python_ready(python, log_path):
        return python
    if os.path.normcase(os.path.abspath(current)) == os.path.normcase(os.path.abspath(python)):
        raise RuntimeError("The macro's Python environment could not load its packages. "
                           "Close this window and run the original .py file using your normal Python. "
                           "See the setup log for the failing package.")
    status("Creating the macro's private Python environment…")
    if _setup_command([base, "-m", "venv", env_dir], log_path, timeout=180) != 0:
        raise RuntimeError("Could not create the Python environment. Repair your Python installation "
                           "with pip, venv and Tcl/Tk enabled, then run this file again.")
    status("Installing Python packages from PyPI…\nFirst-time setup can take several minutes.")
    command = [python, "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
               "--no-input", "--index-url", "https://pypi.org/simple", "--prefer-binary",
               *_PYTHON_PACKAGES]
    if _setup_command(command, log_path) != 0 or not _python_ready(python, log_path):
        raise RuntimeError("Python package installation did not finish successfully. Check your "
                           "internet connection and the setup log, then run this file again. "
                           "Use a supported 64-bit Python release if no matching package is available.")
    return python


def _tesseract_candidates():
    # Check the user's explicit setting first, then this computer's saved setup path.
    for config in (os.path.join(_setup_folder(), "hallows_macro_settings.json"),
                   os.path.join(_app_folder(), "hallows_macro_settings.json"),
                   os.path.join(_setup_folder(), "setup.json")):
        try:
            with open(config, encoding="utf-8") as f:
                path = json.load(f).get("tesseract")
            if isinstance(path, str) and path:
                yield path
        except (OSError, ValueError, AttributeError):
            pass
    path = shutil.which("tesseract")
    if path:
        yield path
    # A complete portable Tesseract folder beside the macro also works.
    yield os.path.join(_app_folder(), "Tesseract-OCR", "tesseract.exe")
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        folder = os.environ.get(variable)
        if folder:
            yield os.path.join(folder, "Tesseract-OCR", "tesseract.exe")
            if variable == "LOCALAPPDATA":
                yield os.path.join(folder, "Programs", "Tesseract-OCR", "tesseract.exe")
    # Read registered install directories: PATH is not refreshed in a running process.
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Tesseract-OCR", 0,
                                    winreg.KEY_READ | view) as key:
                    for value in ("Path", "InstallDir"):
                        try:
                            folder = winreg.QueryValueEx(key, value)[0]
                            if isinstance(folder, str):
                                yield os.path.join(folder, "tesseract.exe")
                        except OSError:
                            pass
            except OSError:
                pass
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                    0, winreg.KEY_READ | view) as parent:
                    for index in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as key:
                                name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                                if "tesseract" in name.lower():
                                    folder = winreg.QueryValueEx(key, "InstallLocation")[0]
                                    if isinstance(folder, str) and folder:
                                        yield os.path.join(folder, "tesseract.exe")
                        except OSError:
                            continue
            except OSError:
                pass


def _find_tesseract():
    seen = set()
    for candidate in _tesseract_candidates():
        path = os.path.abspath(os.path.expandvars(candidate.strip().strip('"')))
        if os.path.normcase(path) in seen or not os.path.isfile(path):
            continue
        seen.add(os.path.normcase(path))
        try:
            result = subprocess.run([path, "--list-langs"], capture_output=True, text=True,
                                    errors="replace", timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0 and "eng" in {line.strip() for line in result.stdout.splitlines()}:
                return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _prepare_tesseract(status, log_path):
    status("Checking Tesseract and its English language data…")
    path = _find_tesseract()
    if path:
        return path
    winget = shutil.which("winget")
    if not winget:
        candidate = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft",
                                 "WindowsApps", "winget.exe")
        winget = candidate if os.path.isfile(candidate) else None
    if not winget:
        raise RuntimeError("Tesseract was not found and Windows Package Manager (winget) is unavailable. "
                           "Use the Tesseract download button below to install it with English language "
                           "data, then run this macro again. A custom install can also be selected below.")
    status("Installing Tesseract through Windows Package Manager…\n"
           "Approve the Windows installer prompt if it appears.")
    code = _setup_command([winget, "install", "--id", "UB-Mannheim.TesseractOCR", "--exact",
                           "--source", "winget", "--silent", "--accept-package-agreements",
                           "--accept-source-agreements", "--disable-interactivity"], log_path)
    # Some winget statuses mean already installed; trust a working executable, not the exit code alone.
    path = _find_tesseract()
    if not path:
        raise RuntimeError(f"Tesseract setup did not produce a working English OCR installation "
                           f"(winget result: {code}). Install/repair Tesseract using the download "
                           "button, or select an existing tesseract.exe, then run the macro again.")
    return path


def bootstrap():
    """Responsive first-run setup; installs nothing when requirements already work."""
    global _BOOTSTRAP_TESSERACT
    if sys.platform != "win32":
        raise SystemExit("Hallows' Eve Macro requires Windows. No packages were installed.")
    root = tk.Tk()
    root.title("Hallows' Eve • setup")
    root.geometry("620x340")
    root.configure(bg="#171e2d")
    root.resizable(False, False)
    tk.Label(root, text="Getting your macro ready", bg="#171e2d", fg="#f6a64b",
             font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=24, pady=(22, 12))
    status_var = tk.StringVar(value="Checking this computer…")
    tk.Label(root, textvariable=status_var, bg="#171e2d", fg="#edf1fa", wraplength=560,
             justify="left", font=("Segoe UI", 10)).pack(anchor="w", padx=24)
    bar = ttk.Progressbar(root, mode="indeterminate")
    bar.pack(fill="x", padx=24, pady=18)
    bar.start(12)
    tk.Label(root, text="Missing packages install automatically. Existing installations are reused.\n"
             "First-time downloads need internet. Tesseract installs with its standard license terms.",
             bg="#171e2d", fg="#a6b1c7", wraplength=560, justify="left",
             font=("Segoe UI", 9)).pack(anchor="w", padx=24)
    events = queue.Queue()
    outcome = {}
    # Do not terminate midway through a pip/Windows installer transaction.
    root.protocol("WM_DELETE_WINDOW", lambda: status_var.set(
        "Setup is still running. Please wait for installation to finish."))
    log_path = os.path.join(_setup_folder(), "setup.log")

    def work():
        try:
            os.makedirs(_setup_folder(), exist_ok=True)
            # One log per launch, so successful daily checks cannot grow it forever.
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("Hallows' Eve setup " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            status = lambda text: events.put(("status", text))
            python = _prepare_python(status, log_path)
            tesseract = _prepare_tesseract(status, log_path)
            with open(os.path.join(_setup_folder(), "setup.json"), "w", encoding="utf-8") as f:
                json.dump({"tesseract": tesseract}, f)
            events.put(("done", (python, tesseract)))
        except Exception as exc:
            events.put(("error", str(exc)))

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "status":
                    status_var.set(value)
                elif kind == "done":
                    outcome["result"] = value
                    root.destroy()
                    return
                elif kind == "error":
                    bar.stop()
                    root.geometry("620x460")
                    status_var.set("Setup needs attention\n\n" + value)
                    root.protocol("WM_DELETE_WINDOW", root.destroy)
                    actions = ttk.Frame(root)
                    actions.pack(fill="x", padx=24, pady=14)
                    def download():
                        import webbrowser
                        webbrowser.open(_TESSERACT_HELP)
                    def select():
                        path = filedialog.askopenfilename(parent=root, title="Select tesseract.exe",
                            filetypes=[("Tesseract executable", "tesseract.exe")])
                        if path:
                            try:
                                with open(os.path.join(_setup_folder(), "setup.json"), "w",
                                          encoding="utf-8") as f:
                                    json.dump({"tesseract": path}, f)
                                status_var.set("Saved the Tesseract path. Close this window and run "
                                               "the macro again to verify it and finish setup.")
                            except OSError as exc:
                                status_var.set(f"Could not save path: {exc}")
                    ttk.Button(actions, text="Tesseract downloads", command=download).pack(side="left")
                    ttk.Button(actions, text="Select tesseract.exe", command=select).pack(side="left", padx=6)
                    ttk.Button(actions, text="Open setup log", command=lambda: os.startfile(log_path)).pack(side="left")
                    ttk.Button(root, text="Close", command=root.destroy).pack(pady=8)
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=work, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    if "result" not in outcome:
        raise SystemExit(1)
    python, _BOOTSTRAP_TESSERACT = outcome["result"]
    if python:
        # Relaunch under the prepared environment. The child validates it, then opens the macro.
        child = subprocess.Popen([python, os.path.abspath(__file__), *sys.argv[1:]],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raise SystemExit(child.wait())


try:  # real pixel coordinates on scaled displays (must happen before the GUI is created)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

if __name__ == "__main__":
    bootstrap()


import cv2
import mss
import numpy as np
import pyautogui
import pytesseract
import win32api
import win32con
import win32gui
import win32process

_MSS = getattr(mss, "MSS", None) or mss.mss  # newer mss renamed mss.mss -> mss.MSS
pyautogui.FAILSAFE = False   # stop with your Stop hotkey / button instead
pyautogui.PAUSE = 0.05

# ----------------------------------------------------------------------------
# Constants (advanced - the GUI covers the everyday options)
# ----------------------------------------------------------------------------
APP_NAME = "Hallows' Eve Macro"
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.makedirs(_setup_folder(), exist_ok=True)
SETTINGS_FILE = os.path.join(_setup_folder(), "hallows_macro_settings.json")
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

EVENT_REGION = (0.30, 0.07, 0.70, 0.18)   # Hallows' Eve banner title area (window-relative fractions)
POPUP_REGION = (0.15, 0.20, 0.80, 0.80)   # popups: "Welcome Back" and the Robux "Buy item" prompt
WELCOME_CLOSE = (0.745, 0.264)            # its red X (never the YES button)
# Rebirth + Robux prompt click spots (fractions of the window; measured from your screenshots)
REBIRTH_ICON = (0.034, 0.447)             # REBIRTH button in the left sidebar
REBIRTH_BUTTON = (0.367, 0.662)           # green "Rebirth!" button in the rebirth menu
#   NOTE: the purple "400 Robux" button sits at about (0.63, 0.66) - it is NEVER clicked
REBIRTH_MENU_CLOSE = (0.758, 0.296)       # red X of the rebirth menu
ROBUX_CLOSE_SPOTS = [(0.747, 0.286), (0.744, 0.336)]   # fallback X spots for the two prompt sizes seen
ROBUX_X_OFFSET = 0.504                    # X is this fraction of the window width right of the "Buy" title
MENU_REGION = (0.23, 0.29, 0.77, 0.72)    # where the rebirth menu text ("Requirements") appears
AFK_CLICK_SPOT = (0.50, 0.33)             # harmless empty-world spot for the anti-AFK click
KEYWORDS = ["hallows"]                    # fuzzy-matched in the banner text

POLL_SECONDS = 0.08         # target visual polling interval; OCR fallback runs separately
OCR_TIMEOUT = 5.0          # bound a stalled Tesseract call; normal reads finish much sooner
MAX_HOLD_SECONDS = 600      # pause for review if an event remains active this long
MAINTENANCE_SECONDS = 20    # popup check / anti-AFK pass interval
TITLEBAR_CLICK_Y = 12       # px below the window top used to give a window focus
STEP_DELAY = 0.35
CORNERS = ["Top-left (main)", "Top-right", "Bottom-left", "Bottom-right"]

DEFAULTS = {
    "start_vk": 0x75,       # F6
    "stop_vk": 0x76,        # F7
    "char_key": "2",
    "settle": 2.0,          # seconds to wait after clicking into a window before pressing the key
    "afk_enabled": True,
    "afk_minutes": 4.0,
    "close_popup": True,
    "verify_state": True,
    "rebirth": [False, False, False, False],
    "rebirth_seconds": 60.0,
    "tesseract": DEFAULT_TESSERACT,
    "test_seconds": 15,
    "dracula_rotation": True,  # skip Dracula characters, starting from slot 2
    "webhook_url": "",
    "webhook_events": False,
    "webhook_dracula": False,
    "reduce_motion": False,
    "fast_detection": True,
    "stop_when_complete": False,
    "completion_sound": True,
    "setup_complete": False,
}
S = dict(DEFAULTS)


def load_settings():
    try:
        source = SETTINGS_FILE if os.path.isfile(SETTINGS_FILE) else os.path.join(APP_DIR, "hallows_macro_settings.json")
        with open(source, "r", encoding="utf-8") as f:
            S.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    reb = S.get("rebirth")
    if not isinstance(reb, list) or len(reb) != 4:
        S["rebirth"] = [False, False, False, False]


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(S, f, indent=2)
    except Exception:
        pass


def setup_tesseract():
    path = S.get("tesseract") or ""
    if not os.path.exists(path):
        path = shutil.which("tesseract") or path
    pytesseract.pytesseract.tesseract_cmd = path


# ----------------------------------------------------------------------------
# Thread plumbing: log queue, stop flag, interruptible sleep
# ----------------------------------------------------------------------------
UI = queue.Queue()
STOP = threading.Event()


class StopMacro(Exception):
    pass


class Preempt(BaseException):
    """Raised inside low-priority chores (window checks, rebirths, verification) when the event
    just started/ended, so the equip/unequip can happen right away. BaseException so that the
    'except Exception' blocks sprinkled through the code can never swallow it."""


_tl = threading.local()
SHARED = {"want": False, "holding": False}   # want = detector's verdict, holding = what we've acted on


class preemptible:
    def __enter__(self):
        _tl.preemptible = True

    def __exit__(self, *exc):
        _tl.preemptible = False


def log(msg):
    UI.put(("log", time.strftime("[%H:%M:%S] ") + msg))


def check_stop():
    local_stop = getattr(_tl, "stop", None)
    if STOP.is_set() or (local_stop is not None and local_stop.is_set()):
        raise StopMacro()
    if getattr(_tl, "preemptible", False) and SHARED["want"] != SHARED["holding"]:
        raise Preempt()


def sleep(seconds):
    end = time.monotonic() + seconds
    while True:
        check_stop()
        left = end - time.monotonic()
        if left <= 0:
            return
        STOP.wait(min(0.05, left))


# ----------------------------------------------------------------------------
# Low-level input (hardware scan codes + real hold time, which Roblox needs)
# ----------------------------------------------------------------------------
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SCANCODES = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
             "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_scan(scan, flags):
    inp = _INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    inp.ki = _KEYBDINPUT(0, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def tap_key(key, hold=0.12):
    check_stop()
    scan = SCANCODES.get(str(key))
    if scan is None:
        pyautogui.keyDown(key)
        try:
            time.sleep(hold)
        finally:
            pyautogui.keyUp(key)
        return
    _send_scan(scan, KEYEVENTF_SCANCODE)
    try:
        time.sleep(hold)
    finally:
        _send_scan(scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)


def hold_click(hold=0.08):
    check_stop()
    pyautogui.mouseDown()
    try:
        time.sleep(hold)
    finally:
        pyautogui.mouseUp()


MOUSEEVENTF_MOVE = 0x0001


def _mouse_rel(dx, dy):
    """A real relative mouse-move event (what a physical mouse sends), unlike a cursor teleport."""
    inp = _INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi = _MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def hover_click(x, y, hold=0.1):
    """
    Click like a person: glide in from a little way off with real mouse-move events, wiggle a few
    pixels while resting on the spot (so the game registers the hover), then press and release.
    """
    check_stop()
    win32api.SetCursorPos((x - 36, y - 20))
    sleep(0.08)
    for i in range(12):                       # glide toward the spot
        _mouse_rel(3, 2 if i < 8 else 1)
        sleep(0.025)
    win32api.SetCursorPos((x, y))             # correct any pointer-acceleration drift
    sleep(0.1)
    for dx, dy in ((2, 1), (-2, -1), (1, 2), (-1, -2), (2, 0), (-2, 0)):   # wiggle on the spot
        _mouse_rel(dx, dy)
        sleep(0.05)
    win32api.SetCursorPos((x, y))
    sleep(0.2)
    _mouse_rel(1, 0)                          # one last nudge right before pressing
    sleep(0.05)
    pyautogui.mouseDown()
    try:
        time.sleep(hold)
    finally:
        pyautogui.mouseUp()


# ----------------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------------
@dataclass
class Win:
    hwnd: int
    left: int
    top: int
    right: int
    bottom: int
    slot: int = 0

    @property
    def w(self):
        return self.right - self.left

    @property
    def h(self):
        return self.bottom - self.top

    @property
    def name(self):
        return CORNERS[self.slot] if 0 <= self.slot < 4 else f"Window {self.slot + 1}"


def _frame_rect(hwnd):
    rect = wintypes.RECT()
    ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect))  # visible frame bounds
    if ok != 0:
        return win32gui.GetWindowRect(hwnd)
    return rect.left, rect.top, rect.right, rect.bottom


def _show_state(hwnd):
    try:
        return win32gui.GetWindowPlacement(hwnd)[1]
    except Exception:
        return win32con.SW_SHOWNORMAL


def live_roblox_hwnds():
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "Roblox":
            if _show_state(hwnd) == win32con.SW_SHOWMINIMIZED:
                found.append(hwnd)
                return
            l, t, r, b = _frame_rect(hwnd)
            if r - l > 300 and b - t > 300:
                found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found


def order_windows(hwnds):
    """Top row left->right, then bottom row left->right."""
    screen_h = pyautogui.size()[1]
    items = []
    for h in hwnds:
        l, t, r, b = _frame_rect(h)
        items.append((0 if (t + b) / 2 < screen_h / 2 else 1, (l + r) / 2, h))
    items.sort()
    return [x[2] for x in items]


class Slots:
    def __init__(self, hwnds):
        self.hwnds = list(hwnds)

    def __len__(self):
        return len(self.hwnds)

    def win(self, i):
        h = self.hwnds[i]
        if h and win32gui.IsWindow(h) and win32gui.IsWindowVisible(h) \
                and win32gui.GetWindowText(h) == "Roblox":
            if _show_state(h) == win32con.SW_SHOWMINIMIZED:
                win32gui.ShowWindow(h, win32con.SW_RESTORE)
                sleep(0.4)
            l, t, r, b = _frame_rect(h)
            return Win(h, l, t, r, b, i)
        return None

    def all(self):
        return [w for w in (self.win(i) for i in range(len(self))) if w]


def scan_windows(passive=False):
    hwnds = live_roblox_hwnds()
    for h in hwnds:
        if not passive and _show_state(h) == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            sleep(0.4)
    hwnds = order_windows(live_roblox_hwnds())
    if not hwnds:
        log("No Roblox windows found. Open your game windows first.")
        return None
    if len(hwnds) > 4:
        log(f"Found {len(hwnds)} Roblox windows; using the first 4.")
        hwnds = hwnds[:4]
    slots = Slots(hwnds)
    log(f"Found {len(hwnds)} Roblox window(s): " + ", ".join(CORNERS[i] for i in range(len(hwnds))))
    if len(hwnds) != 4:
        log("(Expected 4. The macro will still run on the windows it found.)")
    return slots


def foreground_title():
    try:
        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "?"
    except Exception:
        return "?"


def bring_to_front(hwnd):
    """Raise a window to the very front (the windows overlap each other)."""
    if win32gui.GetForegroundWindow() == hwnd:
        return True
    try:
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    if win32gui.GetForegroundWindow() != hwnd:
        try:  # tapping ALT lets a background program take the foreground
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    if win32gui.GetForegroundWindow() != hwnd:
        try:  # strongest fallback: share input state with the current foreground window
            fg = win32gui.GetForegroundWindow()
            fg_thread = win32process.GetWindowThreadProcessId(fg)[0]
            me = win32api.GetCurrentThreadId()
            win32process.AttachThreadInput(me, fg_thread, True)
            try:
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            finally:
                win32process.AttachThreadInput(me, fg_thread, False)
        except Exception:
            pass
    return win32gui.GetForegroundWindow() == hwnd


def _root_at(x, y):
    h = win32gui.WindowFromPoint((x, y))
    return ctypes.windll.user32.GetAncestor(h, 2) if h else 0  # 2 = GA_ROOT


def focus(win):
    """Bring the window to the front and click its title bar so Roblox truly has focus."""
    ok = False
    for _ in range(3):
        ok = bring_to_front(win.hwnd)
        sleep(0.3)
        if ok:
            break
    if not ok:
        log(f"  {win.name}: Windows refused to focus this window")
    x, y = win.left + win.w // 2, win.top + TITLEBAR_CLICK_Y
    if _root_at(x, y) == win.hwnd:  # only click if that pixel really belongs to this window
        pyautogui.moveTo(x, y, duration=0.1)
        hold_click()
        sleep(0.2)
    return ok


# ----------------------------------------------------------------------------
# Screen reading (OCR)
# ----------------------------------------------------------------------------
def close_capture():
    """MSS handles belong to the thread that created them."""
    sct = getattr(_tl, "capture", None)
    if sct is not None:
        _tl.capture = None
        sct.close()


def grab(win, region):
    check_stop()
    l = win.left + int(win.w * region[0])
    t = win.top + int(win.h * region[1])
    r = win.left + int(win.w * region[2])
    b = win.top + int(win.h * region[3])
    sct = getattr(_tl, "capture", None)
    if sct is None:
        sct = _tl.capture = _MSS()
    try:
        shot = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
    except Exception:
        close_capture()  # recreate on the next attempt after a capture failure
        raise
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # one BGR copy, not two


def ocr(img, *, data=False):
    """Check cancellation between OCR passes and bound each subprocess."""
    check_stop()
    if data:
        result = pytesseract.image_to_data(
            img, config="--psm 6", output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT)
    else:
        result = pytesseract.image_to_string(img, config="--psm 6", timeout=OCR_TIMEOUT)
    check_stop()
    return result


def read_text(img, scale=3, n=3):
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    # Most calls use only two passes; do not allocate an unused threshold image.
    variants = [gray]
    if n >= 2:
        variants.append(255 - gray)
    if n >= 3:
        variants.append(cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1])
    out = [ocr(v) for v in variants[:n]]
    return "\n".join(out)


def has_word(words, target, cutoff):
    return bool(difflib.get_close_matches(target, words, n=1, cutoff=cutoff))


def read_event(win):
    """Returns (is_hallows_eve, text_read, image). Stops at the first OCR pass that finds the title."""
    img = grab(win, EVENT_REGION)
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    text = ""
    for inverted in (False, True):
        text += "\n" + ocr(255 - gray if inverted else gray)
        words = re.findall(r"[a-z]+", text.lower())
        if any(has_word(words, k, 0.8) for k in KEYWORDS):
            return True, text, img
    return False, text, img


def popup_state(win):
    """Which blocking popups are showing: {'welcome'} and/or {'robux'} (the Roblox 'Buy item' prompt)."""
    words = re.findall(r"[a-z]+", read_text(grab(win, POPUP_REGION), scale=2, n=2).lower())
    found = set()
    if any(has_word(words, k, 0.8) for k in ("welcome", "offline", "triple")):
        found.add("welcome")
    if (has_word(words, "buy", 0.9) and (has_word(words, "item", 0.85) or has_word(words, "robux", 0.85))) or \
            (has_word(words, "skip", 0.9) and has_word(words, "rebirth", 0.8)) or \
            (has_word(words, "payment", 0.85) and has_word(words, "charged", 0.85)):
        found.add("robux")
    return found


def popup_visible(win):
    return bool(popup_state(win))


def rebirth_menu_open(win):
    words = re.findall(r"[a-z]+", read_text(grab(win, MENU_REGION), scale=2, n=2).lower())
    return has_word(words, "requirements", 0.8)


def _runs(row, min_len):
    """Inclusive endpoints, including runs that touch either image edge."""
    padded = np.empty(len(row) + 2, dtype=np.int8)
    padded[0] = padded[-1] = 0
    padded[1:-1] = np.asarray(row, dtype=bool)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1
    keep = ends - starts + 1 >= min_len
    return list(zip(starts[keep].tolist(), ends[keep].tolist()))


HOTBAR_STRIP = (0.0, 0.925, 1.0, 1.0)   # bottom of the window, where the hotbar lives


def character_equipped(win):
    """
    True if a hotbar slot has the bright-blue 'held' outline. The outline is a box: a top edge and a
    bottom edge of the same blue (R<=45, G 110-215, B>=230), the same width, ~5% of the window
    height apart. Rarity borders and UI text never form that shape.
    """
    img = grab(win, HOTBAR_STRIP)
    r, g, b = img[..., 2], img[..., 1], img[..., 0]
    mask = (r <= 45) & (b >= 230) & (g >= 110) & (g <= 215)
    min_len = max(8, int(win.w * 0.026))
    # Index edges by row instead of comparing every edge against every other edge.
    rows = [_runs(row, min_len) for row in mask]
    lo, hi = 0.035 * win.h, 0.075 * win.h
    for y1, runs in enumerate(rows):
        if not runs:
            continue
        for y2 in range(y1 + int(np.ceil(lo)), min(len(rows), y1 + int(hi) + 1)):
            for a1, z1 in runs:
                for a2, z2 in rows[y2]:
                    if abs(a1 - a2) <= 4 and abs(z1 - z2) <= 4:
                        return True
    return False


# ----------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------
# Dynamic hotbar reading: cards are located afresh, never by fixed slot coordinates.
MUTATION_REGION = (0.10, 0.90, 0.90, 1.0)
SLOT_KEYS = "1234567890"


@dataclass
class HotbarCard:
    number: int
    box: tuple
    equipped: bool
    dracula: object = None  # True / False / None (unreadable)
    text: str = ""
    kind: str = "character"  # neutral-border consumables are excluded from rotation


def locate_hotbar(img, window_width, window_height):
    """Return a centered, contiguous row of 2..10 square cards, or no guess.

    Coordinates are relative to MUTATION_REGION. Nested contours are deduplicated.
    Regular spacing + center alignment reject partial/obscured rows rather than
    renumbering their remaining cards and sending the wrong hotkey.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 110, 100), (179, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (0.033 * window_height <= h <= 0.085 * window_height
                and 0.75 <= w / h <= 1.25
                and y + h >= img.shape[0] - 0.035 * window_height):
            candidates.append((x, y, w, h))
    boxes = []
    for box in sorted(candidates, key=lambda b: b[2] * b[3], reverse=True):
        x, y, w, h = box
        if not any(abs(x + w / 2 - (a + c / 2)) < 0.45 * max(w, c)
                   and abs(y + h / 2 - (b + d / 2)) < 0.45 * max(h, d)
                   for a, b, c, d in boxes):
            boxes.append(box)
    # Consumables have neutral grey borders. Recover actual square outlines near
    # the coloured card row; never infer a missing slot solely from spacing.
    edges = cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 40, 120)
    outlines, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    anchors = list(boxes)
    for contour in outlines:
        x, y, w, h = cv2.boundingRect(contour)
        if not any(abs((y+h/2)-(b+d/2)) < .12*d
                   and .85*c <= w <= 1.12*c and .85*d <= h <= 1.12*d
                   for a,b,c,d in anchors):
            continue
        if not any(abs(x+w/2-(a+c/2)) < .45*max(w,c)
                   and abs(y+h/2-(b+d/2)) < .45*max(h,d) for a,b,c,d in boxes):
            boxes.append((x,y,w,h))
    rows = []
    thick_edges = cv2.dilate(edges, np.ones((3,3), np.uint8)) > 0
    for anchor in boxes:
        row = sorted([b for b in boxes if abs(b[1] + b[3] / 2
                     - (anchor[1] + anchor[3] / 2)) < 0.18 * anchor[3]])
        if not 2 <= len(row) <= 10:
            continue
        sizes = np.array([b[2] for b in row])
        typical = float(np.median(sizes))
        centers = np.array([b[0] + b[2] / 2 for b in row])
        gaps = np.diff(centers)
        if (sizes.max() > typical * 1.2 or sizes.min() < typical * 0.8
                or np.any(gaps < typical * 0.88) or np.any(gaps > typical * 1.3)):
            continue
        center = (row[0][0] + row[-1][0] + row[-1][2]) / 2
        if abs(center - img.shape[1] / 2) > min(window_width * 0.015, typical * 0.35):
            continue
        # Coloured middle cards alone can form a centered row even when an
        # outer rod is covered and a neutral item was missed by the contours.
        if len(row) < 10:
            side = round(typical)
            top = round(float(np.median([b[1] for b in row])))
            bottom = top + round(float(np.median([b[3] for b in row])))
            margin = max(3, round(side*.15))
            pitch = float(np.median(gaps))
            extra = False
            for c in (centers[0]-pitch, centers[-1]+pitch):
                x = round(c-side/2)
                if x < 1 or x+side+1 >= img.shape[1]:
                    continue
                left = thick_edges[top+margin:bottom-margin,x-1:x+2].any(axis=1).mean()
                right = thick_edges[top+margin:bottom-margin,x+side-2:x+side+1].any(axis=1).mean()
                base = thick_edges[bottom-2:bottom+1,x+margin:x+side-margin].any(axis=0).mean()
                if base >= .68 and max(left,right) >= .68:
                    extra = True
                    break
            if extra:
                continue
        rows.append(row)
    if not rows:
        return fit_hotbar_grid(img, window_width, window_height, boxes)
    row = max(rows, key=len)
    # A selected blue outline can enlarge one contour; use the whole row's
    # typical geometry so the mutation-label crop does not move with selection.
    width = round(float(np.median([b[2] for b in row])))
    height = round(float(np.median([b[3] for b in row])))
    top = round(float(np.median([b[1] for b in row])))
    return [(round(x + w / 2 - width / 2), top, width, height) for x, y, w, h in row]


def fit_hotbar_grid(img, window_width, window_height, anchors):
    """Recover merged contours only when every proposed card has real edges.

    Bright selection borders can join neighbouring stars/cards into one contour.
    A grid hypothesis uses the remaining cards, then verifies all slot outlines;
    a missing/covered square is never accepted just because spacing predicts it.
    """
    edges = cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 40, 120)
    # Neutral item outlines must establish geometry independently of saturated
    # contours: stars/backgrounds can make the latter much larger than a card.
    outlines, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    anchors = list(anchors)
    for contour in outlines:
        x, y, w, h = cv2.boundingRect(contour)
        if (window_height*.033 <= h <= window_height*.085
                and .85 <= w/h <= 1.15
                and y+h >= img.shape[0]-window_height*.018):
            if not any(abs(x+w/2-(a+c/2)) < 3 and abs(y+h-(b+d)) < 3
                       and abs(w-c) < 4 for a,b,c,d in anchors):
                anchors.append((x,y,w,h))
    edges = cv2.dilate(edges, np.ones((3,3), np.uint8)) > 0
    solutions = []
    for anchor in anchors:
        row = sorted([b for b in anchors if abs(b[1]+b[3]-(anchor[1]+anchor[3])) <= 4
                      and .85*anchor[2] <= b[2] <= 1.15*anchor[2]
                      and .85*anchor[3] <= b[3] <= 1.15*anchor[3]])
        if len(row) < 3:
            continue
        # Inner/outer contours describe the same slot. Do not let those tiny
        # duplicate gaps bias the spacing estimate or inflate the slot count.
        unique = []
        for box in row:
            if unique and abs(box[0]+box[2]/2-(unique[-1][0]+unique[-1][2]/2)) < .3*anchor[2]:
                if box[2]*box[3] > unique[-1][2]*unique[-1][3]:
                    unique[-1] = box
            else:
                unique.append(box)
        row = unique
        if len(row) < 3:
            continue
        width = float(np.median([b[2] for b in row]))
        # The hotbar is centered and has at most ten slots. Buff/status icons
        # beside it can also produce square contours at the same height, but
        # cannot be slot centers outside even the widest allowed ten-slot row.
        max_center_distance = 4.5 * width * 1.25 + 3
        row = [b for b in row if abs(b[0]+b[2]/2-img.shape[1]/2) <= max_center_distance]
        if len(row) < 3:
            continue
        width = float(np.median([b[2] for b in row]))
        centers = np.array([x+w/2 for x,y,w,h in row])
        steps = np.diff(centers)
        steps = steps[(steps >= width*.9) & (steps <= width*1.25)]
        if not len(steps):
            continue
        pitch = float(np.median(steps))
        # Fit across the entire row, including gaps left by merged contours;
        # adjacent measurements alone accumulate pixel rounding errors.
        indices = np.rint((centers-centers[0])/pitch)
        if len(np.unique(indices)) != len(indices):
            continue
        pitch = float(np.polyfit(indices, centers, 1)[0])
        size = round(min(pitch-1, width))
        bottom = round(float(np.median([y+h for x,y,w,h in row])))
        top = bottom-size
        if size < window_height*.033 or top < 0 or bottom > img.shape[0]:
            continue
        for count in range(max(2,len(row)),11):
            expected = img.shape[1]/2 + (np.arange(count)-(count-1)/2)*pitch
            if any(np.min(abs(expected-c)) > 5 for c in centers):
                continue
            # Contours can follow inner artwork rather than the outer frame.
            # Search a bounded shared geometry correction, verifying real edges.
            for side in (size, size-2, size+2):
                if side < window_height*.033 or side >= pitch:
                    continue
                margin=max(3,round(side*.15))
                for base_y in (bottom, bottom+2, bottom-2):
                    top_y=base_y-side
                    if top_y < 0 or base_y >= img.shape[0]:
                        continue
                    def edge_strength(center):
                        x=round(center-side/2)
                        if x < 1 or x+side+1 >= img.shape[1]:
                            return (0., 0., 0.)
                        left=edges[top_y+margin:base_y-margin,x-1:x+2].any(axis=1).mean()
                        right=edges[top_y+margin:base_y-margin,x+side-2:x+side+1].any(axis=1).mean()
                        base=edges[base_y-2:base_y+1,x+margin:x+side-margin].any(axis=0).mean()
                        return left,right,base
                    for offset in (0, -1, 1, -2, 2):
                        strengths=[]
                        for center in expected+offset:
                            strength=edge_strength(center)
                            if min(strength)<.68:
                                break
                            strengths.append(strength)
                        if len(strengths)!=count:
                            continue
                        # Reject centered inner subsets of an incomplete row.
                        if count < 10:
                            extra=[edge_strength(c) for c in
                                   (expected[0]+offset-pitch,expected[-1]+offset+pitch)]
                            if any(base>=.68 and max(left,right)>=.68 for left,right,base in extra):
                                continue
                        proposed=[(round(c+offset-side/2),top_y,side,side) for c in expected]
                        solutions.append((count,float(np.mean(strengths)),proposed))
    return max(solutions,key=lambda solution:solution[:2])[2] if solutions else []


def card_is_equipped(img, box):
    x, y, w, h = box
    crop = img[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3]
    b, g, r = crop[..., 0], crop[..., 1], crop[..., 2]
    blue = (r <= 45) & (b >= 230) & (g >= 110) & (g <= 215)
    edge_rows = [i for i, row in enumerate(blue) if _runs(row, max(8, int(w * 0.55)))]
    return any(0.65 * h <= j - i <= 1.2 * h for i in edge_rows for j in edge_rows)


def read_mutation(img, box):
    """Read only the label above this card, excluding stars and the card artwork.

    A blank label with no red lettering is a non-Dracula card. Red lettering that
    cannot be read is unknown, not permission to skip the character.
    """
    x, y, w, h = box
    # Contours sometimes follow the inner artwork, several pixels below the
    # actual frame. Find a continuous coloured top edge before cropping text.
    # A mutation's separate glyphs/stars do not form a solid horizontal line.
    top = y
    left, right = max(0, x + round(w*.15)), min(img.shape[1], x + round(w*.85))
    for row in range(max(1, y-round(h*.18)), min(y+1, img.shape[0])):
        line = img[row, left:right].astype(np.int16)
        previous = img[row-1, left:right].astype(np.int16)
        if len(line) < 8:
            continue
        median = np.median(line, axis=0)
        uniform = np.max(abs(line-median), axis=1) < 45
        contrast = np.max(abs(line-previous), axis=1) > 55
        if (median.max() > 100 and median.max()-median.min() > 80
                and uniform.mean() >= .85 and contrast.mean() >= .70):
            top = row
            break
    label = img[max(0, top - round(h * 0.28)):top + 1, max(0, x - 1):x + w + 1]
    if label.size == 0 or label.shape[0] < 4:
        return None, "label outside capture"
    b, g, r = (label[..., i].astype(np.int16) for i in (0, 1, 2))
    red = (r > 95) & (r > g * 2.9) & (r > b * 1.6)
    red[-2:] = False  # ignore the card's own colored top border
    # Orange rarity stars are not red lettering. Large solid red scene regions
    # (visible behind slots 9/10 in the reference) are not letters either.
    _, labels, stats, _ = cv2.connectedComponentsWithStats(red.astype(np.uint8))
    # Purple rarity stars acquire a few dark-red pixels along their antialiased
    # edges. Remove only tiny components wholly adjacent to the purple fill;
    # substantial red text still goes through the conservative OCR path.
    purple = (r > 90) & (b > 60) & (b > r*.55) & (g < r*.5)
    near_purple = cv2.dilate(purple.astype(np.uint8), np.ones((5,5), np.uint8)) > 0
    letters = [i for i, (_, _, cw, ch, area) in enumerate(stats[1:], 1)
               if max(2, h * 0.065) <= ch <= h * 0.27
               and cw <= w * 0.35 and area >= max(2, h * 0.055)
               and not (area <= h*.20 and np.all(near_purple[labels == i]))]
    if not letters:
        return False, "no red mutation label"
    if len(letters) < 3:
        return None, "insufficient readable red lettering"
    red = np.isin(labels, letters)
    big = cv2.resize(label, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    isolated = cv2.resize((~red).astype(np.uint8) * 255, None, fx=6, fy=6,
                          interpolation=cv2.INTER_NEAREST)
    readings = []
    for variant in (big, gray, isolated):
        check_stop()
        text = pytesseract.image_to_string(variant, config="--psm 7", timeout=OCR_TIMEOUT)
        check_stop()
        readings.append(text.strip())
        words = re.findall(r"[a-z]+", text.lower())
        # Tiny outlined lettering often reads D as O/G and a as o; tolerate
        # those specific substitutions, including a joined bracket/edge glyph.
        if has_word(words, "dracula", 0.82) or any(
                re.fullmatch(r"[a-z]{0,2}[dog]r[ao]cula[a-z]{0,2}", word) for word in words):
            return True, " / ".join(readings)
        # Other readable mutation names are valid non-Dracula characters.
        others = {"demonic", "nightmare", "angelic", "mars", "void", "sinister", "lunar",
                  "solar", "toxic", "ghost", "blood", "electric", "lava", "slime", "zombie",
                  "diamond", "frozen", "party", "gold", "honey"}
        if any(word in others for word in words):
            return False, " / ".join(readings)
    return None, " / ".join(readings) or "unreadable red label"


def hotbar_card_kind(img, box):
    """Separate income-bearing characters from named consumables without OCR.

    Uncertain artwork is never permission to equip a slot. Every square still
    counts toward its original hotkey number, including consumables.
    """
    x,y,w,h = box
    crop = img[y+int(h*.65):y+h, max(0,x):x+w].astype(np.int16)
    if not crop.size:
        return "unknown"
    b,g,r = (crop[:,:,i] for i in range(3))
    green = ((g>130) & (g>r*1.5) & (g>b*1.35)).astype(np.uint8)
    _,_,stats,_ = cv2.connectedComponentsWithStats(green)
    letters = [c for c in stats[1:] if 2 <= c[3] <= h*.32 and c[2] <= w*.28 and c[4] >= 2]
    if len(letters) >= 3:
        return "character"
    title = img[max(0,y-round(h*.50)):max(0,y-1),max(0,x-2):x+w+2].astype(np.int16)
    if title.size:
        white = ((title.min(2)>100) & (title.max(2)-title.min(2)<60)).astype(np.uint8)
        _,_,stats,_ = cv2.connectedComponentsWithStats(white)
        words = [c for c in stats[1:] if 2 <= c[3] <= h*.28 and c[2] <= w and c[4] >= 2]
        if words and max(c[0]+c[2] for c in words)-min(c[0] for c in words) >= w*.5:
            return "item"
        # Bright scenery can join white potion lettering into one enormous
        # component. Remove broad white areas, then require several text-height
        # components on a shared baseline. Tiny star highlights are excluded.
        lettering = white[:max(1, len(white)-max(2, round(h*.10)))]
        thin = lettering - cv2.morphologyEx(lettering, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))
        _,_,stats,_ = cv2.connectedComponentsWithStats(thin)
        glyphs = [c for c in stats[1:] if max(3, h*.09) <= c[3] <= h*.28
                  and c[2] <= w*.55 and c[4] >= 3]
        for glyph in glyphs:
            line = [c for c in glyphs if abs(c[1]+c[3]-glyph[1]-glyph[3]) <= max(2,h*.06)]
            if len(line) >= 3 and max(c[0]+c[2] for c in line)-min(c[0] for c in line) >= w*.5:
                return "item"
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    rim = np.zeros(hsv.shape[:2], np.uint8)
    cv2.rectangle(rim, (x,y), (x+w-1,y+h-1), 255, 2)
    coloured = (hsv[:,:,1]>=110) & (hsv[:,:,2]>=100) & (rim!=0)
    if np.count_nonzero(coloured)/max(1,np.count_nonzero(rim)) < .25:
        return "item"
    return "unknown"


def hotbar_snapshot(win, read_labels=True):
    img = grab(win, MUTATION_REGION)
    boxes = locate_hotbar(img, win.w, win.h)
    cards = []
    for number, box in enumerate(boxes, 1):
        card = HotbarCard(number, box, card_is_equipped(img, box))
        card.kind = hotbar_card_kind(img, box)
        if read_labels and number >= 2 and card.kind == "character":
            card.dracula, card.text = read_mutation(img, box)
        elif card.kind != "character":
            card.text = "item; excluded from rotation" if card.kind == "item" else "unconfirmed card type"
        cards.append(card)
    return cards, img


def choose_character(cards):
    """First non-Dracula character; 0 means complete, None means uncertain."""
    if len(cards) < 2:
        return None
    if any(c.kind == "unknown" for c in cards[1:]):
        return None
    characters = [c for c in cards[1:] if c.kind == "character"]
    if not characters:
        return None
    for card in characters:  # slot 1 remains reserved, as configured by the macro
        if card.dracula is None:
            return None
        if not card.dracula:
            return card.number
    return 0


def hotbar_visible(win, cards):
    """Test only detected card/label pixels, not unused screen/frame margins."""
    if len(cards)<2:
        return False
    left=min(c.box[0] for c in cards)
    right=max(c.box[0]+c.box[2] for c in cards)
    top=min(c.box[1]-round(c.box[3]*.30) for c in cards)
    bottom=max(c.box[1]+c.box[3] for c in cards)
    ox,oy=int(win.w*MUTATION_REGION[0]),int(win.h*MUTATION_REGION[1])
    return region_visible(win, ((ox+left)/win.w,(oy+max(0,top))/win.h,
                                (ox+right)/win.w,(oy+bottom)/win.h))


def stable_hotbar(win, read_labels=True, failure_report=None):
    # Match two valid observations in a bounded sequence. An unreadable frame
    # contributes no vote; a readable contradictory state replaces the previous
    # observation. Never return cached cards in place of a fresh valid frame.
    previous = None
    for attempt in range(8):
        if attempt:
            sleep(.25)
        current, img = hotbar_snapshot(win, read_labels)
        visible = hotbar_visible(win, current)
        if failure_report is not None:
            failure_report.setdefault("frames", []).append((img.copy(), {
                "visible": visible, "slots": [
                    {"number": c.number, "box": c.box, "kind": c.kind,
                     "equipped": c.equipped, "dracula": c.dracula, "text": c.text}
                    for c in current]}))
        if not visible:
            continue
        if read_labels and choose_character(current) is None:
            continue
        if not read_labels and any(c.equipped and c.number >= 2 and c.kind == "unknown" for c in current):
            continue
        if previous is not None and len(previous) == len(current):
            same = True
            for a, b in zip(previous, current):
                ax, ay, aw, ah = a.box
                bx, by, bw, bh = b.box
                # Inner/outer borders can differ while representing the same
                # slot. Compare centers and scale, not identical contour edges.
                geometry = (abs(ax+aw/2-bx-bw/2) <= max(3, min(aw,bw)*.1)
                            and abs(ay+ah/2-by-bh/2) <= max(3, min(ah,bh)*.1)
                            and abs(aw-bw) <= max(aw,bw)*.2
                            and abs(ah-bh) <= max(ah,bh)*.2)
                if not (geometry and a.equipped == b.equipped and a.kind == b.kind
                        and (not read_labels or a.dracula == b.dracula)):
                    same = False
                    break
            if same:
                return current
        previous = current
    return None


def manual_fallback_state(win, want):
    states = getattr(_tl, "manual_fallback", {})
    state = states[win.hwnd]
    if state["equipped"] == bool(want):
        return "ok"
    focus(win)
    sleep(S["settle"] if want else min(S["settle"], .15))
    press_char(win, "manual fallback: equip" if want else "manual fallback: put away", key=state["key"])
    state["equipped"] = bool(want)
    UI.put(("state", win.slot, bool(want)))
    return "fixed"


def activate_manual_fallback(win, want):
    states = getattr(_tl, "manual_fallback", None)
    if states is None:
        states = _tl.manual_fallback = {}
    slot = getattr(_tl, "commanded_slots", {}).get(win.hwnd, 0)
    key = (SLOT_KEYS[slot-1] if 2 <= slot <= 10 else
           getattr(_tl, "last_character_keys", {}).get(win.hwnd, str(S["char_key"])))
    states[win.hwnd] = {"key": key, "equipped": slot >= 2}
    getattr(_tl, "hotbar_waits", {}).pop(win.hwnd, None)
    log(f"{win.name}: switching to manual fallback for this run (key {key}); hotbar checks disabled for this window")
    UI.put(("rotation", win.slot, f"Manual fallback • key {key}"))
    return manual_fallback_state(win, want)


def rotation_state(win, want, known_popup_state=None):
    """Equip/unequip an identified numbered card; never blindly toggle a guessed slot."""
    if win32gui.GetForegroundWindow() != win.hwnd:
        if not bring_to_front(win.hwnd):
            return "skipped"
        sleep(0.3)
    if (popup_state(win) if known_popup_state is None and want else known_popup_state):
        log(f"{win.name}: rotation paused while a popup covers the game")
        return "skipped"
    if win.hwnd in getattr(_tl, "manual_fallback", {}):
        return manual_fallback_state(win, want)
    # Putting away a confirmed selected character does not need its mutation.
    failure_report = {}
    cards = stable_hotbar(win, read_labels=want, failure_report=failure_report)
    target = choose_character(cards) if cards and want else (0 if cards else None)
    if target is None:
        frames = failure_report.get("frames", [])
        hidden = frames and all(not info["visible"] for _, info in frames)
        if getattr(_tl, "automation", False):
            # Catch animations temporarily replace the HUD. Defer this window
            # without sending input; other windows and the event detector run.
            waits = getattr(_tl, "hotbar_waits", None)
            if waits is None:
                waits = _tl.hotbar_waits = {}
            now = time.monotonic()
            pending = waits.get(win.hwnd)
            if pending is None:
                pending = waits[win.hwnd] = {"since": now, "slot": win.slot}
                log(f"{win.name}: scan uncertain; retrying for at least 40s before manual fallback")
            pending["attempts"] = pending.get("attempts", 0)+1
            if now-pending["since"] < 40 or pending["attempts"] < 3:
                pending["retry_at"] = now+2
                UI.put(("rotation", win.slot, "Scan uncertain • retrying"))
                return "skipped"
        log(f"{win.name}: hotbar/label uncertain; keeping current selection (use Test Dracula scan)")
        UI.put(("rotation", win.slot, "Unreadable • manual fallback"))
        if getattr(_tl, "automation", False):
            # Preserve the actual failed sequence, not a later successful scan.
            # Only this window's narrow hotbar strip is saved, locally.
            try:
                import zipfile
                path = os.path.join(APP_DIR, f"hotbar_failure_{win.slot+1}.zip")
                frames = failure_report.get("frames", [])
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    details = {"window": win.slot+1, "want_character": want,
                               "frame_rect": [win.left, win.top, win.right, win.bottom],
                               "frames": [info for _,info in frames]}
                    archive.writestr("readings.json", json.dumps(details, indent=2))
                    for i,(img,_) in enumerate(frames,1):
                        ok, encoded = cv2.imencode(".png", img)
                        if ok:
                            archive.writestr(f"frame_{i:02d}.png", encoded.tobytes())
                log(f"Failed scan sequence saved: {path}")
            except Exception as exc:
                log(f"Could not save failed scan sequence: {exc}")
            return activate_manual_fallback(win, want)
        return "skipped"
    waits = getattr(_tl, "hotbar_waits", {})
    if waits.pop(win.hwnd, None) is not None:
        log(f"{win.name}: hotbar restored; applying the current event state")
    publish_progress(win, cards)
    selected = [c.number for c in cards if c.equipped]
    if len(selected) > 1:
        return "skipped"
    current = selected[0] if selected else 0
    if not hasattr(_tl, "commanded_slots"):
        _tl.commanded_slots = {}
    last_command = _tl.commanded_slots.get(win.hwnd)
    if not want and current >= 2 and last_command == 0 and getattr(_tl, "automation", False):
        # A put-away command was already issued. An ambiguous stale highlight
        # must not cause a second toggle that equips the character again.
        return activate_manual_fallback(win, False)
    _tl.commanded_slots[win.hwnd] = current
    if target == 0:
        key_slot = current if any(c.number == current and c.number >= 2 and c.kind == "character" for c in cards) else None
        note = "All characters have Dracula" if want else "Event inactive"
    else:
        key_slot = target if current != target else None
        note = f"Slot {target} • hunting Dracula"
    UI.put(("rotation", win.slot, note))
    if key_slot is None:
        UI.put(("state", win.slot, current >= 2))
        return "ok"
    focus(win)
    sleep(S["settle"] if want else min(S["settle"], .15))
    before_press, _ = hotbar_snapshot(win, read_labels=False)
    if (not hotbar_visible(win, before_press) or len(before_press) != len(cards)
            or [c.number for c in before_press if c.equipped] != selected):
        log(f"{win.name}: hotbar changed while focusing; postponing the slot switch")
        return "skipped"
    press_char(win, f"{'select' if target else 'put away'} slot {key_slot}",
               key=SLOT_KEYS[key_slot - 1])
    _tl.commanded_slots[win.hwnd] = target
    if not hasattr(_tl, "last_character_keys"):
        _tl.last_character_keys = {}
    _tl.last_character_keys[win.hwnd] = SLOT_KEYS[key_slot-1]
    # Confirm the specific selected slot, not just any blue outline.
    end = time.monotonic() + 3.0
    while time.monotonic() < end:
        sleep(0.35)
        after, _ = hotbar_snapshot(win, read_labels=False)
        if len(after) != len(cards) or not hotbar_visible(win, after):
            break
        selected_after = [c.number for c in after if c.equipped]
        if selected_after == ([target] if target else []):
            for observed, previous in zip(after, cards):
                observed.dracula = previous.dracula
                observed.kind = previous.kind
            publish_progress(win, after)
            UI.put(("state", win.slot, bool(target)))
            return "fixed"
    log(f"{win.name}: couldn't confirm selected slot; will reread on the next pass")
    UI.put(("state", win.slot, None))
    if getattr(_tl, "automation", False):
        # A command already went out: do not toggle it again on an ambiguous
        # highlight. Keep tracking transitions without visual verification.
        return activate_manual_fallback(win, want)
    return "failed"


def job_test_dracula():
    """Read-only diagnostic: no slot switching, also saves the detected card boxes."""
    slots = scan_windows()
    if not slots:
        return
    for win in slots.all():
        focus(win)
        sleep(0.5)
        cards, img = hotbar_snapshot(win)
        raw_path = os.path.join(APP_DIR, f"hotbar_raw_{win.slot + 1}.png")
        cv2.imwrite(raw_path, img)
        detail_path = os.path.join(APP_DIR, f"hotbar_readings_{win.slot + 1}.json")
        with open(detail_path, "w", encoding="utf-8") as handle:
            json.dump({"window_width": win.w, "window_height": win.h,
                       "cards": [{"slot": c.number, "box": c.box, "kind": c.kind,
                                  "dracula": c.dracula, "text": c.text} for c in cards]}, handle, indent=2)
        img = img.copy()  # annotation must never overwrite the raw capture
        target = choose_character(cards)
        if target is not None:
            publish_progress(win, cards)
        publish_preview(f"hotbar_{win.slot}", img, f"{win.name} • diagnostic scan")
        log(f"{win.name}: {len(cards)} hotbar cards; " +
            ("uncertain" if target is None else (f"next slot {target}" if target else "all Dracula")))
        for card in cards:
            x, y, w, h = card.box
            cv2.rectangle(img, (x, y), (x + w, y + h), (255, 210, 0), 1)
            cv2.putText(img, str(card.number), (x + 2, y + 15), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (255, 255, 255), 1)
            if card.number >= 2:
                if card.kind != "character":
                    log(f"  slot {card.number}: " + ("item; excluded from rotation" if card.kind == "item"
                                                     else "UNKNOWN card type; scan remains uncertain"))
                    continue
                status = "DRACULA" if card.dracula else ("not Dracula" if card.dracula is False else "unknown")
                log(f"  slot {card.number}: {status}; OCR: {card.text!r}")
        path = os.path.join(APP_DIR, f"hotbar_debug_{win.slot + 1}.png")
        cv2.imwrite(path, img)
        log(f"  Hotbar diagnostic saved: {path}")
        log(f"  Raw capture and slot readings saved: {raw_path}; {detail_path}")
    main = slots.win(0)
    if main:
        bring_to_front(main.hwnd)


def press_char(win, label, key=None):
    """Make sure this window has focus, then press the character key exactly once."""
    for _ in range(3):
        if win32gui.GetForegroundWindow() == win.hwnd:
            break
        log(f"  {win.name}: not focused yet (focus is on '{foreground_title()}'), trying again")
        focus(win)
        sleep(1.0)
    check_stop()
    if win32gui.GetForegroundWindow() != win.hwnd:
        raise RuntimeError(f"{win.name}: key press skipped because focus was not acquired")
    key = key or S["char_key"]
    tap_key(key)
    log(f"  {win.name}: {label} (pressed {key} once)")


def equip_character(win):
    if getattr(_tl, "automation", False) and not SHARED["want"]:
        return "skipped"
    if S["dracula_rotation"]:
        return rotation_state(win, True)
    focus(win)
    sleep(S["settle"])
    press_char(win, "equip character")
    sleep(STEP_DELAY)


def unequip_character(win):
    if getattr(_tl, "automation", False):
        fallback = getattr(_tl, "manual_fallback", {}).get(win.hwnd)
        if fallback is not None:
            return manual_fallback_state(win, False)
        slot = getattr(_tl, "commanded_slots", {}).get(win.hwnd)
        if slot == 0:
            return "ok"
        if slot is not None and slot >= 2:
            if not bring_to_front(win.hwnd):
                return "skipped"
            sleep(.15)
            press_char(win, f"fast put away slot {slot}", key=SLOT_KEYS[slot-1])
            _tl.commanded_slots[win.hwnd] = 0
            if not hasattr(_tl, "last_character_keys"):
                _tl.last_character_keys = {}
            _tl.last_character_keys[win.hwnd] = SLOT_KEYS[slot-1]
            UI.put(("state", win.slot, False))
            return "fixed"
    if S["dracula_rotation"]:
        return rotation_state(win, False)
    focus(win)
    sleep(S["settle"])
    press_char(win, "unequip character")
    sleep(STEP_DELAY)


def run_on_all(slots, fn):
    origin = pyautogui.position()
    try:
        for w in slots.all():
            fn(w)
    finally:
        if not STOP.is_set():
            restore_main(slots)
        pyautogui.moveTo(origin.x, origin.y)


def wait_for_state(win, want, timeout=3.0):
    """Poll the hotbar until it shows the wanted state (the highlight can lag a moment)."""
    end = time.time() + timeout
    while True:
        if character_equipped(win) == want:
            return True
        if time.time() >= end:
            return False
        sleep(0.5)


def ensure_state(win, want, known_popup_state=None):
    """
    Look at the window's hotbar; if the character is equipped/unequipped the wrong way round,
    press the key to fix it (at most 2 presses, each confirmed by looking again).
    Returns 'ok', 'fixed', 'failed' or 'skipped'.
    """
    if S["dracula_rotation"]:
        return rotation_state(win, want, known_popup_state)
    bring_to_front(win.hwnd)
    sleep(0.4)
    state = popup_state(win) if known_popup_state is None else known_popup_state
    if state:  # popup hides the hotbar, so the state can't be read
        log(f"  {win.name}: Welcome Back popup is open, skipping the character check")
        return "skipped"
    cur = character_equipped(win)
    sleep(0.4)
    if character_equipped(win) != cur:  # unstable read (animation) - try again next pass
        return "skipped"
    UI.put(("state", win.slot, cur))
    if cur == want:
        return "ok"
    log(f"  {win.name}: character is {'EQUIPPED' if cur else 'NOT equipped'} but should be "
        f"{'equipped' if want else 'unequipped'} -> fixing")
    for _ in range(2):
        focus(win)
        sleep(S["settle"])
        press_char(win, "fixing")
        if wait_for_state(win, want):
            log(f"  {win.name}: fixed")
            UI.put(("state", win.slot, want))
            return "fixed"
    log(f"  {win.name}: couldn't confirm the fix - please check this window by hand")
    UI.put(("state", win.slot, None))
    return "failed"


def verify_all(slots, want):
    origin = pyautogui.position()
    results = []
    for i in range(len(slots)):
        w = slots.win(i)
        if w is not None:
            results.append(ensure_state(w, want))
    pyautogui.moveTo(origin.x, origin.y)
    log("Character check: " + (", ".join(results) if results else "no windows"))
    return results


def close_welcome_popup(win):
    focus(win)
    click_ratio(win, WELCOME_CLOSE)


def click_abs(win, x, y, hold=0.1):
    """Click a screen point. First makes sure no other window is on top of it."""
    for _ in range(3):
        owner = _root_at(x, y)
        if owner == win.hwnd:
            break
        try:
            who = win32gui.GetWindowText(owner) or hex(owner)
        except Exception:
            who = hex(owner)
        log(f"  {win.name}: another window ('{who}') is covering the click spot, raising this one again")
        bring_to_front(win.hwnd)
        sleep(0.5)
    else:
        raise RuntimeError(f"{win.name}: click skipped because another window covers the spot")
    hover_click(x, y, hold)
    sleep(0.4)


def click_ratio(win, ratio, hold=0.1):
    click_abs(win, win.left + int(win.w * ratio[0]), win.top + int(win.h * ratio[1]), hold)


def save_rebirth_debug(win, note):
    """Save a screenshot of the window with the rebirth-icon click spot marked, plus what OCR read."""
    try:
        folder = os.path.join(APP_DIR, "rebirth_debug")
        os.makedirs(folder, exist_ok=True)
        img = grab(win, (0, 0, 1, 1)).copy()
        cx, cy = int(win.w * REBIRTH_ICON[0]), int(win.h * REBIRTH_ICON[1])
        cv2.circle(img, (cx, cy), 14, (0, 0, 255), 3)
        path = os.path.join(folder, f"rebirth_{win.slot + 1}_{time.strftime('%H%M%S')}.png")
        cv2.imwrite(path, img)
        text = " ".join(read_text(grab(win, MENU_REGION), scale=2, n=2).split())[:90]
        log(f"  {win.name}: {note} | click spot ({win.left + cx},{win.top + cy}) | menu text read: {text!r}")
        log(f"  saved a screenshot with the click spot circled in red: {path}")
    except Exception as e:
        log(f"  (couldn't save debug image: {e})")


def robux_close_point(win):
    """
    Find the X of the Robux prompt on screen. Its height depends on the prompt, but the X is always on
    the same row as the 'Buy ...' title and a fixed distance (ROBUX_X_OFFSET * window width) to its
    right. We locate the topmost word 'Buy' (the title; the Buy button is lower down) with OCR.
    Returns (x, y) in screen pixels, or None.
    """
    scale = 2
    img = grab(win, POPUP_REGION)
    ox = win.left + int(win.w * POPUP_REGION[0])
    oy = win.top + int(win.h * POPUP_REGION[1])
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    for variant in (gray, 255 - gray):
        d = ocr(variant, data=True)
        best = None
        for i, t in enumerate(d["text"]):
            t2 = re.sub(r"[^a-z]", "", t.lower())
            if t2 == "buy" and (best is None or d["top"][i] < best[1]):
                best = (d["left"][i], d["top"][i], d["height"][i])
        if best:
            left, top, height = best
            return int(ox + left / scale + ROBUX_X_OFFSET * win.w), int(oy + (top + height / 2) / scale)
    return None


def close_robux_popup(win):
    """Close the Roblox purchase prompt with its X. Never clicks Buy. Returns True if it closed."""
    for attempt in range(4):
        pt = robux_close_point(win)
        if pt is None:  # couldn't read the title: try the known X spots in turn
            r = ROBUX_CLOSE_SPOTS[attempt % len(ROBUX_CLOSE_SPOTS)]
            pt = (win.left + int(win.w * r[0]), win.top + int(win.h * r[1]))
        log(f"{win.name}: Robux purchase prompt -> closing it with the X (try {attempt + 1}/4)")
        if attempt:
            focus(win)
        click_abs(win, pt[0], pt[1])
        sleep(1.0)
        if "robux" not in popup_state(win):
            return True
    log(f"{win.name}: WARNING - couldn't close the Robux prompt, please close it by hand!")
    return False


def watch_for_robux(win, seconds):
    """The prompt can show up a bit late (lag): keep looking for a while and close it if it appears."""
    end = time.time() + seconds
    closed = False
    while time.time() < end:
        if "robux" in popup_state(win):
            close_robux_popup(win)
            closed = True
            end = max(end, time.time() + 3)  # keep watching a little longer in case of a second one
        else:
            sleep(0.7)
    return closed


def do_rebirth(win):
    """Open the rebirth menu, click the green Rebirth! button, close any Robux prompt, close the menu."""
    name = win.name
    log(f"{name}: rebirth attempt")
    focus(win)
    sleep(0.5)
    st = popup_state(win)
    if "robux" in st:
        close_robux_popup(win)
    if "welcome" in st:
        close_welcome_popup(win)
    if not rebirth_menu_open(win):
        opened = False
        for attempt in range(3):  # normal click, then a slower click with a hover nudge, then again
            focus(win)
            click_ratio(win, REBIRTH_ICON, hold=0.1 if attempt == 0 else 0.18)
            sleep(1.5)
            if rebirth_menu_open(win):
                opened = True
                break
            log(f"{name}: rebirth menu didn't open (try {attempt + 1}/3)")
        if not opened:
            log(f"{name}: couldn't open the Rebirth menu - skipping this attempt")
            save_rebirth_debug(win, "menu not detected")
            if "robux" in popup_state(win):
                close_robux_popup(win)
            return False
    click_ratio(win, REBIRTH_BUTTON)   # the GREEN Rebirth! button only
    log(f"{name}: Rebirth! clicked - watching for a Robux prompt (it can appear late)")
    if watch_for_robux(win, 7.0):
        log(f"{name}: closed the Robux prompt (not enough cash to rebirth yet)")
    sleep(0.5)
    if rebirth_menu_open(win):
        click_ratio(win, REBIRTH_MENU_CLOSE)
        sleep(0.6)
    watch_for_robux(win, 4.0)          # one more look in case a prompt lags in after the menu closed
    return True


def afk_click(win):
    x = win.left + int(win.w * AFK_CLICK_SPOT[0])
    y = win.top + int(win.h * AFK_CLICK_SPOT[1])
    hover_click(x, y)
    sleep(0.2)


def check_window(slots, i, last_afk, force_afk=False):
    """Bring window i to the front; close a Robux prompt (always) and the Welcome Back popup (if
    enabled); do the anti-AFK click if due."""
    w = slots.win(i)
    if w is None:
        return
    bring_to_front(w.hwnd)
    sleep(0.3)
    w = slots.win(i)
    if w is None:
        return
    state = popup_state(w)
    if "robux" in state:
        close_robux_popup(w)
    if S["close_popup"] and "welcome" in state:
        log(f"{w.name}: Welcome Back popup -> closing it")
        close_welcome_popup(w)
        sleep(0.5)
    if (S["afk_enabled"] or force_afk) and (force_afk or time.time() - last_afk[i] >= S["afk_minutes"] * 60):
        afk_click(w)
        last_afk[i] = time.time()
        return None  # input may have changed the UI; verification must read again
    # Only reuse a clear read when no popup was acted on and no game input followed it.
    return state if not state else None


def maintenance(slots, last_afk, force_afk=False, want=None):
    """One pass: popup close, anti-AFK click, and (if want is True/False) character state check."""
    origin = pyautogui.position()
    for i in range(len(slots)):
        state = check_window(slots, i, last_afk, force_afk)
        if want is not None and (S["verify_state"] or S["dracula_rotation"]):
            w = slots.win(i)
            if w is not None:
                ensure_state(w, want, known_popup_state=state)
    main = slots.win(0)
    if main is not None:
        bring_to_front(main.hwnd)  # keep the main window's banner visible
    pyautogui.moveTo(origin.x, origin.y)


# ----------------------------------------------------------------------------
# Jobs (run in a background thread so the window never freezes)
# ----------------------------------------------------------------------------
EVENT_TEMPLATE_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAGYAAAATCAAAAABHWyfMAAABDUlEQVQ4Eb3BWXbbWABEMdz9L7rCR1HOcNzpfAnIvxvyq+WYX4Tld/l3Q76xfFm+kf80mXwZ8o3lf+QYYeRtNPK2Rn43wjzyrRwjjLyNRv5qhHnksvwhxwgjb6ORvxphHrksf8gxxIg5Go1c5pKR0WgeYchlhNEcOXLMW+bWaIS5NTKatybMS0PMl1xyzFvz0miEeWlujUZYLvOSkfkplxzz1shoNGLEaL40l7zMLYZGQyOXHCOMRkajESNG5hFzyW3kZW7NSy45RhgZjUYmjIzMI9PIbeQxl8wtR44RRubWPDK3GBoxR27ziCHmliPHCCPmyGiIueQyGTFHbvMII8yRIx+Rj8hH5CPyET8Ar8yHFP+I4OgAAAAASUVORK5CYII='

class RecoveryRequired(StopMacro):
    pass


RECOVERY = {"reason": ""}
PROGRESS = {}
PREVIEW = {}
DATA_LOCK = threading.Lock()


def safety_pause(reason):
    with DATA_LOCK:
        first = not RECOVERY["reason"]
        RECOVERY["reason"] = reason
    if first:
        log("PAUSED: " + reason + " Fix the issue, then choose Resume / recheck.")
        UI.put(("recovery", reason))
    STOP.set()


def publish_preview(key, img, status):
    with DATA_LOCK:
        PREVIEW[key] = (img.copy() if img is not None else None, status, time.monotonic())


def passive_window(slots, i):
    # Observation must never restore or focus a window behind the action worker.
    h = slots.hwnds[i]
    if not h or not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h):
        return None
    if win32gui.GetWindowText(h) != "Roblox" or win32gui.IsIconic(h):
        return None
    return Win(h, *_frame_rect(h), i)


def region_owners(win, region):
    # DWM rectangles and screenshot crops have exclusive right/bottom edges.
    # Sampling bottom == win.bottom accidentally tests the window underneath.
    x1, y1, x2, y2 = region
    left, right = int(win.w*x1), int(win.w*x2)-1
    top, bottom = int(win.h*y1), int(win.h*y2)-1
    return {_root_at(win.left+x, win.top+y)
            for x in (left,(left+right)//2,right) for y in (top,(top+bottom)//2,bottom)}


def region_visible(win, region):
    return region_owners(win, region) == {win.hwnd}


def tracked_overlap(win, region, slots):
    """A valid tracked Roblox window covers this region, not another desktop app."""
    owners = region_owners(win, region)
    return bool(owners - {win.hwnd}) and owners.issubset(set(slots.hwnds))


def reveal_for_scan(slots, i):
    """Only the action/setup worker owns focus. Background watchers never steal it."""
    for attempt in range(3):
        win = passive_window(slots, i)
        if win is None:
            return None
        if bring_to_front(win.hwnd):
            sleep(.30)
            win = passive_window(slots, i)
            if win and win32gui.GetForegroundWindow()==win.hwnd:
                return win
        sleep(.15)
    return None


def restore_main(slots):
    win = passive_window(slots, 0)
    if win is not None:
        bring_to_front(win.hwnd)


def title_mask(img):
    return cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2HSV),
                       np.array([5, 140, 160]), np.array([35, 255, 255]))


class BannerMatcher:
    def __init__(self):
        import base64
        raw = np.frombuffer(base64.b64decode(EVENT_TEMPLATE_PNG), np.uint8)
        template = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        self.templates = [cv2.resize(template, None, fx=float(s), fy=float(s),
                          interpolation=cv2.INTER_LINEAR)
                          for s in np.concatenate((np.arange(0.60, 1.0, 0.02), np.arange(1.0, 1.81, 0.04)))]
        self.last_match = None

    def score(self, img):
        mask = title_mask(img)
        best = 0.0
        if self.last_match is not None:
            t = self.last_match
            if t.shape[0] <= mask.shape[0] and t.shape[1] <= mask.shape[1]:
                score = float(cv2.minMaxLoc(cv2.matchTemplate(mask, t, cv2.TM_CCOEFF_NORMED))[1])
                if score >= 0.78:
                    return score
        for t in self.templates:
            if t.shape[0] <= mask.shape[0] and t.shape[1] <= mask.shape[1]:
                score = float(cv2.minMaxLoc(cv2.matchTemplate(mask, t, cv2.TM_CCOEFF_NORMED))[1])
                best = max(best, score)
                if score >= 0.78:
                    self.last_match = t
                    return score
        return best


class EventDebouncer:
    """Monotonic timing; unknown frames break confirmation, but retain the verdict."""
    def __init__(self):
        self.active = False
        self.candidate = None
        self.since = 0.0

    def update(self, present, now, start_delay=0.20, end_delay=0.45):
        if present is None or present == self.active:
            self.candidate = None
            return False
        if self.candidate != present:
            self.candidate, self.since = present, now
            return False
        if now - self.since >= (start_delay if present else end_delay):
            self.active = present
            self.candidate = None
            return True
        return False


WEBHOOK_QUEUE = queue.Queue(maxsize=100)
WEBHOOK_LOCK = threading.Lock()
WEBHOOK_WORKER = None
DRACULA_NOTIFIED = set()


def webhook_worker():
    from urllib.request import Request, urlopen
    while True:
        url, message = WEBHOOK_QUEUE.get()
        try:
            body = json.dumps({"content": message, "allowed_mentions": {"parse": []}}).encode("utf-8")
            request = Request(url, data=body, headers={"Content-Type": "application/json",
                                                     "User-Agent": "HallowsMacro/2.9"}, method="POST")
            with urlopen(request, timeout=5) as response:
                response.read(1024)
            log("Webhook notification delivered")
        except Exception as exc:
            # Webhook URLs contain credentials. Do not log exception text/URL.
            log(f"Webhook delivery failed ({type(exc).__name__}); macro continues")
        finally:
            WEBHOOK_QUEUE.task_done()


def notify_webhook(kind, message):
    global WEBHOOK_WORKER
    from urllib.parse import urlsplit
    if not S.get("webhook_"+kind):
        return
    url = S.get("webhook_url", "").strip()
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
    except ValueError:
        log("Webhook not sent: configure a valid HTTPS webhook URL in Automation")
        return
    with WEBHOOK_LOCK:
        if WEBHOOK_WORKER is None or not WEBHOOK_WORKER.is_alive():
            WEBHOOK_WORKER = threading.Thread(target=webhook_worker, daemon=True, name="Webhook delivery")
            WEBHOOK_WORKER.start()
    try:
        WEBHOOK_QUEUE.put_nowait((url, message))
    except queue.Full:
        log("Webhook queue full; notification skipped, macro continues")


def publish_progress(win, cards):
    info = {"slots": [{"slot": c.number, "dracula": c.dracula, "selected": c.equipped}
                       for c in cards[1:] if c.kind == "character"],
            "selected": next((c.number for c in cards if c.equipped), 0),
            "complete": choose_character(cards) == 0, "at": time.monotonic()}
    with DATA_LOCK:
        PROGRESS[win.slot] = info
        alerts = []
        if getattr(_tl, "automation", False) and S.get("webhook_dracula"):
            for card in cards[1:]:
                key = (win.hwnd, card.number)
                if card.kind == "character" and card.dracula is True and key not in DRACULA_NOTIFIED:
                    DRACULA_NOTIFIED.add(key)
                    alerts.append(f"Dracula confirmed — {win.name}, character slot {card.number}.")
    for message in alerts:
        notify_webhook("dracula", message)
    UI.put(("progress", win.slot, info))


def all_complete(count, now):
    with DATA_LOCK:
        return count > 0 and all(i in PROGRESS and PROGRESS[i]["complete"]
                                and now - PROGRESS[i]["at"] < 45 for i in range(count))


def validate_runtime_start(slots):
    """A resumed run must pass fresh checks before any game input is sent."""
    try:
        return validate_visible_windows(slots)
    finally:
        restore_main(slots)


def validate_visible_windows(slots):
    for i in range(len(slots)):
        win = reveal_for_scan(slots, i)
        if not win:
            safety_pause(f"Window {i+1}: could not bring Roblox forward. Close blocking dialogs and retry.")
            return False
        text = read_text(grab(win, POPUP_REGION), scale=1, n=1).lower() if region_visible(win, POPUP_REGION) else ""
        if any(p in text for p in ("disconnected", "connection lost", "same account launched", "error code: 277", "error code: 279")):
            safety_pause(f"Window {i+1}: reconnect Roblox before resuming.")
            return False
        if S["dracula_rotation"]:
            report = {}
            cards = stable_hotbar(win, failure_report=report)
            if cards is None or choose_character(cards) is None:
                frames = report.get("frames", [])
                if frames:
                    waits = getattr(_tl, "hotbar_waits", None)
                    if waits is None:
                        waits = _tl.hotbar_waits = {}
                    now = time.monotonic()
                    waits[win.hwnd] = {"since": now, "slot": win.slot, "retry_at": now+2}
                    log(f"{win.name}: startup scan uncertain; retrying before manual fallback")
                    continue
                safety_pause(f"Window {i+1}: hotbar or mutation unconfirmed. Run Dracula scan for slot details.")
                return False
            publish_progress(win, cards)
            if not hasattr(_tl, "commanded_slots"):
                _tl.commanded_slots = {}
            _tl.commanded_slots[win.hwnd] = next((c.number for c in cards if c.equipped), 0)
    return True


class SafetyMonitor(threading.Thread):
    """Independent health checks; never clicks or brings a window to the front."""
    def __init__(self, slots):
        super().__init__(daemon=True)
        self.slots, self.stop = slots, threading.Event()

    def run(self):
        _tl.stop = self.stop
        missing = {}
        ocr_due = {}
        try:
            while not STOP.is_set() and not self.stop.is_set():
                for i in range(len(self.slots)):
                    check_stop()
                    win = passive_window(self.slots, i)
                    if win is None:
                        safety_pause(f"Window {i+1} closed, minimized or unavailable.")
                        return
                    cards, img = hotbar_snapshot(win, read_labels=False)
                    visible=hotbar_visible(win,cards)
                    publish_preview(f"hotbar_{i}", img if visible else None,
                                    f"Window {i+1} • {len(cards)} visible slots" if visible else
                                    f"Window {i+1} • covered/unconfirmed; awaiting focused scan")
                    now = time.monotonic()
                    if not visible and S["dracula_rotation"] and SHARED.get("menu_window") != i:
                        if now-missing.get(i, -100) >= 20:
                            log(f"{win.name}: background hotbar unconfirmed; will recheck when focused.")
                            missing[i]=now
                    else:
                        missing.pop(i, None)
                    if now >= ocr_due.get(i, 0) and region_visible(win, POPUP_REGION):
                        text = read_text(grab(win, POPUP_REGION), scale=1, n=1).lower()
                        ocr_due[i] = time.monotonic() + 4
                        if not region_visible(win, POPUP_REGION):
                            continue
                        if any(phrase in text for phrase in ("disconnected", "connection lost", "same account launched", "error code: 277", "error code: 279")):
                            safety_pause(f"{win.name}: Roblox connection warning detected.")
                            return
                self.stop.wait(0.5)
        except StopMacro:
            pass
        except Exception as exc:
            safety_pause(f"Health check failed: {type(exc).__name__}: {exc}")
        finally:
            close_capture()


def job_live_preview():
    slots = scan_windows(passive=True)
    if not slots:
        return
    matcher = BannerMatcher()
    while True:
        check_stop()
        win = passive_window(slots, 0)
        if win and region_visible(win, EVENT_REGION):
            img = grab(win, EVENT_REGION)
            score = matcher.score(img)
            publish_preview("banner", img, f"Read-only preview • title match {score:.0%} (not an event verdict)")
        else:
            publish_preview("banner", None, "Unable to read • uncover the main window")
        for i in range(len(slots)):
            w = passive_window(slots, i)
            if w:
                cards, img = hotbar_snapshot(w, read_labels=False)
                visible=hotbar_visible(w,cards)
                publish_preview(f"hotbar_{i}", img if visible else None,
                                f"Window {i+1} • {len(cards)} visible slots" if visible else
                                f"Window {i+1} • covered or unconfirmed")
        sleep(0.30)


def job_preflight():
    def report(step, good, detail):
        UI.put(("setup_check", step, good, detail))
        log(f"Setup {step}: {'PASS' if good else 'CHECK'} • {detail}")
    try:
        command = pytesseract.pytesseract.tesseract_cmd
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run([command, "--version"], capture_output=True, text=True,
                                timeout=OCR_TIMEOUT, creationflags=flags)
        check_stop()
        version = result.stdout.splitlines()[0] if result.stdout else "unknown"
        languages = subprocess.run([command, "--list-langs"], capture_output=True, text=True,
                                   timeout=OCR_TIMEOUT, creationflags=flags)
        check_stop()
        good = result.returncode == 0 and languages.returncode == 0 and "eng" in languages.stdout.split()
        report(0, good, f"Dependencies loaded; Tesseract {version}; English {'ready' if good else 'missing'}")
        if not good:
            return
        slots = scan_windows(passive=True)
        report(1, bool(slots), f"{len(slots) if slots else 0} Roblox windows found. Checking each in front; close game popups.")
        if not slots:
            return
        w = reveal_for_scan(slots, 0)
        if w is None or not region_visible(w, EVENT_REGION):
            report(2, False, "Uncover the main window's banner and rerun checks.")
            return
        img = grab(w, EVENT_REGION)
        score = BannerMatcher().score(img)
        present, text, _ = read_event(w)
        publish_preview("banner", img, f"Setup • title match {score:.0%}")
        report(2, True, (f"Event visible; visual match {score:.0%}." if present else
                        "Banner capture works. No event confirmed; validate again during an event."))
        ok = True
        for i in range(len(slots)):
            win = reveal_for_scan(slots, i)
            if not win:
                report(3, False, f"Window {i+1}: could not bring Roblox forward; close blocking dialogs and retry.")
                return
            cards = stable_hotbar(win)
            valid = cards is not None and choose_character(cards) is not None
            ok = ok and valid
            if valid:
                publish_progress(win, cards)
            else:
                detail = "hotbar missing, covered or changing" if cards is None else (
                    "unconfirmed item type in slot(s) " + ", ".join(str(c.number) for c in cards[1:] if c.kind == "unknown")
                    if any(c.kind == "unknown" for c in cards[1:]) else "mutation label unreadable or no character from slot 2 onward")
                log(f"Setup hotbar: window {i+1} • {detail}")
        report(3, ok, "All hotbars readable. Start when ready." if ok else "A hotbar or label was uncertain; check the live preview.")
        if ok:
            UI.put(("setup_done",))
    except StopMacro:
        raise
    except Exception as exc:
        report(0, False, str(exc))
    finally:
        UI.put(("setup_finished", bool(locals().get("ok", False))))
        if "slots" in locals() and slots:
            restore_main(slots)


class Detector(threading.Thread):
    def __init__(self, slots):
        super().__init__(daemon=True)
        self.slots, self.stop = slots, threading.Event()
        self.changed_at = 0.0
        self.ocr_requests = queue.Queue(maxsize=1)
        self.ocr_results = queue.Queue(maxsize=1)

    def fallback_worker(self):
        _tl.stop = self.stop
        try:
            while not STOP.is_set() and not self.stop.is_set():
                try:
                    self.ocr_requests.get(timeout=0.1)
                except queue.Empty:
                    continue
                win = passive_window(self.slots, 0)
                if win is None or not region_visible(win, EVENT_REGION):
                    continue
                present = read_event(win)[0]
                current = passive_window(self.slots, 0)
                if current is None or (current.left, current.top, current.w, current.h) != (win.left, win.top, win.w, win.h):
                    continue
                if region_visible(current, EVENT_REGION):
                    try:
                        self.ocr_results.get_nowait()
                    except queue.Empty:
                        pass
                    self.ocr_results.put_nowait((time.monotonic(), present))
        except StopMacro:
            pass
        except Exception as exc:
            safety_pause(f"OCR fallback failed: {exc}")
        finally:
            close_capture()

    def run(self):
        _tl.stop = self.stop
        fallback = threading.Thread(target=self.fallback_worker, daemon=True)
        fallback.start()
        try:
            self.detect()
        except StopMacro:
            pass
        except Exception as exc:
            safety_pause(f"Event detector failed: {type(exc).__name__}: {exc}")
        finally:
            self.stop.set()
            fallback.join()
            close_capture()

    def detect(self):
        matcher, state = BannerMatcher(), EventDebouncer()
        fast = S.get("fast_detection", True)
        fallback_due = 0.0
        active_since = None
        unknown_since = None
        while not STOP.is_set() and not self.stop.is_set():
            started = time.monotonic()
            win = passive_window(self.slots, 0)
            if win is None:
                safety_pause("Main Roblox window unavailable.")
                return
            if not region_visible(win, EVENT_REGION):
                state.update(None, started)
                publish_preview("banner", None, "Unable to read • banner covered; previous verdict retained")
                if tracked_overlap(win, EVENT_REGION, self.slots):
                    # The worker will bring the main window back when its pass ends.
                    # Do not turn normal Roblox overlap into a timed failure.
                    unknown_since = None
                    self.stop.wait(.1)
                    continue
                unknown_since = unknown_since if unknown_since is not None else started
                if started - unknown_since > 15:
                    safety_pause("Main event banner covered for 15 seconds. Arrange windows so it stays visible.")
                    return
                self.stop.wait(0.1)
                continue
            img = grab(win, EVENT_REGION)
            if not region_visible(win, EVENT_REGION):
                state.update(None, time.monotonic())
                self.stop.wait(POLL_SECONDS)
                continue
            score = matcher.score(img) if fast else 0.0
            present = (True if score >= 0.78 else False if score < 0.58 else None) if fast else None
            # OCR runs on a separate worker so idle compatibility checks cannot stall
            # the visual loop. An incompatible title uses OCR for this whole session.
            if fast:
                if time.monotonic() >= fallback_due and (present is None or (not state.active and present is False)):
                    try:
                        self.ocr_requests.put_nowait(True)
                    except queue.Full:
                        pass
                    fallback_due = time.monotonic() + 8
                try:
                    at, detected = self.ocr_results.get_nowait()
                    if detected and time.monotonic() - at < 1.5 and score < 0.78:
                        fast, present = False, True
                        log("Banner layout differs from the reference; using slower OCR for this session.")
                except queue.Empty:
                    pass
            else:
                present = read_event(win)[0]
            now = time.monotonic()
            if present is None:
                unknown_since = unknown_since if unknown_since is not None else now
                if now - unknown_since > 15:
                    safety_pause("Event banner remained ambiguous for 15 seconds. Run guided setup.")
                    return
            else:
                unknown_since = None
            changed = state.update(present, now, .20 if fast else .4, .45 if fast else 3.0)
            if changed:
                self.changed_at = time.time()
                SHARED["want"] = state.active
                active_since = now if state.active else None
                log(f"Event {'started' if state.active else 'ended'} • {'visual' if fast else 'OCR'} detector")
                if state.active:
                    notify_webhook("events", "Hallows’ Eve detected — event started.")
            if active_since is not None and now - active_since > MAX_HOLD_SECONDS:
                safety_pause("Event exceeded the maximum watch time; verify the game before resuming.")
                return
            status = "Unable to read" if present is None else "Event active" if state.active else "Inactive"
            publish_preview("banner", img, f"{status} • {'visual' if fast else 'OCR fallback'} • match {score:.0%}")
            self.stop.wait(max(.01, (POLL_SECONDS if fast else .4) - (time.monotonic() - started)))


def retry_hidden_hotbars(slots):
    waits = getattr(_tl, "hotbar_waits", {})
    due = [(hwnd, pending["slot"]) for hwnd, pending in list(waits.items())
           if time.monotonic() >= pending.get("retry_at", 0)]
    if not due:
        return
    try:
        for hwnd, slot in due:
            check_stop()
            win = slots.win(slot)
            if win is None or win.hwnd != hwnd:
                waits.pop(hwnd, None)
                continue
            # Rate-limit even when a popup prevents rotation_state's scan.
            if hwnd in waits:
                waits[hwnd]["retry_at"] = time.monotonic()+2
            rotation_state(win, SHARED["want"])
    finally:
        restore_main(slots)


def job_macro():
    slots = scan_windows(passive=True)
    if not slots:
        return
    _tl.automation = True
    _tl.hotbar_waits = {}
    _tl.manual_fallback = {}
    _tl.commanded_slots = {}
    _tl.last_character_keys = {}
    with DATA_LOCK:
        PROGRESS.clear()
        DRACULA_NOTIFIED.clear()
    if not validate_runtime_start(slots):
        _tl.automation = False
        return
    SHARED["want"] = SHARED["holding"] = False
    det = Detector(slots)
    health = SafetyMonitor(slots)
    health.start()
    det.start()
    log("Macro started. Watching the main window for Hallows' Eve (visual detection with OCR fallback).")
    last_maint = 0.0
    last_afk = [0.0] * len(slots)
    next_rebirth = [0.0] * len(slots)
    try:
        while True:
            check_stop()
            try:
                if (S.get("stop_when_complete") and S["dracula_rotation"]
                        and not _tl.manual_fallback and all_complete(len(slots), time.monotonic())):
                    log("All tracked characters have Dracula. Session complete.")
                    if SHARED["holding"]:
                        UI.put(("event_end", time.time(), True))
                    UI.put(("complete",))
                    break
                # 1) Event start/end comes first and is never delayed by the chores below.
                if SHARED["want"] != SHARED["holding"]:
                    if SHARED["want"]:
                        log("*** Hallows' Eve detected -> equipping characters ***")
                        SHARED["holding"] = True
                        UI.put(("event_start", det.changed_at))
                        with preemptible():
                            run_on_all(slots, equip_character)
                        if S["verify_state"] and not S["dracula_rotation"]:
                            with preemptible():
                                verify_all(slots, True)
                    else:
                        log("*** Hallows' Eve over -> unequipping characters ***")
                        SHARED["holding"] = False
                        UI.put(("event_end", det.changed_at, False))
                        run_on_all(slots, unequip_character)
                        if S["verify_state"] and not S["dracula_rotation"]:
                            with preemptible():
                                verify_all(slots, False)
                    continue  # look again straight away in case it flipped while we were busy

                # Retry animation-covered windows independently of the slower
                # maintenance cycle, using the latest desired event state.
                if S["dracula_rotation"]:
                    with preemptible():
                        retry_hidden_hotbars(slots)

                # 2) Chores. Each one can be interrupted the moment the event starts or ends.
                now = time.time()
                if now - last_maint >= MAINTENANCE_SECONDS:
                    last_maint = now
                    with preemptible():
                        maintenance(slots, last_afk, want=SHARED["holding"])

                due = [i for i in range(len(slots))
                       if S["rebirth"][i] and time.time() >= next_rebirth[i]]
                if due:
                    with preemptible():
                        origin = pyautogui.position()
                        for i in due:
                            w = slots.win(i)
                            if w is not None:
                                SHARED["menu_window"] = i
                                try:
                                    do_rebirth(w)
                                finally:
                                    SHARED["menu_window"] = None
                            next_rebirth[i] = time.time() + S["rebirth_seconds"]
                        mw = slots.win(0)
                        if mw is not None:
                            bring_to_front(mw.hwnd)
                        pyautogui.moveTo(origin.x, origin.y)
            except Preempt:
                last_maint = 0.0  # redo the interrupted pass once the event has been handled
                continue
            except StopMacro:
                raise
            except pytesseract.TesseractNotFoundError:
                raise
            except Exception as e:  # one hiccup must not kill an overnight run
                log(f"[error] {type(e).__name__}: {e} -- continuing")
                sleep(5)
            sleep(0.2)
    except StopMacro:
        if SHARED["holding"]:
            UI.put(("event_end", time.time(), True))
            if S["dracula_rotation"]:
                log("Stopped during the event. Equipment was left unchanged. Check each window's "
                    "highlighted slot before putting characters away manually.")
            else:
                log(f"Stopped while characters are equipped - press {S['char_key']} in each window "
                    f"(or use 'Toggle character in all windows') to put them away.")
        raise
    finally:
        health.stop.set()
        det.stop.set()
        _tl.automation = False
        health.join()
        # Do not let a new job start while an old detector can still write SHARED.
        # OCR calls have a timeout and check the detector's own stop flag on return.
        det.join()


def job_test_layout():
    slots = scan_windows()
    if not slots:
        return
    for i in range(len(slots)):
        w = slots.win(i)
        if w is None:
            continue
        log(f"{w.name}: x={w.left} y={w.top} w={w.w} h={w.h}")
        bring_to_front(w.hwnd)
        sleep(0.4)
        w = slots.win(i)
        spots = [
            ("title bar (focus click)", (w.left + w.w // 2, w.top + TITLEBAR_CLICK_Y)),
            ("Welcome Back X", (w.left + int(w.w * WELCOME_CLOSE[0]), w.top + int(w.h * WELCOME_CLOSE[1]))),
            ("anti-AFK click spot", (w.left + int(w.w * AFK_CLICK_SPOT[0]), w.top + int(w.h * AFK_CLICK_SPOT[1]))),
        ]
        for label, (x, y) in spots:
            log(f"  moving mouse to {label}")
            pyautogui.moveTo(x, y, duration=0.4)
            sleep(0.6)
    log("Layout test done. The mouse should have landed on the title bar, the red X of the "
        "Welcome Back popup, and an empty spot in each window.")


def job_test_event(seconds):
    slots = scan_windows()
    if not slots:
        return
    log("TEST: pretending Hallows' Eve STARTED -> pressing the character key in every window")
    run_on_all(slots, equip_character)
    if S["verify_state"] and not S["dracula_rotation"]:
        verify_all(slots, True)
    log(f"TEST: pretend event running for {seconds}s...")
    sleep(seconds)
    log("TEST: pretending the event ENDED -> pressing the character key again")
    run_on_all(slots, unequip_character)
    if S["verify_state"] and not S["dracula_rotation"]:
        verify_all(slots, False)
    log("TEST: done.")


def job_toggle_all():
    slots = scan_windows()
    if not slots:
        return
    def manual_toggle(win):
        focus(win)
        sleep(S["settle"])
        press_char(win, "manual toggle")
        sleep(STEP_DELAY)
    run_on_all(slots, manual_toggle)
    log("Pressed the character key once in every window.")


def job_test_maintenance():
    slots = scan_windows()
    if not slots:
        return
    maintenance(slots, [0.0] * len(slots), force_afk=True)
    log("Maintenance test done: Welcome Back popups closed (if any) and one anti-AFK click per window.")


def job_test_rebirth():
    slots = scan_windows()
    if not slots:
        return
    targets = [i for i in range(len(slots)) if S["rebirth"][i]]
    if not targets:
        log("Tick at least one window under 'Rebirth macro' in the Settings tab first.")
        return
    origin = pyautogui.position()
    for i in targets:
        w = slots.win(i)
        if w is not None:
            do_rebirth(w)
    mw = slots.win(0)
    if mw is not None:
        bring_to_front(mw.hwnd)
    pyautogui.moveTo(origin.x, origin.y)
    log("Rebirth test done.")


def job_check_state():
    """Read every window's hotbar and report equipped / not equipped. Presses nothing."""
    slots = scan_windows()
    if not slots:
        return
    for i in range(len(slots)):
        w = slots.win(i)
        if w is None:
            continue
        bring_to_front(w.hwnd)
        sleep(0.5)
        w = slots.win(i)
        if popup_visible(w):
            log(f"{w.name}: Welcome Back popup is open (hotbar hidden) - can't read")
            continue
        eq = character_equipped(w)
        UI.put(("state", w.slot, eq))
        log(f"{w.name}: character is {'EQUIPPED (blue outline found)' if eq else 'not equipped (no outline)'}")
    main = slots.win(0)
    if main is not None:
        bring_to_front(main.hwnd)


def job_test_detection():
    slots = scan_windows()
    if not slots:
        return
    main = slots.win(0)
    bring_to_front(main.hwnd)
    sleep(0.5)
    active, text, img = read_event(main)
    cv2.imwrite(os.path.join(APP_DIR, "debug_crop.png"), img)
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    log(f"Banner read: {' '.join(text.split())[:160]!r}")
    log(f"Hallows' Eve detected right now: {'YES' if active else 'NO'}"
        + (f" (timer {m.group(0)})" if m else ""))
    log(f"Saved what the macro sees to {os.path.join(APP_DIR, 'debug_crop.png')}")


class Job(threading.Thread):
    def __init__(self, fn, *args):
        super().__init__(daemon=True)
        self.fn, self.args = fn, args

    def run(self):
        ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x1, 0x2
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM | ES_DISPLAY)  # no sleep
        except Exception:
            pass
        try:
            self.fn(*self.args)
        except StopMacro:
            log("Stopped.")
        except pytesseract.TesseractNotFoundError:
            log("ERROR: Tesseract OCR not found. Install it and set its path in the Settings tab.")
        except Exception as e:
            log(f"ERROR: {type(e).__name__}: {e}")
        finally:
            try:
                close_capture()
            finally:
                try:
                    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                except Exception:
                    pass


# ----------------------------------------------------------------------------
# Hotkey helpers
# ----------------------------------------------------------------------------
_VK_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock",
             0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
             0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert", 0x2E: "Delete",
             0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
             0x90: "NumLock", 0x91: "ScrollLock", 0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-",
             0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
_MODIFIERS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}


def vk_name(vk):
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num{vk - 0x60}"
    return f"Key {vk}"


def is_down(vk):
    return bool(win32api.GetAsyncKeyState(vk) & 0x8000)


def pressed_vk():
    for vk in range(0x08, 0xFF):  # starts above the mouse buttons
        if vk not in _MODIFIERS and is_down(vk):
            return vk
    return None


# ----------------------------------------------------------------------------
# The GUI
# ----------------------------------------------------------------------------
def fmt_dur(seconds):
    seconds = int(max(0, seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"


def fmt_clock(ts):
    return time.strftime("%I:%M:%S %p", time.localtime(ts)).lstrip("0")


# ----------------------------------------------------------------------------
# Qt desktop interface. The automation engine above remains independent of Qt.
# ----------------------------------------------------------------------------
import math
import logging
from logging.handlers import RotatingFileHandler
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Property, QRectF, QPointF, QSize
from PySide6.QtGui import QImage, QPixmap, QColor, QPainter, QPen, QLinearGradient, QRadialGradient, QFont, QTextCursor, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QAbstractButton, QAbstractSpinBox, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea,
    QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QPlainTextEdit, QFileDialog, QSizePolicy,
    QDialog, QCheckBox, QMessageBox)

BG, SURFACE, BORDER = "#0e1119", "#171c28", "#293143"
TEXT, MUTED, ACCENT, GREEN = "#eef0f8", "#929db4", "#ac9aff", "#72dfb4"


class Motion:
    enabled = True


def mix_color(a, b, amount):
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                          a.greenF() + (b.greenF() - a.greenF()) * amount,
                          a.blueF() + (b.blueF() - a.blueF()) * amount)


def label(text, size=10, color=TEXT, bold=False):
    widget = QLabel(text)
    widget.setFont(QFont("Segoe UI", size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    widget.setStyleSheet(f"color:{color};background:transparent;border:none;"
                        f"font-size:{size}pt;font-weight:{600 if bold else 400};")
    widget.setWordWrap(True)
    return widget


class SoftButton(QPushButton):
    """Native button semantics with rounded painting and short hover transitions."""
    def __init__(self, text, callback=None, kind="normal", parent=None):
        super().__init__(text, parent)
        self.kind, self._hover = kind, 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMinimumWidth(100)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.anim = QPropertyAnimation(self, b"hover", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if callback:
            self.clicked.connect(callback)

    def sizeHint(self):
        return QSize(max(100, self.fontMetrics().horizontalAdvance(self.text()) + 38), 40)

    def minimumSizeHint(self):
        return self.sizeHint()

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = value
        self.update()

    hover = Property(float, get_hover, set_hover)

    def animate_to(self, value):
        self.anim.stop()
        if Motion.enabled:
            self.anim.setStartValue(self._hover)
            self.anim.setEndValue(value)
            self.anim.start()
        else:
            self.set_hover(value)

    def enterEvent(self, event):
        self.animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.animate_to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.isChecked()
        if self.kind == "primary":
            bg = mix_color("#a692fa", "#c3b3ff", self._hover)
            fg, edge = QColor("#17142b"), QColor("#c4b7ff")
        elif self.kind == "danger":
            bg = mix_color("#30202c", "#513043", self._hover)
            fg, edge = QColor("#f9a9bd"), QColor("#673b50")
        else:
            bg = mix_color("#29273e" if active else "#1e2533", "#34394f", self._hover)
            fg, edge = QColor(ACCENT if active else TEXT), QColor("#514769" if active else BORDER)
        if not self.isEnabled():
            bg, fg, edge = QColor("#191e2a"), QColor("#586279"), QColor("#242c3d")
        if self.isDown():
            bg = bg.darker(115)
        p.setBrush(bg)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(rect, 11, 11)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 9, 9)
        p.setPen(fg)
        p.setFont(self.font())
        alignment = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if self.kind == "nav"
                                                    else Qt.AlignmentFlag.AlignHCenter)
        p.drawText(rect.adjusted(15, 0, -12, 0), alignment, self.text())
        p.end()


class Switch(QAbstractButton):
    def __init__(self, checked=False, name="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setAccessibleName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 28)
        self._position = float(bool(checked))
        self.anim = QPropertyAnimation(self, b"position", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self.changed)

    def get_position(self):
        return self._position

    def set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, get_position, set_position)

    def changed(self, checked):
        self.anim.stop()
        if Motion.enabled:
            self.anim.setStartValue(self._position)
            self.anim.setEndValue(float(checked))
            self.anim.start()
        else:
            self.set_position(float(checked))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setPen(QPen(QColor(ACCENT if self.hasFocus() else BORDER), 1))
        p.setBrush(mix_color("#30394e", "#a18af4", self._position))
        p.drawRoundedRect(QRectF(1, 3, 44, 22), 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f5f3ff"))
        p.drawEllipse(QRectF(4 + self._position * 22, 6, 16, 16))
        p.end()


class Hero(QFrame):
    """Slow color drift and a small orbit, suspended when hidden or motion is reduced."""
    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.setMinimumHeight(190)
        self.timer = QTimer(self)
        self.timer.setInterval(60)  # low-frequency decorative animation, never a busy loop
        self.timer.timeout.connect(self.advance)
        self.timer.start()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 23, 230, 23)
        self.eyebrow = label("AUTOMATION, IN FOCUS", 9, ACCENT, True)
        self.title = label("Ready for the next Hallows’ Eve.", 23, TEXT, True)
        self.description = label("Let the event come to you. Your windows, characters and\nDracula rotation — all in one place.", 10, "#b4bdd2")
        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)
        layout.addWidget(self.description)

    def advance(self):
        if Motion.enabled and self.isVisible() and not self.window().isMinimized():
            self.phase += 0.017
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor("#25233a"))
        grad.setColorAt(0.65, mix_color("#1b2235", "#25233d", (math.sin(self.phase) + 1) / 2))
        grad.setColorAt(1, QColor("#162933"))
        p.setBrush(grad)
        p.setPen(QPen(QColor("#3c3a56"), 1))
        p.drawRoundedRect(rect, 20, 20)
        center = QPointF(self.width() - 115, self.height() / 2)
        glow = QRadialGradient(center, 106)
        glow.setColorAt(0, QColor(135, 104, 230, 55))
        glow.setColorAt(1, QColor(135, 104, 230, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 103, 80)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#4d4569"), 1))
        p.drawEllipse(center, 67, 67)
        p.setPen(QPen(QColor("#363d57"), 1))
        p.drawEllipse(center, 50, 50)
        p.setBrush(QColor("#b6a4fc"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 29, 29)
        p.setBrush(QColor("#202439"))
        p.drawEllipse(center + QPointF(12, -9), 27, 27)
        point = center + QPointF(67 * math.cos(self.phase), 67 * math.sin(self.phase))
        p.setBrush(QColor(GREEN))
        p.drawEllipse(point, 4, 4)
        p.end()


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(20, 18, 20, 18)
        self.box.setSpacing(10)


def scroll_page():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 10, 12)
    layout.setSpacing(16)
    scroll.setWidget(content)
    return scroll, content, layout


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hallows’ Eve  •  Macro Studio 2.9")
        self.resize(1180, 870)
        self.setMinimumSize(980, 720)
        self.job = None
        self.job_label = ""
        self.binding = None
        self.binding_ready_at = 0.0
        self.prev = {}
        self.count = 0
        self.current_start = None
        self.total_time = 0.0
        self.last_duration = None
        self.states = {}
        self.history = []
        self.logs = []
        self.job_had_error = False
        self.closing = False
        self.initializing = True
        self.settings_saved = True
        Motion.enabled = not bool(S.get("reduce_motion", False))
        self.log_path = os.path.join(_setup_folder(), "logs", "macro.log")
        self.file_logger = logging.getLogger("hallows.desktop")
        self.file_logger.setLevel(logging.INFO)
        self.file_logger.propagate = False
        self.log_handler = None
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            self.log_handler = RotatingFileHandler(self.log_path, maxBytes=1_000_000,
                                                   backupCount=3, encoding="utf-8")
            self.log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.file_logger.addHandler(self.log_handler)
        except OSError:
            pass
        self.setStyleSheet(self.stylesheet())
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.apply_settings)
        self.build_ui()
        self.initializing = False
        self.update_dependencies()
        self.append_log("Ready. Choose a diagnostic or start the macro. No automation is running.")
        if self.log_handler is None:
            self.append_log("Warning: could not create a log file; logs remain visible in Activity.")
        self.timers = []
        for interval, fn in ((80, self.drain), (40, self.poll_hotkeys), (250, self.refresh_previews), (1000, self.tick)):
            timer = QTimer(self)
            timer.setInterval(interval)
            timer.timeout.connect(fn)
            timer.start()
            self.timers.append(timer)
        self.refresh_tracker()
        if not S.get("setup_complete"):
            QTimer.singleShot(350, self.show_setup)

    @staticmethod
    def stylesheet():
        return """
        QMainWindow, QWidget { background:#0e1119; color:#eef0f8; font-family:'Segoe UI'; font-size:13px; }
        QWidget#sidebar { background:#121722; border-right:1px solid #252c3d; }
        QFrame#card { background:#171c28; border:1px solid #293143; border-radius:16px; }
        QFrame#card QWidget { background:transparent; }
        QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; border:0; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
          background:#101620; color:#e9eaf5; border:1px solid #343d52; border-radius:9px;
          padding:8px 10px; min-height:22px; selection-background-color:#584780; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#ac9aff; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#626d83; border-color:#262e3f; }
        QComboBox::drop-down { border:none; width:24px; }
        QCheckBox { spacing:10px; }
        QCheckBox::indicator { width:16px; height:16px; border:1px solid #737e96; border-radius:4px; background:#101620; }
        QCheckBox::indicator:checked { background:#ac9aff; border-color:#ac9aff; }
        QComboBox QAbstractItemView { background:#20283a; color:#eef0f8; selection-background-color:#423959; padding:5px; }
        QScrollBar:vertical { background:transparent; width:9px; margin:3px; }
        QScrollBar::handle:vertical { background:#354058; border-radius:3px; min-height:32px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        QPlainTextEdit { background:#111620; border:1px solid #293143; border-radius:12px; padding:14px;
                         color:#bdc7de; font-family:'Consolas'; font-size:12px; }
        QToolTip { background:#252c3e; color:#eef0f8; border:1px solid #4c4566; padding:8px; }
        """

    def build_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        shell = QHBoxLayout(container)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(202)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(20, 28, 18, 20)
        left.setSpacing(9)
        logo = label("H / E", 24, ACCENT, True)
        left.addWidget(logo)
        left.addWidget(label("HALLOWS’ EVE", 11, TEXT, True))
        left.addWidget(label("MACRO STUDIO", 8, MUTED, True))
        left.addSpacing(36)
        left.addWidget(label("WORKSPACE", 8, "#626e87", True))
        self.nav = []
        for index, name in enumerate(("Overview", "Automation", "Diagnostics", "Activity log")):
            b = SoftButton(name, lambda checked=False, i=index: self.navigate(i), "nav")
            b.setCheckable(True)
            b.setMinimumHeight(44)
            left.addWidget(b)
            self.nav.append(b)
        left.addStretch()
        note = Card()
        note.box.setContentsMargins(13, 15, 13, 15)
        note.box.addWidget(label("YOUR SHORTCUTS", 8, MUTED, True))
        self.shortcut_text = label("", 10, TEXT, True)
        note.box.addWidget(self.shortcut_text)
        note.box.addWidget(label("Work even when Roblox\nis in front.", 9, MUTED))
        left.addWidget(note)
        left.addSpacing(10)
        self.side_status = label("●  Standing by", 9, GREEN)
        left.addWidget(self.side_status)
        left.addWidget(label("Fish! An Anime RNG", 8, "#69748b"))
        shell.addWidget(sidebar)
        body = QWidget()
        right = QVBoxLayout(body)
        right.setContentsMargins(28, 23, 24, 18)
        right.setSpacing(18)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.page_title = label("Overview", 21, TEXT, True)
        self.page_subtitle = label("A little less clicking. A little more control.", 10, MUTED)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        top.addLayout(titles, 1)
        self.start_button = SoftButton("Start macro", self.start_macro, "primary")
        self.start_button.setFixedWidth(134)
        self.stop_button = SoftButton("Stop", self.stop_job, "danger")
        self.stop_button.setFixedWidth(90)
        self.stop_button.setEnabled(False)
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
        right.addLayout(top)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        self.build_dashboard()
        self.build_settings()
        self.build_diagnostics()
        self.build_activity()
        footer = QHBoxLayout()
        self.footer_status = label("Ready when you are", 9, MUTED)
        footer.addWidget(self.footer_status, 1)
        self.footer_mode = label("DRACULA ROTATION", 8, ACCENT, True)
        self.footer_mode.setWordWrap(False)
        footer.addWidget(self.footer_mode)
        right.addLayout(footer)
        shell.addWidget(body, 1)
        self.navigate(0)
        self.update_hotkey_text()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        names = ["Overview", "Automation", "Diagnostics", "Activity log"]
        descriptions = ["A little less clicking. A little more control.",
                        "Set it up your way. Changes are saved automatically.",
                        "See what the macro sees before a full run.",
                        "Every event, action and detail. All in one place."]
        self.page_title.setText(names[index])
        self.page_subtitle.setText(descriptions[index])
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        self.nav[index].setFocus(Qt.FocusReason.OtherFocusReason)
        if index == 3:
            self.render_logs()

    def build_dashboard(self):
        page, _, layout = scroll_page()
        self.pages.addWidget(page)
        self.recovery_card = Card()
        self.recovery_text = label("", 10, "#e3b87b", True)
        self.recovery_card.box.addWidget(self.recovery_text)
        self.resume_button = SoftButton("Resume / recheck", self.resume_recheck, "primary")
        self.recovery_card.box.addWidget(self.resume_button)
        layout.addWidget(self.recovery_card)
        self.recovery_card.hide()
        self.hero = Hero()
        layout.addWidget(self.hero)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_labels = {}
        for key, title, value, hint in (("count", "EVENTS SEEN", "0", "This session"),
                ("time", "TIME IN EVENT", "0m 00s", "Across all detected events"),
                ("last", "LAST EVENT", "—", "Waiting for a completed event")):
            card = Card()
            card.box.addWidget(label(title, 8, MUTED, True))
            number = label(value, 23, TEXT, True)
            card.box.addWidget(number)
            card.box.addWidget(label(hint, 8, "#717e96"))
            self.metric_labels[key] = number
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        head = QHBoxLayout()
        head.addWidget(label("Your windows", 13, TEXT, True))
        head.addStretch()
        self.window_summary = label("No windows checked yet", 9, MUTED)
        self.window_summary.setWordWrap(False)
        head.addWidget(self.window_summary)
        layout.addLayout(head)
        windows = QHBoxLayout()
        windows.setSpacing(10)
        self.window_badges, self.window_notes = {}, {}
        for i, name in enumerate(CORNERS):
            card = Card()
            card.box.setContentsMargins(14, 15, 14, 15)
            card.box.addWidget(label(f"0{i + 1}   /   {name.replace(' (main)', '').upper()}", 8, MUTED, True))
            badge = label("Not checked", 12, TEXT, True)
            card.box.addWidget(badge)
            note = label("Run a scan to\nread this window.", 9, "#8793ac")
            note.setMinimumHeight(34)
            card.box.addWidget(note)
            windows.addWidget(card, 1)
            self.window_badges[i], self.window_notes[i] = badge, note
        layout.addLayout(windows)
        quick = Card()
        row = QHBoxLayout()
        words = QVBoxLayout()
        words.addWidget(label("Start with a quick scan", 12, TEXT, True))
        words.addWidget(label("Read Dracula labels and slot positions without switching characters.", 9, MUTED))
        row.addLayout(words, 1)
        self.quick_scan = SoftButton("Scan hotbar", lambda: self.start_job("Dracula scan", job_test_dracula))
        self.quick_scan.setFixedWidth(134)
        row.addWidget(self.quick_scan)
        quick.box.addLayout(row)
        layout.addWidget(quick)
        recent = Card()
        row = QHBoxLayout()
        row.addWidget(label("Latest activity", 12, TEXT, True))
        row.addStretch()
        row.addWidget(SoftButton("View all", lambda: self.navigate(3)))
        recent.box.addLayout(row)
        self.recent_log = label("No activity yet.", 9, MUTED)
        self.recent_log.setTextFormat(Qt.TextFormat.PlainText)
        recent.box.addWidget(self.recent_log)
        layout.addWidget(recent)
        layout.addStretch()

    def section(self, layout, title, caption):
        card = Card()
        card.box.addWidget(label(title, 13, TEXT, True))
        card.box.addWidget(label(caption, 9, MUTED))
        card.box.addSpacing(4)
        layout.addWidget(card)
        return card.box

    def setting_row(self, box, title, description, control):
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 6)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addWidget(label(title, 10, TEXT, True))
        texts.addWidget(label(description, 9, MUTED))
        row.addLayout(texts, 1)
        row.addSpacing(16)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(row)
        control.setAccessibleName(title)
        return control

    def spin(self, value, low, high, step=1, suffix="", integer=False):
        widget = QSpinBox() if integer else QDoubleSpinBox()
        widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        widget.setRange(low, high)
        widget.setSingleStep(step)
        if not integer:
            widget.setDecimals(1)
        widget.setValue(value)
        widget.setSuffix(suffix)
        widget.setFixedWidth(132)
        widget.valueChanged.connect(self.settings_changed)
        return widget

    def toggle(self, key):
        widget = Switch(S[key], key)
        widget.toggled.connect(self.settings_changed)
        return widget

    def build_settings(self):
        page, self.settings_content, layout = scroll_page()
        self.pages.addWidget(page)
        self.saved_text = label("●  All changes saved", 9, GREEN)
        layout.addWidget(self.saved_text)
        box = self.section(layout, "Character selection", "Choose how characters are selected during Hallows’ Eve.")
        self.fast_toggle = self.setting_row(box, "Fast event detection",
            "Visual checks about every 80 ms. Different banner layouts use slower OCR fallback.", self.toggle("fast_detection"))
        self.complete_toggle = self.setting_row(box, "Stop when all characters have Dracula",
            "Finish after every tracked window confirms all visible character slots. Requires smart rotation.", self.toggle("stop_when_complete"))
        self.sound_toggle = self.setting_row(box, "Completion sound",
            "Play a notification when the automatic completion stop occurs.", self.toggle("completion_sound"))
        self.rotation_toggle = self.setting_row(box, "Smart Dracula rotation",
            "Start at slot 2. Skip Dracula characters and stop when every visible character has it.", self.toggle("dracula_rotation"))
        self.char_combo = QComboBox()
        self.char_combo.addItems(list("1234567890"))
        self.char_combo.setCurrentText(str(S["char_key"]))
        self.char_combo.setFixedWidth(132)
        self.char_combo.currentTextChanged.connect(self.settings_changed)
        self.setting_row(box, "Manual character key", "Used by manual mode and fallback if no previous slot is known. Start with this character put away.", self.char_combo)
        box_notify = self.section(layout, "Webhook notifications", "Discord-compatible HTTPS webhook. Delivery runs in the background. URL is saved locally.")
        self.webhook_edit = QLineEdit(S.get("webhook_url", ""))
        self.webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook_edit.setPlaceholderText("https://discord.com/api/webhooks/…")
        self.webhook_edit.textChanged.connect(self.settings_changed)
        self.setting_row(box_notify, "Webhook URL", "Excluded from diagnostic exports. Never share this URL.", self.webhook_edit)
        self.webhook_events_toggle = self.setting_row(box_notify, "Hallows’ Eve alerts", "Send when the event detector confirms a start.", self.toggle("webhook_events"))
        self.webhook_dracula_toggle = self.setting_row(box_notify, "Dracula alerts", "First confirmed Dracula per window/slot each run, including existing mutations. Unavailable during manual fallback.", self.toggle("webhook_dracula"))
        self.verify_toggle = self.setting_row(box, "Verify equipped state",
            "Fix missed key presses in manual mode. Smart rotation always verifies its own selection.", self.toggle("verify_state"))
        box = self.section(layout, "Window timing", "Give Roblox time to respond when switching between windows.")
        self.settle_spin = self.setting_row(box, "Focus delay", "Increase this if key presses are missed on your computer.",
            self.spin(S["settle"], 0, 10, 0.5, " sec"))
        box = self.section(layout, "Keep things running", "Background maintenance runs separately for each Roblox window.")
        self.popup_toggle = self.setting_row(box, "Close Welcome Back popups", "Click the close button when the popup blocks the game.", self.toggle("close_popup"))
        self.afk_toggle = self.setting_row(box, "Prevent idle disconnects", "Send an occasional click to each window.", self.toggle("afk_enabled"))
        self.afk_spin = self.setting_row(box, "Idle-click interval", "Time between anti-idle clicks for each window.", self.spin(S["afk_minutes"], 0.5, 10, 0.5, " min"))
        box = self.section(layout, "Rebirth", "Choose which windows should attempt a rebirth. Robux prompts are closed automatically.")
        grid = QGridLayout()
        self.rebirth_toggles = []
        for i, name in enumerate(CORNERS):
            cell = QHBoxLayout()
            cell.addWidget(label(name.replace(" (main)", ""), 10), 1)
            switch = Switch(S["rebirth"][i], f"Rebirth {name}")
            switch.toggled.connect(self.settings_changed)
            self.rebirth_toggles.append(switch)
            cell.addWidget(switch)
            cell.setContentsMargins(0, 8, 18, 8)
            grid.addLayout(cell, i // 2, i % 2)
        box.addLayout(grid)
        self.rebirth_spin = self.setting_row(box, "Attempt interval", "Wait this long after each window’s rebirth attempt.", self.spin(S["rebirth_seconds"], 10, 3600, 10, " sec", True))
        box = self.section(layout, "Keyboard shortcuts", "Press Bind, then press your chosen key. Escape cancels.")
        self.bind_buttons = {}
        for key, title in (("start", "Start macro"), ("stop", "Stop everything")):
            button = SoftButton("", lambda checked=False, k=key: self.begin_bind(k))
            button.setFixedWidth(160)
            self.bind_buttons[key] = button
            self.setting_row(box, title, "Available even while Roblox is focused.", button)
        self.bind_hint = label("Choose different keys for Start and Stop.", 9, ACCENT)
        box.addWidget(self.bind_hint)
        box = self.section(layout, "OCR & appearance", "First-run setup handles OCR. Change its path only if you installed it somewhere else.")
        path_row = QHBoxLayout()
        self.tess_edit = QLineEdit(S["tesseract"])
        self.tess_edit.setAccessibleName("Tesseract executable path")
        self.tess_edit.textChanged.connect(self.settings_changed)
        path_row.addWidget(self.tess_edit, 1)
        path_row.addWidget(SoftButton("Browse", self.browse_tesseract))
        box.addLayout(path_row)
        self.motion_toggle = self.setting_row(box, "Reduce motion", "Turn off color drift and control animations.", self.toggle("reduce_motion"))
        box.addWidget(SoftButton("Open installation log", lambda: self.open_path(os.path.join(_setup_folder(), "setup.log"))))
        layout.addStretch()

    def build_diagnostics(self):
        page, _, layout = scroll_page()
        self.pages.addWidget(page)
        tip = Card()
        tip.box.addWidget(label("A clear view of what’s happening", 14, TEXT, True))
        tip.box.addWidget(label("Start with the screen-reading tests. Each test writes details to Activity log; image tests also save a crop beside the macro.", 10, MUTED))
        layout.addWidget(tip)
        self.build_live_tools(layout)
        self.test_buttons = []
        grid = QGridLayout()
        grid.setSpacing(14)
        tests = [("Dracula scan", "READS SCREEN", "Find every slot, read its mutation and report the next character to select.", job_test_dracula),
            ("Event banner", "READS SCREEN", "Read the top-left banner and save debug_crop.png for inspection.", job_test_detection),
            ("Character state", "READS SCREEN", "Check each window’s blue equipped outline without pressing a character key.", job_check_state),
            ("Window layout", "MOVES POINTER", "Visit the expected focus, popup-close and anti-idle locations.", job_test_layout),
            ("Event simulation", "SENDS INPUT", "Equip, wait for the duration below, then put characters away. Not counted as an event.", None),
            ("Popup & idle check", "SENDS INPUT", "Close detected popups and send one anti-idle click to each window.", job_test_maintenance),
            ("Rebirth attempt", "SENDS INPUT", "Try one rebirth in the windows enabled under Automation.", job_test_rebirth),
            ("Manual key toggle", "SENDS INPUT", "Press the manual character key once in every window, even when rotation is enabled.", job_toggle_all)]
        self.test_seconds_spin = self.spin(S["test_seconds"], 3, 300, 1, " sec", True)
        for i, (title, tag, description, fn) in enumerate(tests):
            card = Card()
            card.box.addWidget(label(tag, 8, GREEN if tag == "READS SCREEN" else "#e3b87b", True))
            card.box.addWidget(label(title, 13, TEXT, True))
            text = label(description, 9, MUTED)
            text.setMinimumHeight(42)
            card.box.addWidget(text)
            card.box.addStretch()
            row = QHBoxLayout()
            if fn is None:
                row.addWidget(self.test_seconds_spin)
                callback = lambda: self.start_job("Event simulation", job_test_event, int(self.test_seconds_spin.value()))
            else:
                callback = lambda checked=False, f=fn, t=title: self.start_job(t, f)
            row.addStretch()
            button = SoftButton("Run test", callback)
            row.addWidget(button)
            self.test_buttons.append(button)
            card.box.addLayout(row)
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(SoftButton("Open debug folder", lambda: self.open_path(APP_DIR)))
        row.addWidget(SoftButton("View activity log", lambda: self.navigate(3), "primary"))
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()

    def build_live_tools(self, layout):
        card = Card()
        card.box.addWidget(label("Live detection", 14, TEXT, True))
        card.box.addWidget(label("Updates while the macro or read-only preview is running. A stale or covered image is not a verdict.", 9, MUTED))
        row = QHBoxLayout()
        self.preview_start = SoftButton("Start read-only preview", lambda: self.start_job("Live preview", job_live_preview))
        self.setup_button = SoftButton("Guided setup", self.show_setup)
        row.addWidget(self.preview_start)
        row.addWidget(self.setup_button)
        row.addStretch()
        card.box.addLayout(row)
        self.banner_status = label("No banner captured yet", 9, MUTED)
        self.banner_image = QLabel("Start preview to inspect the event banner")
        self.banner_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_image.setFixedHeight(105)
        self.banner_image.setStyleSheet("background:#0b0e16;border-radius:10px;color:#929db4;")
        card.box.addWidget(self.banner_status)
        card.box.addWidget(self.banner_image)
        row = QHBoxLayout()
        self.preview_window = QComboBox()
        self.preview_window.addItems([f"Window {i+1} — {n}" for i,n in enumerate(CORNERS)])
        row.addWidget(self.preview_window)
        row.addStretch()
        card.box.addLayout(row)
        self.hotbar_status = label("No hotbar captured yet", 9, MUTED)
        self.hotbar_image = QLabel("Hotbar preview")
        self.hotbar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotbar_image.setFixedHeight(110)
        self.hotbar_image.setStyleSheet("background:#0b0e16;border-radius:10px;color:#929db4;")
        card.box.addWidget(self.hotbar_status)
        card.box.addWidget(self.hotbar_image)
        layout.addWidget(card)
        tools = Card()
        tools.box.addWidget(label("Support bundle", 12, TEXT, True))
        tools.box.addWidget(label("Export logs, settings and diagnostic results into one ZIP. Logs can contain account names and local paths; review before sharing.", 9, MUTED))
        self.export_crops = QCheckBox("Include latest banner and hotbar crops (may show game/account details)")
        self.export_crops.setChecked(False)
        tools.box.addWidget(self.export_crops)
        tools.box.addWidget(SoftButton("Export diagnostic bundle", self.export_diagnostics))
        layout.addWidget(tools)

    def refresh_previews(self):
        if not hasattr(self, "banner_image") or self.pages.currentIndex() != 2:
            return
        with DATA_LOCK:
            samples = dict(PREVIEW)
        for key, image_label, status_label in (
                ("banner", self.banner_image, self.banner_status),
                (f"hotbar_{self.preview_window.currentIndex()}", self.hotbar_image, self.hotbar_status)):
            sample = samples.get(key)
            if sample is None:
                image_label.clear()
                image_label.setText("No capture for this window yet")
                status_label.setText("Not observed")
                continue
            img, status, at = sample
            age = time.monotonic() - at
            status_label.setText(status + (f" • STALE ({age:.0f}s ago)" if age > 2 else ""))
            if img is None:
                image_label.clear()
                image_label.setText("Unable to read — uncover the game")
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            qimage = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
            image_label.setPixmap(QPixmap.fromImage(qimage).scaled(image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def show_setup(self):
        if getattr(self, "setup_dialog", None) is not None:
            self.setup_dialog.show()
            self.setup_dialog.raise_()
            return
        dialog = self.setup_dialog = QDialog(self)
        dialog.setWindowTitle("Guided setup")
        dialog.resize(640, 520)
        box = QVBoxLayout(dialog)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(14)
        box.addWidget(label("Ready in four checks", 20, TEXT, True))
        box.addWidget(label("1. Open Roblox and enter the game.\n2. Arrange up to four windows; overlap is supported. Keep the main banner visible.\n3. Close menus; keep your rod in slot 1 and characters from slot 2 onward.\n4. Move this setup window away from Roblox, then run the checks.", 10, MUTED))
        self.setup_labels = []
        for title in ("Dependencies and English OCR", "Roblox window layout", "Event banner capture", "Hotbar and mutation recognition"):
            item = label("○  " + title, 10, TEXT)
            box.addWidget(item)
            self.setup_labels.append(item)
        self.setup_result = label("These checks bring each Roblox window forward without selecting characters. An inactive event cannot validate the title match.", 9, MUTED)
        box.addWidget(self.setup_result)
        box.addStretch()
        row = QHBoxLayout()
        self.setup_run = SoftButton("Run checks", self.run_setup_checks, "primary")
        self.setup_run.setEnabled(not self.job_alive())
        row.addWidget(self.setup_run)
        row.addWidget(SoftButton("Close", dialog.hide))
        box.addLayout(row)
        dialog.show()

    def run_setup_checks(self):
        if not self.job_alive():
            for item in self.setup_labels:
                item.setText("○  Waiting for checks…")
            self.setup_result.setText("Checking each window in front… Results also appear in Activity log.")
            self.start_job("Guided setup", job_preflight)

    def resume_recheck(self):
        if self.job_alive():
            return
        self.start_macro()

    def export_diagnostics(self):
        import zipfile
        import platform
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostic bundle", "hallows_diagnostics.zip", "ZIP archives (*.zip)")
        if not path:
            return
        try:
            with DATA_LOCK:
                progress = dict(PROGRESS)
                previews = dict(PREVIEW)
            settings = dict(S)
            settings["webhook_url"] = "[redacted]"
            settings["tesseract"] = "[configured path omitted]"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("settings.json", json.dumps(settings, indent=2))
                archive.writestr("diagnostics.json", json.dumps({"app_version": "2.9", "platform": platform.platform(),
                    "python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False)),
                    "opencv": cv2.__version__, "recovery_reason": RECOVERY["reason"], "progress": progress,
                    "previews": {k:{"status":v[1], "age_seconds":round(time.monotonic()-v[2], 2)} for k,v in previews.items()}}, indent=2))
                archive.writestr("session.log", "\n".join(text for _,text in self.logs))
                if self.log_handler:
                    self.log_handler.flush()
                for filename in [self.log_path] + [self.log_path+f".{i}" for i in range(1,4)] + [os.path.join(_setup_folder(), "setup.log")]:
                    if os.path.isfile(filename):
                        archive.write(filename, "logs/" + os.path.basename(filename))
                if self.export_crops.isChecked():
                    for key, (img, _, _) in previews.items():
                        if img is not None:
                            ok, encoded = cv2.imencode(".png", img)
                            if ok:
                                archive.writestr("crops/"+key+".png", encoded.tobytes())
            self.append_log(f"Diagnostic bundle exported: {path}")
        except Exception as exc:
            self.append_log(f"Error exporting diagnostics: {exc}")


    def build_activity(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        self.pages.addWidget(page)
        row = QHBoxLayout()
        self.search_log = QLineEdit()
        self.search_log.setPlaceholderText("Search messages, windows or errors…")
        self.search_log.setAccessibleName("Search log")
        self.search_log.textChanged.connect(self.render_logs)
        row.addWidget(self.search_log, 1)
        self.log_filter = QComboBox()
        self.log_filter.addItems(["All messages", "Events", "Warnings & errors"])
        self.log_filter.currentIndexChanged.connect(self.render_logs)
        row.addWidget(self.log_filter)
        row.addWidget(SoftButton("Export log", self.export_log))
        layout.addLayout(row)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAccessibleName("Macro activity log")
        self.log_view.document().setMaximumBlockCount(1500)
        layout.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        self.log_count = label("0 messages", 9, MUTED)
        row.addWidget(self.log_count, 1)
        row.addWidget(SoftButton("Open saved log", lambda: self.open_path(self.log_path)))
        layout.addLayout(row)
        history = Card()
        row = QHBoxLayout()
        row.addWidget(label("Session history", 12, TEXT, True), 1)
        row.addWidget(SoftButton("Reset session", self.reset_session))
        history.box.addLayout(row)
        self.history_label = label("No completed events in this session.", 9, MUTED)
        self.history_label.setTextFormat(Qt.TextFormat.PlainText)
        history.box.addWidget(self.history_label)
        layout.addWidget(history)

    def settings_changed(self, *args):
        if self.initializing:
            return
        self.update_dependencies()
        self.saved_text.setText("●  Saving changes…")
        self.save_timer.start()

    def update_dependencies(self):
        self.complete_toggle.setEnabled(self.rotation_toggle.isChecked())
        self.char_combo.setEnabled(True)
        self.verify_toggle.setEnabled(not self.rotation_toggle.isChecked())
        self.afk_spin.setEnabled(self.afk_toggle.isChecked())
        self.rebirth_spin.setEnabled(any(s.isChecked() for s in self.rebirth_toggles))
        Motion.enabled = not self.motion_toggle.isChecked()
        if Motion.enabled:
            self.hero.timer.start()
        else:
            self.hero.timer.stop()
        self.footer_mode.setText("DRACULA ROTATION" if self.rotation_toggle.isChecked() else "MANUAL KEY MODE")

    def apply_settings(self):
        self.save_timer.stop()
        S.update(char_key=self.char_combo.currentText(), settle=float(self.settle_spin.value()),
                 afk_enabled=self.afk_toggle.isChecked(), afk_minutes=float(self.afk_spin.value()),
                 close_popup=self.popup_toggle.isChecked(), verify_state=self.verify_toggle.isChecked(),
                 dracula_rotation=self.rotation_toggle.isChecked(), rebirth=[s.isChecked() for s in self.rebirth_toggles],
                 rebirth_seconds=float(self.rebirth_spin.value()), tesseract=self.tess_edit.text().strip(),
                 test_seconds=int(self.test_seconds_spin.value()), reduce_motion=self.motion_toggle.isChecked(),
                 fast_detection=self.fast_toggle.isChecked(), stop_when_complete=self.complete_toggle.isChecked(),
                 completion_sound=self.sound_toggle.isChecked(), webhook_url=self.webhook_edit.text().strip(),
                 webhook_events=self.webhook_events_toggle.isChecked(), webhook_dracula=self.webhook_dracula_toggle.isChecked())
        setup_tesseract()
        # Report save errors instead of claiming persistence when a folder is read-only.
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(S, f, indent=2)
            self.settings_saved = True
            self.saved_text.setText("●  All changes saved")
        except OSError as exc:
            self.settings_saved = False
            self.saved_text.setText("Changes active • could not save to disk")
            self.append_log(f"Warning: settings could not be saved: {exc}")

    def browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select tesseract.exe", self.tess_edit.text(), "Tesseract (tesseract.exe)")
        if path:
            self.tess_edit.setText(path)

    def job_alive(self):
        return self.job is not None and self.job.is_alive()

    def start_macro(self):
        self.start_job("Macro running", job_macro)

    def start_job(self, name, fn, *args):
        if self.job_alive() or self.closing:
            self.append_log("A job is already running. Stop it before starting another.")
            return
        self.binding = None
        self.update_hotkey_text()
        self.apply_settings()
        STOP.clear()
        with DATA_LOCK:
            RECOVERY["reason"] = ""
        self.recovery_card.hide()
        self.job_had_error = False
        self.job_label = name
        self.job = Job(fn, *args)
        self.append_log(f"Starting: {name}")
        self.job.start()
        self.set_running(True)

    def stop_job(self):
        if self.job_alive():
            STOP.set()
            self.footer_status.setText("Stopping after the current action…")
            self.side_status.setText("●  Stopping")
            self.stop_button.setEnabled(False)

    def set_running(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.quick_scan.setEnabled(not running)
        self.preview_start.setEnabled(not running)
        self.resume_button.setEnabled(not running)
        if hasattr(self, "setup_run"):
            self.setup_run.setEnabled(not running)
        self.settings_content.setEnabled(not running)
        self.test_seconds_spin.setEnabled(not running)
        for button in self.test_buttons:
            button.setEnabled(not running)
        self.side_status.setText("●  Running" if running else "●  Standing by")
        self.saved_text.setText("Stop the current job to edit settings." if running else
                                ("●  All changes saved" if self.settings_saved else "Changes active • could not save to disk"))
        self.footer_status.setText(self.job_label if running else "Ready when you are")
        self.hero.title.setText("Watching for Hallows’ Eve." if running and self.job_label == "Macro running"
                               else ("A closer look at your windows." if running else "Ready for the next Hallows’ Eve."))

    def begin_bind(self, which):
        self.binding = which
        self.binding_ready_at = time.monotonic() + 0.25
        self.bind_hint.setText(f"Press your {which} key now. Escape cancels.")
        self.bind_buttons[which].setText("Press a key…")

    def update_hotkey_text(self):
        for kind in ("start", "stop"):
            self.bind_buttons[kind].setText(f"{vk_name(S[kind + '_vk'])}   ·   Bind")
        self.shortcut_text.setText(f"{vk_name(S['start_vk'])}   Start macro\n{vk_name(S['stop_vk'])}   Stop macro")
        self.bind_hint.setText("Choose different keys for Start and Stop.")

    def poll_hotkeys(self):
        if self.closing:
            return
        if self.binding:
            if time.monotonic() < self.binding_ready_at:
                return
            vk = pressed_vk()
            if vk is None:
                return
            if vk == 0x1B:
                self.binding = None
                self.update_hotkey_text()
            elif vk == S[("stop" if self.binding == "start" else "start") + "_vk"]:
                self.bind_hint.setText("That key is already assigned. Choose another key, or Escape to cancel.")
            else:
                kind = self.binding
                S[kind + "_vk"] = vk
                self.prev[vk] = True
                self.binding = None
                self.apply_settings()
                self.update_hotkey_text()
                self.append_log(f"{kind.title()} shortcut changed to {vk_name(vk)}")
            return
        for vk in {S["start_vk"], S["stop_vk"]}:
            down = is_down(vk)
            was = self.prev.get(vk, False)
            self.prev[vk] = down
            if down and not was:
                if vk == S["stop_vk"]:
                    self.stop_job()
                elif not self.job_alive():
                    self.start_macro()

    def on_event_start(self, ts):
        self.count += 1
        self.current_start = ts
        self.hero.eyebrow.setText("●  HALLOWS’ EVE IS ACTIVE")
        self.hero.title.setText("It’s time to hunt Dracula.")
        self.refresh_tracker()

    def on_event_end(self, ts, stopped):
        if self.current_start is None:
            return
        duration = max(0, ts - self.current_start)
        self.total_time += duration
        self.last_duration = duration
        self.history.insert(0, f"#{self.count}   {fmt_clock(self.current_start)} → {fmt_clock(ts)}   ·   "
                            f"{fmt_dur(duration)}" + ("   ·   stopped" if stopped else ""))
        self.history = self.history[:100]
        self.current_start = None
        self.hero.eyebrow.setText("AUTOMATION, IN FOCUS")
        self.hero.title.setText("Watching for Hallows’ Eve." if self.job_alive() else "Ready for the next Hallows’ Eve.")
        self.refresh_tracker()

    def refresh_tracker(self):
        live = max(0, time.time() - self.current_start) if self.current_start else 0
        self.metric_labels["count"].setText(str(self.count))
        self.metric_labels["time"].setText(fmt_dur(self.total_time + live))
        self.metric_labels["last"].setText(fmt_dur(self.last_duration) if self.last_duration is not None else "—")
        self.history_label.setText("\n".join(self.history[:3]) or "No completed events in this session.")

    def reset_session(self):
        self.count = 1 if self.current_start else 0
        self.total_time = 0.0
        self.last_duration = None
        self.history.clear()
        self.refresh_tracker()
        self.append_log("Session counters and history reset.")

    def tick(self):
        self.refresh_tracker()

    @staticmethod
    def message_level(text):
        lower = text.lower()
        if any(word in lower for word in ("error", "warning", "failed", "couldn't", "uncertain", "unreadable")):
            return "warning"
        if "***" in text or "hallows' eve" in lower:
            return "event"
        return "info"

    def append_log(self, text):
        if not text.startswith("["):
            text = time.strftime("[%H:%M:%S] ") + text
        level = self.message_level(text)
        if level == "warning" and self.job_alive():
            self.job_had_error = True
        self.logs.append((level, text))
        self.logs = self.logs[-1500:]
        if self.log_handler:
            self.file_logger.info(text)
        self.recent_log.setText("\n".join(line for _, line in self.logs[-3:]))
        if self.pages.currentIndex() == 3:
            self.render_logs()

    def render_logs(self, *args):
        query = self.search_log.text().casefold()
        selected = self.log_filter.currentIndex()
        lines = [text for level, text in self.logs if query in text.casefold()
                 and (selected == 0 or (selected == 1 and level == "event")
                      or (selected == 2 and level == "warning"))]
        bar = self.log_view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 3
        old_position = bar.value()
        self.log_view.setPlainText("\n".join(lines))
        bar.setValue(bar.maximum() if follow else old_position)
        self.log_count.setText(f"{len(lines)} shown  /  {len(self.logs)} recent messages  ·  Full logs saved automatically")

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export current session log", "hallows_session.log", "Log files (*.log);;Text files (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(text for _, text in self.logs) + "\n")
                self.append_log(f"Exported session log to {path}")
            except OSError as exc:
                self.append_log(f"Error exporting log: {exc}")

    def open_path(self, path):
        try:
            os.startfile(path)
        except OSError as exc:
            self.append_log(f"Could not open {path}: {exc}")

    def drain(self):
        # Bound work per UI tick so a busy log cannot delay the Stop button.
        for _ in range(200):
            try:
                msg = UI.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "log":
                self.append_log(msg[1])
            elif msg[0] == "event_start":
                self.on_event_start(msg[1])
            elif msg[0] == "event_end":
                self.on_event_end(msg[1], msg[2])
            elif msg[0] == "recovery":
                self.recovery_text.setText("Paused • " + msg[1] + " Fix the issue before resuming.")
                self.recovery_card.show()
                self.side_status.setText("●  Needs attention")
                self.navigate(0)
            elif msg[0] == "progress":
                info = msg[2]
                done = [str(c["slot"]) for c in info["slots"] if c["dracula"] is True]
                self.window_notes[msg[1]].setText(f"Selected: {info['selected'] or 'none'} • Dracula {len(done)}/{len(info['slots'])}\nSlots: {', '.join(done) or 'none'}" + ("\nAll complete" if info["complete"] else ""))
            elif msg[0] == "setup_check":
                if hasattr(self, "setup_labels"):
                    self.setup_labels[msg[1]].setText(("✓  " if msg[2] else "!  ") + msg[3])
            elif msg[0] == "setup_finished":
                if hasattr(self, "setup_result") and not msg[1]:
                    self.setup_result.setText("Checks finished with an issue. Review the marked step and Activity log, then rerun checks.")
            elif msg[0] == "setup_done":
                S["setup_complete"] = True
                save_settings()
                if hasattr(self, "setup_result"):
                    self.setup_result.setText("Checks passed. Review Automation options, close setup and press Start when ready.")
            elif msg[0] == "complete":
                self.recovery_text.setText("Session complete • All tracked characters have Dracula.")
                self.recovery_card.show()
                self.navigate(0)
                if S.get("completion_sound", True):
                    QApplication.beep()
            elif msg[0] == "rotation":
                self.window_badges[msg[1]].setToolTip(msg[2])
                if msg[1] not in PROGRESS:
                    self.window_notes[msg[1]].setText(msg[2])
            elif msg[0] == "state":
                i, value = msg[1], msg[2]
                self.states[i] = value
                self.window_badges[i].setText("Equipped" if value is True else "Put away" if value is False else "Uncertain")
                self.window_badges[i].setStyleSheet(f"color:{GREEN if value is True else MUTED if value is False else '#e3b87b'};background:transparent;border:none;font-size:12pt;font-weight:600;")
                self.window_summary.setText(f"{len(self.states)} window{'s' if len(self.states) != 1 else ''} checked")
        if self.job is not None and not self.job.is_alive():
            name = self.job_label
            self.job = None
            self.set_running(False)
            if RECOVERY["reason"]:
                self.side_status.setText("●  Paused — fix issue")
                self.footer_status.setText(RECOVERY["reason"])
            self.append_log(f"Finished: {name}" + (" — review warnings in Activity log." if self.job_had_error else " — see Activity log for results."))
            if self.closing:
                self.close()

    def closeEvent(self, event):
        if self.job_alive():
            self.closing = True
            self.stop_job()
            self.footer_status.setText("Stopping the current action before closing…")
            event.ignore()
            return
        self.apply_settings()
        for timer in self.timers:
            timer.stop()
        self.hero.timer.stop()
        if self.log_handler:
            self.file_logger.removeHandler(self.log_handler)
            self.log_handler.close()
        event.accept()


def desktop_palette():
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, "#101620"), (QPalette.ColorRole.AlternateBase, SURFACE),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, "#1e2533"),
                        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, "#584780"),
                        (QPalette.ColorRole.HighlightedText, TEXT), (QPalette.ColorRole.ToolTipBase, SURFACE),
                        (QPalette.ColorRole.ToolTipText, TEXT)):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#626d83"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#626d83"))
    return palette


def main():
    load_settings()
    if _BOOTSTRAP_TESSERACT:
        S["tesseract"] = _BOOTSTRAP_TESSERACT
    setup_tesseract()
    app = QApplication(sys.argv)
    app.setApplicationName("Hallows’ Eve Macro Studio 2.9")
    app.setStyle("Fusion")
    app.setPalette(desktop_palette())
    app.setFont(QFont("Segoe UI", 10))
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
