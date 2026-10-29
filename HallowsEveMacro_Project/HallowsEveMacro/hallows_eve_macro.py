"""
Hallows' Eve Macro  -  Fish! An Anime RNG  (up to 4 Roblox windows)

A small desktop program that:
  * watches the TOP-LEFT Roblox window for the Hallows' Eve banner (screen OCR)
  * when the event starts  -> focuses each window and presses your character key (default 2)
  * when the event ends    -> puts away characters, then confirms each hotbar visually
  * closes the "Welcome Back" popup whenever it shows (red X only, never YES)
  * sends a focused Space press per window on an independent anti-idle schedule
  * checks hotbars and handles maintenance BETWEEN events; during Hallows' Eve it prioritizes
    the banner watcher, validated countdown guard, and confirmed put-away recovery
  * optional REBIRTH macro per window: tries a rebirth every minute (never touches the Robux buttons)
  * closes recognized Robux purchase prompts with their X during idle maintenance
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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from macro_runtime import UiMailbox, BoundedExecutor, atomic_settings, validated_settings
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
AFK_CLICK_SPOT = (0.50, 0.33)             # empty-world reference for the pointer layout diagnostic
KEYWORDS = ["hallows"]                    # fuzzy-matched in the banner text

POLL_SECONDS = 0.04         # active banner checks target 25 frames/second
OCR_TIMEOUT = 5.0          # bound a stalled Tesseract call; normal reads finish much sooner
OCR_EXECUTOR = BoundedExecutor(2, "MacroOCR")
ROTATION_EXECUTOR = BoundedExecutor(2, "MutationScan")
EVENT_END_CONFIRM_SECONDS = 0.08  # multiple fresh frames; cleanup also has a countdown guard
EVENT_TIMER_REGION = (0.32, 0.165, 0.68, 0.205)
EXIT_TOOL_ICONS = ('iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAAAAABWESUoAAADRUlEQVQ4EUXBSW4jVRgA4P9/79WrKlc55SGxncROZwCBaEBBTQf1BnqBkECCA3AG7sIFWAEHaKlPwA4JsWgEdBIUmiGOB+w4ds1v+oEF4vtwrySyBBb+RwCAsDMS+WrJcaCscwTkCIDgP4hiOML17Zxj16+MdcgVERAQEvyLN19jWKSbtcCuVyKzNVe+tY4ICQAQ/d5pVa7XWS6wgwydrgQIrQnAEQDwcDsZgF3dpoXAnolNYQjDwjhiqAmA+Z0DjwnYrDYpx5M7zyjOs6DgYAkMcxglSScO17lRmwXDw1ITAa+MFcwR1IzEwUBQp3P1l/DTMeL2y5M7TX7nxtnAt6V1SdRtR0G5+j1PWvUN4h5mUVwueX5cpJrE7mS05flJOP5tobtdM0bcFYGrS9UmSLUnqWNaUSxUej3XtDswLwjvZ1GdgwfRnJAz2A2E3ILFZJYjDvf1JeGjiXCGy9v21GcOw92G5JTPpplBNhrqc8IzlSoSYWYz4fEgCeKWm08WqQNgo5G6cHj/4HLFwyh41uTNKNwyQVJez7IMEHF0oJ8TnqT5sJ9eqfrdnCSIVj5b1bG4AkQ8PlI/WHxvGVSFw4YumomPxG8XRhlbJ5mBw6P6R4efnIdW+960JaQnpb0pCmtqJ3ll4WCkzgkfTwNuiM+6kUDO1ZXVlrTywCH0uvUY8Z3GvEQZ1VkvFrrI/wyiLNfgiaLZNpWpOL6RTGzAHM/2+1F9t16kUaYCsZL53v5sApzjmzk0g3ImO72XtjFf/fKTBtlmV1IN+7MZcIEfXYvKSRvFW2/di2D+9aSUWjnbyJut9R1xgR9fNIwSMoDwwUlbLr+crRmUOlbSUW2QC3xYBYYkupQ9eKUX3X01z7lfpjF//fmtYYwLPAvnpiG1WsjD/Za3+YaSdCdYmMGnX/yqEZjAV6VjHpVlvg8yYIYuJP/g3nffn372+eXGMBR4lhJD0sZugQMy8VIFH57Of67b365qy4Dj++MaAJmNi9ApgjLJvIdv71RPnxXwD+T4eGrIoaeGS06KR39sZ+LouB8+udEWADnDM6vJWI86WYngNa495J4zciN1DYAC8VE4pZAz96IPnttUfdVY57whaUHCA438byry2VBWJqVdAAAAAElFTkSuQmCC', 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAAAAABWESUoAAADY0lEQVQ4ET3By24bVRgA4P8/85/x2B6bGc/EuTtJk1AakohaFSgIEVqpSLwIGxa8AwvYI8QK8R5sAAFCLaG0QiEEkpTExo5jG1/Gc/FczjkEBfX7cF2ITEmlFFxTcEMBICAy1BjeUlMhpVIK/qfgmkLAaxrTcC1JM5SZAgX/UXADATkoJA1rCYsgkygUvKAAEOY2gnFb07CWYJxBikqCUvAC42u3RoMGI6ylkT1ORVaIpZSo4Aa6e4E/nIyIcMVqQ5iz/+ZTo9DXJIACAJZbejUKO5MxEd7xfFbxp4FejNOY8VQqACjskDK189GYCF/2yt3CNHT6+akwAp4pUFi2Fku5SZj4bUa4PaYw4RMziik1sgwzlHrdSGcqv/cq4gQIl0Xw2tlYxncasZC1q1SAXVoom+HwNFrlp0j4yupR4rm1JzxYsA+NaVXvbpnScs+e9+S6eQKE9WGoz1/5XrXaDqMqeW7eLFS9zvlIsR3rqSKsD5efF+LRrUbZi+YHLKjroDudk16CWLcPJOF+326JcnexyWlojfOWY9pZo90VgOxu5bEiXCR+98llobzxs58rufFyZM55z3oBILJ65bHkuLv1bDRZ2fo6CXftRhXQCVoDO2oCItub+VYS3oudS/dKCjbTlHMWKm0w8LNUWH1gb7jfS8I9b+tpXvq3f7Wmrs6K7CwIRWQkeghYtw4U4cN+YcxealXbJtgakDiWEQWKgZbxVXahES6Zuc1f+pa1/MioOawz7s7qx4qKcrS0+UgQcXxz9ihgzvKPQqs5m/nx+PiEJXv9P5jYdn+SGnG8ly39Vepztzlbqrwzw8LPW9xPhXBa87NHiojjW/7abwb61qQChXcXzezTTr80MFLUJfOQiOPDf5hiemuGKQ/fW3HVZ1eDhctM13cPAo1pxHG9IhYORdmMo5F+u1pIvymp9v1m6L7/UYsk4xzfLpxyxgl937C6FQbiz6L+5Vdf7H/48WFAyDm+jnZHBBrE+chkAQvzkmcfLIy++yFERRnpeD9wLlSotGhOqNL5/JDRsPJge+OT48hIUNMIH3igCTFk3FFXerI0GBjTpR4aA7snGerAcccJy020p8Vzoyz5Rdkw4ssilSeDnMZjII772DWNlBouatiYjcppxx1VJ37Br44FSaJ/AWmZswq9uP/eAAAAAElFTkSuQmCC', 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAAAAABWESUoAAADt0lEQVQ4ETXBS28bVRgA0PvNzL3jGb8fcRrHebUqaaPENUqRKC2RKigqZQEbxIIFQqrEArFAbFggNkiw4h8QCf4B3ZRKLaJCadWWthFxSBwncRzHSWzH4xnPjOc99xIJcQ68Y7osdD3KGPofIMQQyi6Ws9rdNixxg8B3KfMp+g8AYoihVHl+RLD378M13rACL4AwgACdAnSKgbxQGiO+uvscloZRw3Q8kAwahggBOsUAX1gsRsJBY1OFD3cTqiV6alwT5B5jDBBDjJ9446wc6K3qEYbba0HAEnZDCsVEHQFllDFIX1uIB8bhVoOJcF31x4Ou6kj5vjlEEnUCBmL5epINj6o7DonAlcltHCg4tZ9S3LQKzKPATb2fQ9bJxpYhEBHeltQBb/tRxRStlG/TMMD5d6eR1dmoDThBFGFJvdGsqXa6/Mx0UanfcYLk0nzE7m3W+pTHIoEfHsiHbMauZA/OFx6mTCmHpKtJX6lVuz4nYELgy9UwgThlr5h08OpIBEh6eoINtjeOXeAETAjcSihjdtOSxZlKV45JOndhljeaawc243lBIAQ+uPzC53uRwnpOOZ7vuHSyHB8eVeo2BY7nMSHw8WT7BJswuucJzSlLzc8XvPbWhsUYcJyACYG3Yh89/d0YnZtdbicnFmux86DU/7bCAAFwAiYEVn6utqZueb/o1ifl7wevLeBmpe58erhiAMcJmBD4KrMZtyxfkyZ3w/q5hcRhRZtpYN3IajoImBC4ffM+DfvxdGV6Tx+dTiu1nghqXx7GzCHwmBD44tWXblxD2RfjXqOU15v7bqyPujjkmRfwmBD4PJNqqhYpWHuUnxM29m05rzcNiCLPCTmMRfhWnVurxrMkc0d8XTpZdUeimD4667lU5USHEhEe3NulubnhPQtdydZ21EsXt/+Imp/tPPS8YupwiEX4+s1HpKedia3nssoRl1barjDVNF1v6kjFiPIifPPer7bkpFIrpW6j9CTt90ShM1LN2MyzuIjNi/Bd3OCT7YNEFHdrYwcXUc0Q9UuPQ9GO2hrHCwR+9F/5p+FHc9y6lh7j6wqfG2lvD+VzZmvABEwx3HlyRm9zGf64lS++TB7IRadLN68OdK+TTHRdToDfdtqEkUi/KUVHnyKaSPZ2E53LvR1JSyfbtkhhefaxSwjrdScamVxDMEwSUvsk4iT6JhZCHMDy9F/xtKY5rVnbGH9WoF0u7Mw/jziO7LrE4Qj8FFgFub4fiU34f8bMEq0okn/j7onoFZ0W4/novyX991UVT1blAAAAAElFTkSuQmCC')
EQUIP_SAMPLE_SECONDS = .04
EQUIP_CONFIRM_SECONDS = .16
EQUIP_RETRY_SECONDS = 2.0  # allow late game inputs to settle before another toggle
EQUIP_UNREADABLE_SECONDS = 1.0
EQUIP_BATCH_SECONDS = .30
EVENT_FOCUS_GRACE = .08  # let the newly active game process activation before key-down

CLEANUP_KEY_HOLD = .10
CLEANUP_RETRY_SECONDS = .35
CLEANUP_SAMPLE_SECONDS = .06
CLEANUP_CONFIRM_SECONDS = .12
CLEANUP_TOGGLE_RETRY_SECONDS = 2.0  # unlike a safe tool, a delayed toggle can re-equip
CLEANUP_UNREADABLE_SECONDS = .5  # avoid rapid focus cycling during hidden hotbars/refused focus
IDLE_FOCUS_AUDIT_SECONDS = 20.0  # covered hotbars need occasional foreground inspection
MAX_HOLD_SECONDS = 600      # pause for review if an event remains active this long
MAINTENANCE_SECONDS = 20    # popup check / anti-AFK pass interval
DAILY_CLOSE_PNG = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAAAAABWESUoAAABBElEQVQ4EYXBrUsDARzH4c8XFERZkfN/cJYJJstxyWCw2IQrg0WTYDgRFLwVbYJF264NRVaEIRgWDAqXTYK2TcEkiEHvhbvbpd/zCIMwCIMwCIMwCIMwCIMwiNJ5CzgZAh0fGJyREqXOjgf9aEDb9+A6uiUlKkEI3B3Sa0K890BGVIKQ0sI3OVGZX78n97j1+UdOTFncvGiQ6F8NKYia8RKJgy4lUTNxSHRPvyiImolDauRSEFOavdYMqZFLQVQ8v03uLTr6JScqQQgvY1htwEb8QUZUghD8CJ7XgO0bMqI09GbBj2DueB9+LndJiZLrAE/vwMoy8BqTEgZhEAZhEAZhEIZ/iRo3ISie90QAAAAASUVORK5CYII='
DAILY_REWARDS_SECONDS = 120  # checked during idle maintenance, never during an event
CONNECTION_CHECK_SECONDS = 10  # independent, read-only checks; never block the input worker
DAILY_REWARDS_REGION = (0.25, 0.14, 0.90, 0.32)  # title and red X only, away from reward buttons
STEP_DELAY = 0.35
CORNERS = ["Top-left (main)", "Top-right", "Bottom-left", "Bottom-right"]

DEFAULTS = {
    "start_vk": 0x75,       # F6
    "stop_vk": 0x76,        # F7
    "char_key": "2",
    "settle": 2.0,          # seconds to wait after focusing a window before pressing the key
    "afk_enabled": True,
    "afk_minutes": 4.0,
    "close_popup": True,
    "close_daily_rewards": True,
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
    "unequip_lead_seconds": 2.0,
    "stop_when_complete": False,
    "completion_sound": True,
    "setup_complete": False,
}
S = dict(DEFAULTS)


def load_settings():
    try:
        source = SETTINGS_FILE if os.path.isfile(SETTINGS_FILE) else os.path.join(APP_DIR, "hallows_macro_settings.json")
        with open(source, "r", encoding="utf-8") as f:
            S.update(validated_settings(json.load(f), DEFAULTS))
    except Exception:
        pass
    reb = S.get("rebirth")
    if not isinstance(reb, list) or len(reb) != 4:
        S["rebirth"] = [False, False, False, False]


def save_settings():
    try:
        atomic_settings(SETTINGS_FILE, S)
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
UI = UiMailbox()
STOP = threading.Event()


class StopMacro(Exception):
    pass


class WindowUnavailable(Exception):
    """Cancel work on one excluded window without stopping the other windows."""


class FrameUnavailable(Exception):
    """Discard a capture whose window moved or disappeared during acquisition."""


class Preempt(BaseException):
    """Raised inside low-priority chores (window checks, rebirths, verification) when the event
    just started/ended, so the equip/unequip can happen right away. BaseException so that the
    'except Exception' blocks sprinkled through the code can never swallow it."""


_tl = threading.local()
SHARED = {"want": False, "holding": False, "event_priority": False,
          "end_seq": 0, "handled_end_seq": 0, "ended_at": 0.0}


class preemptible:
    def __enter__(self):
        self.previous = getattr(_tl, "preemptible", False)
        _tl.preemptible = True

    def __exit__(self, *exc):
        _tl.preemptible = self.previous


def log(msg):
    UI.put(("log", time.strftime("[%H:%M:%S] ") + msg))


def check_stop():
    local_stop = getattr(_tl, "stop", None)
    if STOP.is_set() or (local_stop is not None and local_stop.is_set()):
        raise StopMacro()
    task = getattr(_tl, "window_task", None)
    if task is not None and task[0].is_invalid(task[1].slot):
        raise WindowUnavailable(task[1].name)
    if getattr(_tl, "preemptible", False) and (
            SHARED["want"] != SHARED["holding"] or
            SHARED.get("end_seq", 0) > SHARED.get("handled_end_seq", 0)):
        raise Preempt()
    slots = getattr(_tl, "run_slots", None)
    if (getattr(_tl, "preemptible", False) and slots is not None
            and slots.restore_requested.is_set() and not SHARED["holding"]):
        raise Preempt()


class window_task:
    """Make sleeps and OCR waits cancellable when this window is excluded."""
    def __init__(self, slots, win):
        self.task = (slots, win)

    def __enter__(self):
        self.previous = getattr(_tl, "window_task", None)
        _tl.window_task = self.task

    def __exit__(self, *exc):
        _tl.window_task = self.previous


def guard_window(win):
    """Recheck cached windows before capture or input in an automation run."""
    slots = getattr(_tl, "run_slots", None)
    if slots is None:
        return
    if slots.is_invalid(win.slot):
        raise WindowUnavailable(win.name)
    current = passive_window(slots, win.slot)
    if current is None or current.hwnd != win.hwnd:
        slots.invalidate(win.slot, "closed, minimized or unavailable")
        raise WindowUnavailable(win.name)
    if (current.left, current.top, current.w, current.h) != (win.left, win.top, win.w, win.h):
        raise FrameUnavailable(f"{win.name}: window geometry changed; fresh capture required")


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
             "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
             "space": 0x39}


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
    if ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        raise RuntimeError("Windows rejected the key input; check that Roblox and the macro use the same permission level")


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
        receipt = getattr(_tl, "on_key_down", None)
        if receipt is not None:
            receipt()
        time.sleep(hold)
    finally:
        try:
            _send_scan(scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
        except RuntimeError:
            # A transient rejected release must not leave a held scan code.
            time.sleep(.01)
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


def hover_click(x, y, hold=0.1, before_down=None):
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
    if before_down is not None:
        before_down()
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
        self.invalid = {}
        self.lock = threading.RLock()
        self.main_slot = 0 if self.hwnds else None
        self.restore_requested = threading.Event()

    def __len__(self):
        return len(self.hwnds)

    def is_invalid(self, i):
        with self.lock:
            return i in self.invalid

    def active_indices(self):
        with self.lock:
            return [i for i in range(len(self)) if i not in self.invalid]

    def invalidate(self, i, reason):
        # Keep original indices: character settings and progress must never move
        # to a different window when an earlier window is removed.
        with self.lock:
            if i in self.invalid:
                return
            self.invalid[i] = reason
            remaining = self.active_indices()
            changed = self.main_slot == i
            if changed:
                self.main_slot = remaining[0] if remaining else None
            # A disconnected foreground window may cover the surviving banner.
            self.restore_requested.set()
            main_slot = self.main_slot
        with DATA_LOCK:
            PROGRESS.pop(i, None)
        log(f"{CORNERS[i]}: skipped for this run ({reason}). {len(remaining)} window(s) remain active.")
        UI.put(("window_invalid", i, reason, len(remaining)))
        publish_preview(f"hotbar_{i}", None, f"Skipped • {reason}")
        if changed and main_slot is not None:
            log(f"Event monitor moved to {CORNERS[main_slot]}.")
        if not remaining:
            safety_pause("No usable Roblox windows remain. Reconnect them and restart the macro.")

    def win(self, i):
        if self.is_invalid(i):
            return None
        if getattr(_tl, "run_slots", None) is self:
            win = passive_window(self, i)
            if win is None:
                self.invalidate(i, "closed, minimized or unavailable")
            return win
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
        return [w for w in (self.win(i) for i in self.active_indices()) if w]


def scan_windows(passive=False):
    hwnds = live_roblox_hwnds()
    for h in hwnds:
        if not passive and _show_state(h) == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            sleep(0.4)
    hwnds = order_windows(live_roblox_hwnds())
    if not hwnds:
        UI.put(("windows_found", 0))
        log("No Roblox windows found. Open your game windows first.")
        return None
    if len(hwnds) > 4:
        log(f"Found {len(hwnds)} Roblox windows; using the first 4.")
        hwnds = hwnds[:4]
    slots = Slots(hwnds)
    UI.put(("windows_found", len(hwnds)))
    log(f"Found {len(hwnds)} Roblox window(s): " + ", ".join(CORNERS[i] for i in range(len(hwnds))))
    return slots


def foreground_title():
    try:
        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "?"
    except Exception:
        return "?"


def wait_for_foreground(hwnd):
    """Activation across input queues is asynchronous; verify within a short bound."""
    deadline = time.monotonic() + (.04 if (getattr(_tl, "event_cleanup", False) or getattr(_tl, "event_input", False)) else .12)
    while True:
        check_stop()
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        left = deadline-time.monotonic()
        if left <= 0:
            return False
        sleep(min(.01, left))


def bring_to_front(hwnd):
    """Activate without clicking, moving, resizing, or joining input queues."""
    slots = getattr(_tl, "run_slots", None)
    if slots is not None and hwnd in slots.hwnds:
        i = slots.hwnds.index(hwnd)
        if slots.is_invalid(i):
            raise WindowUnavailable(CORNERS[i])
    if win32gui.GetForegroundWindow() == hwnd:
        return True
    for method in range(3):
        check_stop()
        try:
            if method == 1:
                # Release ALT even if the activation request is rejected.
                try:
                    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                finally:
                    ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            elif method == 2:
                # Raise overlapping windows without a title-bar click. The
                # async flag avoids waiting on a stalled game's input queue.
                flags = (win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                         win32con.SWP_SHOWWINDOW | win32con.SWP_ASYNCWINDOWPOS)
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, 0, 0, flags)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        if wait_for_foreground(hwnd):
            return True
    return False


def _root_at(x, y):
    h = win32gui.WindowFromPoint((x, y))
    return ctypes.windll.user32.GetAncestor(h, 2) if h else 0  # 2 = GA_ROOT


def focus(win):
    """Acquire foreground ownership without moving or clicking the mouse."""
    guard_window(win)
    if win32gui.GetForegroundWindow() == win.hwnd:
        return True
    for _ in range(3):
        if bring_to_front(win.hwnd):
            sleep(.3)
            guard_window(win)
            if win32gui.GetForegroundWindow() == win.hwnd:
                return True
        else:
            sleep(.15)
    log(f"  {win.name}: Windows refused to focus this window")
    return False


def cleanup_focus(win):
    """Acquire foreground ownership promptly, without a title-bar click."""
    guard_window(win)
    if win32gui.GetForegroundWindow() == win.hwnd:
        return True
    if not bring_to_front(win.hwnd):
        return False
    sleep(EVENT_FOCUS_GRACE)
    guard_window(win)
    return win32gui.GetForegroundWindow() == win.hwnd


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
    guard_window(win)
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
    guard_window(win)
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # one BGR copy, not two


def ocr(img, *, data=False, config="--psm 6"):
    """Let event transitions interrupt a worker waiting on Tesseract.

    The bounded OCR pool never sends input. An abandoned result is discarded;
    its subprocess still has a timeout and cannot resume the interrupted action.
    """
    check_stop()
    fn = pytesseract.image_to_data if data else pytesseract.image_to_string
    options = {"config": config, "timeout": OCR_TIMEOUT}
    if data:
        options["output_type"] = pytesseract.Output.DICT
    if getattr(_tl, "automation", False) and getattr(_tl, "preemptible", False):
        pending = None
        while pending is None:
            check_stop()
            pending = OCR_EXECUTOR.submit(fn, img, **options)
            if pending is None:
                sleep(.02)
        try:
            while True:
                check_stop()
                try:
                    result = pending.result(timeout=.02)
                    break
                except FutureTimeout:
                    if pending.done():
                        raise
        finally:
            pending.cancel()
    else:
        result = fn(img, **options)
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
        if (any(re.fullmatch(r"hallows?eve", w) for w in words)
                or (has_word(words, "hallows", .85) and "eve" in words)):
            return True, text, img
    return False, text, img


def disconnected_text(text):
    text = " ".join(text.lower().split())
    return any(p in text for p in ("disconnected", "connection lost", "same account launched")) or bool(
        re.search(r"error\s*code\s*:?\s*(?:267|273|277|279|280|282|285)\b", text))


def exclude_disconnected(win, text):
    slots = getattr(_tl, "run_slots", None)
    if slots is not None and disconnected_text(text):
        slots.invalidate(win.slot, "Roblox disconnected")
        raise WindowUnavailable(win.name)


def popup_state(win):
    """Which blocking popups are showing: {'welcome'} and/or {'robux'} (the Roblox 'Buy item' prompt)."""
    text = read_text(grab(win, POPUP_REGION), scale=2, n=2).lower()
    exclude_disconnected(win, text)
    words = re.findall(r"[a-z]+", text)
    found = set()
    if any(has_word(words, k, 0.8) for k in ("welcome", "offline", "triple")):
        found.add("welcome")
    if "daily" in words and any(w in words for w in ("rewards", "rewardsl")):
        found.add("daily_rewards")
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
    fingerprint: bytes = b""  # candidate validation only; never equipment confirmation


def card_fingerprint(img, box):
    """Conservative artwork + mutation-label identity, excluding selection rims.

    Any mismatch invalidates a plan; equality is not a verdict about equipment.
    Exact cropped bytes intentionally favor a rescan over a stale inventory guess.
    """
    x,y,w,h = box
    inset = max(4, round(min(w,h)*.22))
    art = img[y+inset:y+h-inset, x+inset:x+w-inset]
    label = img[max(0,y-round(h*.5)):y, max(0,x):x+w]
    if not art.size or not label.size:
        return b""
    thumb = cv2.resize(art, (12,12), interpolation=cv2.INTER_AREA)
    b,g,r = (label[...,i].astype(np.int16) for i in range(3))
    red = ((r>95) & (r>g*2.9) & (r>b*1.6)).astype(np.uint8)
    label_mask = cv2.resize(red, (48,16), interpolation=cv2.INTER_NEAREST)
    return thumb.tobytes()+np.packbits(label_mask).tobytes()


def card_layout_signature(cards):
    return tuple((c.kind, getattr(c, "fingerprint", b"")) for c in cards)


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
    rows, seen_rows = [], set()
    thick_edges = cv2.dilate(edges, np.ones((3,3), np.uint8)) > 0
    for anchor in boxes:
        row = sorted([b for b in boxes if abs(b[1] + b[3] / 2
                     - (anchor[1] + anchor[3] / 2)) < 0.18 * anchor[3]])
        if not 2 <= len(row) <= 10:
            continue
        signature = tuple(row)
        if signature in seen_rows:
            continue
        seen_rows.add(signature)
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
        return fit_hotbar_grid(img, window_width, window_height, boxes, edges, outlines)
    row = max(rows, key=len)
    # A selected blue outline can enlarge one contour; use the whole row's
    # typical geometry so the mutation-label crop does not move with selection.
    width = round(float(np.median([b[2] for b in row])))
    height = round(float(np.median([b[3] for b in row])))
    top = round(float(np.median([b[1] for b in row])))
    return [(round(x + w / 2 - width / 2), top, width, height) for x, y, w, h in row]


def fit_hotbar_grid(img, window_width, window_height, anchors, edges=None, outlines=None):
    """Recover merged contours only when every proposed card has real edges.

    Bright selection borders can join neighbouring stars/cards into one contour.
    A grid hypothesis uses the remaining cards, then verifies all slot outlines;
    a missing/covered square is never accepted just because spacing predicts it.
    """
    if edges is None:
        edges = cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 40, 120)
    # Neutral item outlines must establish geometry independently of saturated
    # contours: stars/backgrounds can make the latter much larger than a card.
    if outlines is None:
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
    solutions, seen_rows = [], set()
    for anchor in anchors:
        check_stop()
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
        signature = tuple(row)
        if signature in seen_rows:
            continue
        seen_rows.add(signature)
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
    # One native horizontal erosion replaces a Python run scan on every row.
    # Zero padding preserves the original minimum continuous edge length.
    edges = cv2.erode(blue.astype(np.uint8), np.ones((1, max(8, int(w*.55))), np.uint8),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    rows = np.flatnonzero(edges.any(axis=1))
    distances = rows[:, None] - rows[None, :]
    return bool(np.any((distances >= .65*h) & (distances <= 1.2*h)))


def read_mutation(img, box, allow_ocr=True):
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
    if not allow_ocr:
        return None, "red mutation label needs OCR"
    red = np.isin(labels, letters)
    big = cv2.resize(label, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    isolated = cv2.resize((~red).astype(np.uint8) * 255, None, fx=6, fy=6,
                          interpolation=cv2.INTER_NEAREST)
    readings = []
    for variant in (big, gray, isolated):
        check_stop()
        text = ocr(variant, config="--psm 7")
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
    # Classify just this rim instead of converting the full hotbar once per card.
    left, top = max(0, x-1), max(0, y-1)
    hsv = cv2.cvtColor(img[top:y+h+1, left:x+w+1], cv2.COLOR_BGR2HSV)
    rim = np.zeros(hsv.shape[:2], np.uint8)
    cv2.rectangle(rim, (x-left,y-top), (x+w-1-left,y+h-1-top), 255, 2)
    coloured = (hsv[:,:,1]>=110) & (hsv[:,:,2]>=100) & (rim!=0)
    if np.count_nonzero(coloured)/max(1,np.count_nonzero(rim)) < .25:
        return "item"
    return "unknown"


def hotbar_snapshot(win, read_labels=True):
    try:
        img = grab(win, MUTATION_REGION)
    except FrameUnavailable:
        return [], np.zeros((1,1,3), np.uint8)
    boxes = locate_hotbar(img, win.w, win.h)
    cards = []
    for number, box in enumerate(boxes, 1):
        card = HotbarCard(number, box, card_is_equipped(img, box))
        card.kind = hotbar_card_kind(img, box)
        card.fingerprint = card_fingerprint(img, box)
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
    characters = 0
    for card in cards[1:]:  # only earlier slots can change the first eligible target
        if card.kind == "unknown":
            return None
        if card.kind != "character":
            continue
        characters += 1
        if card.dracula is None:
            return None
        if not card.dracula:
            return card.number
    return 0 if characters else None


def hotbar_visible(win, cards):
    """Test only detected card/label pixels, not unused screen/frame margins."""
    if len(cards)<2:
        return False
    try:
        guard_window(win)
    except FrameUnavailable:
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
    if not getattr(_tl, "automation", False):
        raise RuntimeError("Use the event diagnostic to initialize confirmed input tracking")
    state = _tl.manual_fallback[win.hwnd]
    if want:
        return event_equip_slot(win, SLOT_KEYS.index(state["key"])+1, allow_hidden_first=True)
    return ensure_state(win, False)

def activate_manual_fallback(win, want):
    states = getattr(_tl, "manual_fallback", None)
    if states is None:
        states = _tl.manual_fallback = {}
    slot = getattr(_tl, "commanded_slots", {}).get(win.hwnd, 0)
    key = (SLOT_KEYS[slot-1] if 2 <= slot <= 10 else
           getattr(_tl, "last_character_keys", {}).get(win.hwnd, str(S["char_key"])))
    states[win.hwnd] = {"key": key, "equipped": slot >= 2}
    getattr(_tl, "hotbar_waits", {}).pop(win.hwnd, None)
    log(f"{win.name}: switching to manual fallback for this run (key {key}); mutation scans disabled; equip confirmation remains active")
    UI.put(("rotation", win.slot, f"Manual fallback • key {key}"))
    return manual_fallback_state(win, want)


def rotation_state(win, want, known_popup_state=None):
    """Equip/unequip an identified numbered card; never blindly toggle a guessed slot."""
    if win32gui.GetForegroundWindow() != win.hwnd:
        if not bring_to_front(win.hwnd):
            log(f"{win.name}: equip/rotation deferred; foreground activation was not confirmed")
            return "skipped"
        sleep(0.3)
    if (popup_state(win) if known_popup_state is None and want else known_popup_state):
        log(f"{win.name}: rotation paused while a popup covers the game")
        return "skipped"
    if win.hwnd in getattr(_tl, "manual_fallback", {}):
        return manual_fallback_state(win, want)
    # Putting away a confirmed selected character does not need its mutation.
    failure_report = {}
    # Idle recovery must prepare mutation targets too. Reading selection alone
    # used to clear the pending scan without preparing a slot for the next event.
    cards = stable_hotbar(win, read_labels=want or getattr(_tl, "automation", False),
                          failure_report=failure_report)
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
    if want and target > 0 and getattr(_tl, "automation", False):
        return event_equip_slot(win, target)
    if getattr(_tl, "automation", False):
        return ensure_state(win, False)  # idle or all Dracula: one cleanup authority
    raise RuntimeError("Rotation actions require initialized input tracking")


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
    guard_window(win)
    urgent = getattr(_tl, "event_cleanup", False) or getattr(_tl, "event_input", False)
    for _ in range(0 if urgent else 3):
        if win32gui.GetForegroundWindow() == win.hwnd:
            break
        log(f"  {win.name}: not focused yet (focus is on '{foreground_title()}'), trying again")
        focus(win)
        sleep(1.0)
    check_stop()
    if win32gui.GetForegroundWindow() != win.hwnd:
        raise RuntimeError(f"{win.name}: key press skipped because focus was not acquired")
    key = key or S["char_key"]
    guard_window(win)
    if urgent:
        tap_key(key, hold=CLEANUP_KEY_HOLD)
    else:
        tap_key(key)
    log(f"  {win.name}: {label} (pressed {key} once)")


def send_tracked_key(win, label, key, accepted):
    """Commit the cleanup hint at key-down, even if a later release fails."""
    previous = getattr(_tl, "on_key_down", None)
    recorded = False
    def receipt():
        nonlocal recorded
        if not recorded:
            accepted()
            recorded = True
    _tl.on_key_down = receipt
    try:
        press_char(win, label, key=key)
        receipt()  # alternate input backends may acknowledge only on return
    finally:
        _tl.on_key_down = previous


def event_equip_allowed(win):
    """Recheck the latched end as well as the current banner before any equip."""
    check_stop()
    return (SHARED["want"] and not SHARED.get("event_ending")
            and SHARED.get("end_seq", 0) <= SHARED.get("handled_end_seq", 0)
            and win.hwnd not in getattr(_tl, "putaway_pending", {}))


def event_slot_observation(win, target):
    """Fresh selection and card count; None means hidden/ambiguous, never empty."""
    cards, _ = hotbar_snapshot(win, read_labels=False)
    if not hotbar_visible(win, cards):
        return None
    target_card = next((c for c in cards if c.number == target), None)
    if target_card is None or target_card.kind != "character":
        return None
    selected = [c for c in cards if c.equipped]
    if len(selected) > 1 or any(c.kind == "unknown" for c in selected):
        return None
    return (selected[0].number if selected else 0, len(cards))


def confirm_event_equip(win, entry):
    if not event_equip_allowed(win):
        return "skipped"
    target = entry["target"]
    _tl.commanded_slots[win.hwnd] = target
    fallback = getattr(_tl, "manual_fallback", {}).get(win.hwnd)
    if fallback is not None:
        fallback["equipped"] = True
    elapsed = (time.monotonic()-entry["since"])*1000
    acknowledgement = ((time.monotonic()-entry["input_at"])*1000
                       if entry.get("input_at") is not None else 0)
    log(f"{win.name}: EQUIP CONFIRMED visually after {elapsed:.0f} ms • slot {target} "
        f"({entry['attempts']} input attempt(s), {acknowledgement:.0f} ms since last input, event {entry['end_seq']})")
    UI.put(("state", win.slot, True))
    UI.put(("rotation", win.slot, f"Slot {target} • equip confirmed"))
    return "fixed"


def event_equip_slot(win, target, allow_hidden_first=False):
    """Select once, verify two fresh frames, and retain missed inputs for retry.

    A sent command is only a cleanup hint. It never satisfies confirmation.
    The chosen smart slot is kept for this event so retries need no mutation OCR.
    """
    if not event_equip_allowed(win):
        return "skipped"
    entries = getattr(_tl, "event_equips", None)
    if entries is None:
        entries = _tl.event_equips = {}
    entry = entries.setdefault(win.hwnd, {
        "target": target, "attempts": 0, "sent_at": 0.0,
        "allow_hidden_first": allow_hidden_first,
        "end_seq": SHARED.get("end_seq", 0),
        "since": SHARED.get("started_at") or time.monotonic()})
    if entry["end_seq"] != SHARED.get("end_seq", 0):
        return "skipped"
    target = entry["target"]
    if entry["attempts"]:
        # The observation checks ownership of the actual cards. Unused strip
        # margins may overlap another window without obscuring the hotbar.
        first = event_slot_observation(win, target)
        if first is not None and first[0] == target:
            sleep(EQUIP_SAMPLE_SECONDS)
            if event_slot_observation(win, target) == first:
                return confirm_event_equip(win, entry)
        if first is not None and time.monotonic()-entry["sent_at"] < EQUIP_RETRY_SECONDS:
            return "waiting"  # no reason to steal focus when no input is due
    if not cleanup_focus(win):
        entry["reason"] = "Windows did not grant foreground focus"
        return "skipped"
    # Event actions use verified foreground ownership and a short render grace,
    # never the multi-second delay configured for ordinary maintenance.
    first = event_slot_observation(win, target)
    sleep(EQUIP_SAMPLE_SECONDS)
    second = event_slot_observation(win, target)
    if first is not None and first == second and first[0] == target:
        return confirm_event_equip(win, entry)
    readable_absence = first is not None and first == second and first[0] != target
    hidden_first = (entry["allow_hidden_first"] and not entry["attempts"]
                    and first is None and second is None)
    if not (readable_absence or hidden_first):
        entry["reason"] = "hotbar hidden or unreadable" if first is None or second is None else "selection changed between frames"
        UI.put(("state", win.slot, None))
        if first is not None and second is not None:
            return verify_event_selection(win, entry)
        return "skipped"
    if entry["attempts"] and time.monotonic()-entry["sent_at"] < EQUIP_RETRY_SECONDS:
        return "waiting"
    # One last fresh frame guards against a delayed prior input arriving while
    # we were collecting the two absence samples. Unknown is never retry proof.
    latest = event_slot_observation(win, target)
    if (readable_absence and latest != second) or (hidden_first and latest is not None):
        entry["reason"] = "selection changed just before input"
        return "skipped"
    if not event_equip_allowed(win):
        return "skipped"
    key = SLOT_KEYS[target-1]
    def accepted():
        now = time.monotonic()
        entry.update(attempts=entry["attempts"]+1, sent_at=now, input_at=now)
        _tl.commanded_slots[win.hwnd] = target
        _tl.last_character_keys[win.hwnd] = key
    send_tracked_key(win, f"{'retry' if entry['attempts'] else 'select'} event slot {target}", key, accepted)
    entry["sent_at"] = time.monotonic()
    elapsed_ms = (time.monotonic()-entry["since"])*1000
    log(f"{win.name}: equip input sent after {elapsed_ms:.0f} ms • slot {target}; awaiting visual confirmation")
    UI.put(("state", win.slot, None))
    UI.put(("rotation", win.slot, f"Slot {target} • verifying equip"))
    # Most games acknowledge within a frame or two. Finish this short transaction
    # while foreground, rather than forcing a second sweep over overlapping HUDs.
    # A missing acknowledgement has a strict bound so peers still receive input.
    return verify_event_selection(win, entry)


def verify_event_selection(win, entry):
    """A brief local confirmation window, without sending another key."""
    target = entry["target"]
    previous = None
    deadline = time.monotonic()+EQUIP_CONFIRM_SECONDS
    while True:
        if not event_equip_allowed(win):
            return "skipped"
        current = event_slot_observation(win, target)
        if current is not None and current == previous and current[0] == target:
            return confirm_event_equip(win, entry)
        previous = current  # an unreadable frame breaks consecutive confirmation
        remaining = deadline-time.monotonic()
        if remaining <= 0 or current is None:
            break
        sleep(min(EQUIP_SAMPLE_SECONDS, remaining))
    entry["reason"] = "hotbar hidden or unreadable" if current is None else "target highlight not confirmed"
    return "sent" if entry["attempts"] else "failed"


def prepared_event_equip(win):
    """Use an idle scan's candidate only after fresh size/card-type/mutation checks.

    A prepared slot is not proof of equipment or permission to use stale labels.
    Red/ambiguous labels defer OCR until after peers receive their fast inputs.
    """
    plan = getattr(_tl, "prepared_equips", {}).get(win.hwnd)
    if plan is None or plan["size"] != (win.w, win.h):
        return None
    if not cleanup_focus(win):
        return "skipped"
    cards, img = hotbar_snapshot(win, read_labels=False)
    if not hotbar_visible(win, cards):
        return "skipped"
    if tuple(c.kind for c in cards) != plan["kinds"]:
        return None
    if plan.get("signature") != card_layout_signature(cards):
        getattr(_tl, "prepared_equips", {}).pop(win.hwnd, None)
        return None
    target = plan["target"]
    card = next((c for c in cards if c.number == target and c.kind == "character"), None)
    if card is None:
        return None
    mutation, _ = read_mutation(img, card.box, allow_ocr=False)
    if mutation is not False:
        getattr(_tl, "prepared_equips", {}).pop(win.hwnd, None)
        return None
    return event_equip_slot(win, target)


def scan_mutations_offscreen(img, cards, cancel):
    """Analyze an immutable crop only. This worker never captures or sends input."""
    _tl.stop = cancel
    try:
        for card in cards[1:]:
            check_stop()
            if card.kind == "unknown":
                break
            if card.kind == "character":
                card.dracula, card.text = read_mutation(img, card.box)
                if card.dracula is not True:
                    break  # later slots cannot change the first eligible target
        return cards
    finally:
        _tl.stop = None


def clear_event_scans():
    for scan in getattr(_tl, "rotation_scans", {}).values():
        scan["cancel"].set()
        scan["future"].cancel()
    getattr(_tl, "rotation_scans", {}).clear()


def event_rotation_scan(win):
    """Capture once, yield foreground while OCR runs, then validate fresh pixels."""
    if not event_equip_allowed(win):
        return "skipped"
    if not hasattr(_tl, "rotation_scans"):
        _tl.rotation_scans = {}
    scans = _tl.rotation_scans
    waits = getattr(_tl, "hotbar_waits", None)
    if waits is None:
        waits = _tl.hotbar_waits = {}
    now = time.monotonic()
    wait = waits.setdefault(win.hwnd, {"slot": win.slot, "since": now, "attempts": 0})
    scan = scans.get(win.hwnd)
    if scan is not None:
        if (scan["end_seq"] != SHARED.get("end_seq", 0) or scan["size"] != (win.w, win.h)):
            scan["cancel"].set(); scan["future"].cancel()
            scans.pop(win.hwnd, None)
            return "needs_scan"
        if not scan["future"].done():
            UI.put(("rotation", win.slot, "Reading mutation labels • other windows continue"))
            return "scanning"  # importantly, no focus request here
        scans.pop(win.hwnd, None)
        try:
            scanned = scan["future"].result()
        except StopMacro:
            return "skipped"
        except Exception as exc:
            log(f"{win.name}: background mutation scan will retry ({type(exc).__name__})")
            scanned = None
        if scanned is not None:
            if not cleanup_focus(win):
                return "skipped"
            fresh, _ = hotbar_snapshot(win, read_labels=False)
            if (hotbar_visible(win, fresh) and card_layout_signature(fresh) == scan["signature"]
                    and event_equip_allowed(win)):
                for current, old in zip(fresh, scanned):
                    current.dracula, current.text = old.dracula, old.text
                target = choose_character(fresh)
                if target is not None:
                    waits.pop(win.hwnd, None)
                    publish_progress(win, fresh)
                    return event_equip_slot(win, target) if target > 0 else ensure_state(win, False)
        UI.put(("rotation", win.slot, "Scan changed or unreadable • will retry"))
    if now-wait["since"] >= 40 and wait["attempts"] >= 3:
        return activate_manual_fallback(win, True)
    if now < wait.get("retry_at", 0):
        return "scanning"
    wait["attempts"] += 1
    wait["retry_at"] = now+2
    if not cleanup_focus(win):
        return "skipped"
    cards, img = hotbar_snapshot(win, read_labels=False)
    if not hotbar_visible(win, cards):
        return "skipped"
    cancel = threading.Event()
    signature = card_layout_signature(cards)
    # Capture memory is independent of the next frame and all UI previews.
    future = ROTATION_EXECUTOR.submit(scan_mutations_offscreen, img.copy(), cards, cancel)
    if future is None:
        return "scanning"  # pool is bounded; never queue unlimited stale images
    scans[win.hwnd] = {"future": future, "cancel": cancel, "signature": signature,
                      "size": (win.w, win.h), "end_seq": SHARED.get("end_seq", 0)}
    UI.put(("rotation", win.slot, "Reading mutation labels • other windows continue"))
    return "scanning"


def equip_character(win):
    if win.hwnd in getattr(_tl, "putaway_pending", {}):
        log(f"{win.name}: previous unequip remains unconfirmed; skipping this event's equip")
        return "skipped"
    if getattr(_tl, "automation", False):
        if not event_equip_allowed(win):
            return "skipped"
        entry = getattr(_tl, "event_equips", {}).get(win.hwnd)
        if entry is not None:
            return event_equip_slot(win, entry["target"])
    if S["dracula_rotation"]:
        if getattr(_tl, "automation", False):
            if win.hwnd in getattr(_tl, "manual_fallback", {}):
                return manual_fallback_state(win, True)
            if win.hwnd in getattr(_tl, "rotation_scans", {}):
                return event_rotation_scan(win)
            result = prepared_event_equip(win)
            if result is not None:
                return result
            if SHARED.get("equipping"):
                # Missing or changed plans must not hold up other first inputs.
                return "needs_scan"
            return event_rotation_scan(win)
        return rotation_state(win, True)
    if getattr(_tl, "automation", False):
        return event_equip_slot(win, SLOT_KEYS.index(str(S["char_key"]))+1,
                                allow_hidden_first=True)
    raise RuntimeError("Use the event diagnostic to initialize confirmed input tracking")


def attempt_event_equip(win):
    """Retry unconfirmed windows; successful visual confirmations are terminal."""
    pending = _tl.equip_pending
    if not SHARED["want"] or SHARED.get("event_ending"):
        return
    previous_fast = getattr(_tl, "event_input", False)
    _tl.event_input = True
    try:
        result = equip_character(win)
    except (StopMacro, Preempt, WindowUnavailable):
        raise
    except pytesseract.TesseractNotFoundError:
        raise
    except Exception as exc:
        log(f"{win.name}: event equip deferred ({type(exc).__name__}); retrying this window")
        result = "skipped"
    finally:
        _tl.event_input = previous_fast
    check_stop()  # retain the input hint, then yield immediately if the event ended
    if result in ("skipped", "failed", "sent", "needs_scan", "waiting", "scanning"):
        entry = pending.setdefault(win.hwnd, {"slot": win.slot, "attempts": 0})
        entry["attempts"] += 1
        delay = (.20 if result == "scanning" else EQUIP_SAMPLE_SECONDS if result == "needs_scan" else
                 EQUIP_UNREADABLE_SECONDS if result == "skipped" else EQUIP_RETRY_SECONDS)
        if result in ("sent", "waiting"):
            command = _tl.event_equips[win.hwnd]
            delay = max(EQUIP_SAMPLE_SECONDS,
                        command["sent_at"]+EQUIP_RETRY_SECONDS-time.monotonic())
        entry["retry_at"] = time.monotonic()+delay
        command = getattr(_tl, "event_equips", {}).get(win.hwnd, {})
        reason = command.get("reason", {"needs_scan": "fresh mutation scan required",
                    "scanning": "background mutation scan pending",
                    "skipped": "focus or hotbar unavailable", "waiting": "waiting for late input"}.get(result,
                    "selection is ambiguous"))
        if reason != entry.get("reason") or time.monotonic() >= entry.get("log_at", 0):
            log(f"{win.name}: event equip pending • {reason}; "
                f"{command.get('attempts', 0)} key input(s), next check in {delay:.2f}s")
            entry.update(reason=reason, log_at=time.monotonic()+5)
        UI.put(("rotation", win.slot, "Event equip pending • retrying"))
    else:
        pending.pop(win.hwnd, None)
        log(f"{win.name}: event equip pass complete ({result or 'input sent'})")


def retry_event_equips(slots):
    """Service a short batch, then expose the banner; cleanup preempts all waits."""
    pending = getattr(_tl, "equip_pending", {})
    if not SHARED["want"] or SHARED.get("event_ending"):
        pending.clear()
        return
    started = time.monotonic()
    serviced = False
    try:
        # Verification first: missing mutation scans must not delay acknowledgements.
        due = sorted(list(pending.items()), key=lambda item:
                     (item[0] not in getattr(_tl, "event_equips", {}), item[1]["retry_at"]))
        for hwnd, entry in due:
            now = time.monotonic()
            if slots.is_invalid(entry["slot"]):
                pending.pop(hwnd, None)
                continue
            if now < entry["retry_at"]:
                continue
            win = slots.win(entry["slot"])
            if win is None or win.hwnd != hwnd:
                pending.pop(hwnd, None)
                continue
            if hwnd in getattr(_tl, "putaway_pending", {}):
                entry["retry_at"] = now+EQUIP_UNREADABLE_SECONDS
                continue
            try:
                serviced = True
                with window_task(slots, win), preemptible():
                    attempt_event_equip(win)
            except WindowUnavailable:
                pending.pop(hwnd, None)
            if time.monotonic()-started >= EQUIP_BATCH_SECONDS:
                break
    finally:
        SHARED["equipping"] = False
        if serviced:
            restore_main(slots)


def unequip_character(win):
    """Diagnostic put-away; the running macro uses confirmed priority cleanup."""
    if getattr(_tl, "automation", False):
        if not hasattr(_tl, "putaway_pending"):
            _tl.putaway_pending = {}
        now = time.monotonic()
        pending = _tl.putaway_pending.setdefault(win.hwnd, {
            "slot": win.slot, "since": now, "sent_at": 0.0, "attempts": 0,
            "observed": None, "observed_at": 0.0, "next_check": 0.0, "warn_at": now+2})
        previous = getattr(_tl, "event_cleanup", False)
        _tl.event_cleanup = True
        try:
            cleanup_one_window(win, pending, first=True)
        finally:
            _tl.event_cleanup = previous
        return "pending" if win.hwnd in _tl.putaway_pending else "fixed"
    raise RuntimeError("Use the event diagnostic to initialize confirmed input tracking")


def run_on_all(slots, fn):
    origin = pyautogui.position()
    try:
        for w in slots.all():
            try:
                with window_task(slots, w):
                    guard_window(w)
                    fn(w)
            except WindowUnavailable:
                continue
    finally:
        if not STOP.is_set():
            restore_main(slots)
        pyautogui.moveTo(origin.x, origin.y)


def known_exit_tool(img, box):
    """Match only the rod/bat artwork positively identified in supplied captures."""
    import base64
    x, y, w, h = box
    margin = max(3, round(min(w, h)*.14))
    crop = img[y+margin:y+h-margin, x+margin:x+w-margin]
    if not crop.size:
        return False
    icon = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA)
    for encoded in EXIT_TOOL_ICONS:
        template = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_GRAYSCALE)
        if float(cv2.matchTemplate(icon, template, cv2.TM_CCOEFF_NORMED)[0, 0]) >= .93:
            return True
    return False


def remember_exit_key(win):
    """Recognize the reserved slot-1 rod/bat once, outside event cleanup.

    Repeating this key can select or put away a tool, but cannot select a
    character. Do not treat arbitrary consumables as safe replacement tools.
    """
    cards, img = hotbar_snapshot(win, read_labels=False)
    if not hotbar_visible(win, cards) or cards[0].kind != "item":
        return
    x, y, w, h = cards[0].box
    label = img[max(0, y-round(h*.6)):y, max(0, x-3):x+w+3]
    if not label.size:
        return
    recognized = known_exit_tool(img, cards[0].box)
    text = "" if recognized else read_text(label, scale=5, n=1).lower()
    if recognized or re.search(r"\b(?:rod|bat)\b", text):
        if not hasattr(_tl, "exit_keys"):
            _tl.exit_keys = {}
        _tl.exit_keys[win.hwnd] = "1"
        if not hasattr(_tl, "exit_fingerprints"):
            _tl.exit_fingerprints = {}
        _tl.exit_fingerprints[win.hwnd] = ((win.w, win.h), cards[0].fingerprint)
        log(f"{win.name}: slot 1 tool recognized for repeatable event-end put-away")


def equipment_observation(win):
    """0 = visibly no character, number = selected character, None = unknown.

    No mutation OCR, no sleeps, and never infer 'put away' from an empty or
    obscured hotbar capture. Unknown card types cannot confirm a safe state.
    """
    cards, _ = hotbar_snapshot(win, read_labels=False)
    if not hotbar_visible(win, cards):
        return None
    proof = getattr(_tl, "exit_fingerprints", {}).get(win.hwnd)
    if proof and proof != ((win.w, win.h), getattr(cards[0], "fingerprint", b"")):
        getattr(_tl, "exit_keys", {}).pop(win.hwnd, None)
        _tl.exit_fingerprints.pop(win.hwnd, None)
        log(f"{win.name}: slot 1 changed; safe-tool shortcut invalidated")
    selected = [c for c in cards if c.equipped]
    if len(selected) > 1:
        return None
    if not selected:
        return 0
    card = selected[0]
    if card.kind == "character":
        return card.number
    if card.kind == "item":
        return 0
    return None


def confirm_putaway(win, pending):
    _tl.commanded_slots[win.hwnd] = 0
    fallback = getattr(_tl, "manual_fallback", {}).get(win.hwnd)
    if fallback is not None:
        fallback["equipped"] = False
    _tl.putaway_pending.pop(win.hwnd, None)
    elapsed = (time.monotonic()-pending["since"])*1000
    log(f"{win.name}: UNEQUIP CONFIRMED visually after {elapsed:.0f} ms "
        f"({pending['attempts']} input attempt(s))")
    UI.put(("state", win.slot, False))
    UI.put(("rotation", win.slot, "Unequip confirmed"))


def send_putaway(win, pending, key):
    def accepted():
        pending.update(sent_at=time.monotonic(), attempts=pending["attempts"]+1,
                       observed=None, observed_at=0.0)
    send_tracked_key(win, "priority put-away" if not pending["attempts"] else "retry unconfirmed put-away", key, accepted)
    pending["sent_at"] = time.monotonic()
    # Sending input does not prove that the game acted on it.
    log(f"{win.name}: put-away input sent {(pending['sent_at']-pending['since'])*1000:.0f} ms "
        "after cleanup request; awaiting visual confirmation")
    UI.put(("state", win.slot, None))
    UI.put(("rotation", win.slot, "Unequip sent • verifying"))
    confirm_putaway_in_place(win, pending)


def confirm_putaway_in_place(win, pending):
    """Two fresh clear frames in this visit; unknown never means put away."""
    deadline = time.monotonic()+CLEANUP_CONFIRM_SECONDS
    previous = None
    while True:
        check_stop()
        observed = equipment_observation(win)
        if observed == 0 and previous == 0:
            confirm_putaway(win, pending)
            return True
        remaining = deadline-time.monotonic()
        if remaining <= 0 or observed is None:
            pending["check_delay"] = (CLEANUP_UNREADABLE_SECONDS if observed is None
                                      else CLEANUP_RETRY_SECONDS)
            return False
        previous = observed
        sleep(min(CLEANUP_SAMPLE_SECONDS, remaining))


def cleanup_one_window(win, pending, first=False):
    guard_window(win)
    pending["check_delay"] = CLEANUP_SAMPLE_SECONDS
    safe_key = getattr(_tl, "exit_keys", {}).get(win.hwnd)
    retry_guard = CLEANUP_RETRY_SECONDS if safe_key else CLEANUP_TOGGLE_RETRY_SECONDS
    if not first:
        passive = equipment_observation(win)
        if passive == 0:
            sleep(CLEANUP_SAMPLE_SECONDS)
            if equipment_observation(win) == 0:
                confirm_putaway(win, pending)
                return
        remaining = pending["sent_at"]+retry_guard-time.monotonic()
        if passive is not None and pending["attempts"] and remaining > 0:
            pending["check_delay"] = max(CLEANUP_SAMPLE_SECONDS, remaining)
            return  # observe a late acknowledgement without another focus cycle
    if not cleanup_focus(win):
        pending["check_delay"] = CLEANUP_UNREADABLE_SECONDS
        return
    now = time.monotonic()
    first = first and pending["attempts"] == 0
    observed = equipment_observation(win)
    safe_key = getattr(_tl, "exit_keys", {}).get(win.hwnd)
    retry_guard = CLEANUP_RETRY_SECONDS if safe_key else CLEANUP_TOGGLE_RETRY_SECONDS
    if first and safe_key and observed != 0:
        send_putaway(win, pending, safe_key)
        return
    if observed is None:
        pending["check_delay"] = CLEANUP_UNREADABLE_SECONDS
    previous, sampled_at = pending["observed"], pending["observed_at"]
    repeated = observed is not None and previous == observed and now-sampled_at >= CLEANUP_SAMPLE_SECONDS
    if observed != previous or not sampled_at:
        pending.update(observed=observed, observed_at=now)
    if observed == 0:
        if not repeated:
            # Confirm while this window is already visible instead of making a
            # second full focus sweep just to collect the next clear frame.
            sleep(CLEANUP_SAMPLE_SECONDS)
            repeated = equipment_observation(win) == 0
        if repeated:
            confirm_putaway(win, pending)
        return
    if pending["attempts"] and now-pending["sent_at"] < retry_guard:
        pending["check_delay"] = max(CLEANUP_SAMPLE_SECONDS, pending["sent_at"]+retry_guard-now)
        return
    if safe_key:
        send_putaway(win, pending, safe_key)
    elif observed is not None:
        if not repeated:
            sleep(CLEANUP_SAMPLE_SECONDS)
            repeated = equipment_observation(win) == observed
        if not repeated:
            return
        # Re-read just before a toggle: a delayed previous command may have
        # cleared the highlight since the confirmation frames were taken.
        if equipment_observation(win) == observed:
            send_putaway(win, pending, SLOT_KEYS[observed-1])
    elif first and observed is None:
        # A catch animation can hide the hotbar. Make one best-effort toggle
        # using the tracked equip command, then require fresh evidence to retry.
        fallback = getattr(_tl, "manual_fallback", {}).get(win.hwnd)
        slot = getattr(_tl, "commanded_slots", {}).get(win.hwnd, 0)
        key = (fallback["key"] if fallback and fallback["equipped"] else
               SLOT_KEYS[slot-1] if slot else None)
        if key:
            send_putaway(win, pending, key)


def service_putaway(slots, first=False):
    """Round-robin recovery: one window never holds up the first pass on others."""
    pending_all = getattr(_tl, "putaway_pending", {})
    serviced = False
    _tl.event_cleanup = True
    try:
        for hwnd, pending in list(pending_all.items()):
            check_stop()
            if slots.is_invalid(pending["slot"]):
                pending_all.pop(hwnd, None)
                continue
            if not first and time.monotonic() < pending["next_check"]:
                continue
            win = slots.win(pending["slot"])
            if win is None:
                pending_all.pop(hwnd, None)
                continue
            try:
                serviced = True
                with window_task(slots, win):
                    cleanup_one_window(win, pending, first=first)
            except WindowUnavailable:
                pending_all.pop(hwnd, None)
            except StopMacro:
                raise
            except Exception as exc:
                pending["error"] = f"{type(exc).__name__}: {exc}"
            pending["next_check"] = time.monotonic()+pending.get("check_delay", CLEANUP_UNREADABLE_SECONDS)
            if hwnd in pending_all and time.monotonic() >= pending["warn_at"]:
                log(f"{win.name}: UNEQUIP UNCONFIRMED; continuing priority recovery. "
                    + pending.pop("error", "Waiting for readable hotbar confirmation."))
                UI.put(("state", win.slot, None))
                UI.put(("rotation", win.slot, "Unequip unconfirmed • retrying"))
                pending["warn_at"] = time.monotonic()+5
        # A blocking game dialog can swallow every key. Repair at most one
        # after the fast pass, and let a new event-end interrupt its OCR wait.
        if not first:
            for hwnd, pending in list(pending_all.items()):
                if time.monotonic() < pending.get("popup_at", pending["since"]+2):
                    continue
                pending["popup_at"] = time.monotonic()+5
                win = slots.win(pending["slot"])
                if win is not None:
                    try:
                        serviced = True
                        with window_task(slots, win), preemptible():
                            repair_cleanup_popup(win)
                    except WindowUnavailable:
                        pending_all.pop(hwnd, None)
                    except StopMacro:
                        raise
                    except Exception as exc:
                        log(f"{win.name}: blocking-popup recovery will retry ({type(exc).__name__})")
                break
    finally:
        _tl.event_cleanup = False
        if serviced:
            restore_main(slots)
        SHARED["event_priority"] = bool(SHARED["want"] or SHARED["holding"] or
                                       SHARED.get("event_ending") or pending_all)
        remaining = len(pending_all)
        if getattr(_tl, "last_cleanup_count", None) != remaining:
            _tl.last_cleanup_count = remaining
            UI.put(("cleanup", remaining))


def finish_event(slots):
    """Start immediate cleanup, then retain pending windows until visually safe."""
    clear_event_scans()
    getattr(_tl, "equip_pending", {}).clear()  # old event must never equip after cleanup
    getattr(_tl, "event_equips", {}).clear()
    getattr(_tl, "prepared_equips", {}).clear()
    sequence = SHARED.get("end_seq", 0)
    if getattr(_tl, "cleanup_seq", -1) != sequence:
        _tl.cleanup_seq = sequence
        if not hasattr(_tl, "putaway_pending"):
            _tl.putaway_pending = {}
        now = time.monotonic()
        for win in slots.all():
            _tl.putaway_pending.setdefault(win.hwnd, {
                "slot": win.slot, "since": SHARED.get("ended_at") or now,
                "sent_at": 0.0, "attempts": 0, "observed": None, "observed_at": 0.0,
                "next_check": 0.0, "warn_at": now+2})
        service_putaway(slots, first=True)
    SHARED["handled_end_seq"] = sequence
    SHARED["holding"] = False
    SHARED["event_priority"] = bool(SHARED["want"] or SHARED.get("event_ending") or _tl.putaway_pending)


def repair_cleanup_popup(win):
    check_stop()
    if not cleanup_focus(win):
        return
    state = popup_state(win)
    if "robux" in state:
        close_robux_popup(win)
    elif "welcome" in state and S["close_popup"]:
        close_welcome_popup(win)
    elif "daily_rewards" in state and S.get("close_daily_rewards", True):
        close_daily_rewards(win, cleanup=True)


def check_idle_equipment(slots):
    """Read exposed hotbars passively; only reveal covered ones on a slower audit."""
    now = time.monotonic()
    audit_due = now >= getattr(_tl, "idle_focus_audit_at", 0.0)
    moved_focus = False
    try:
        for win in slots.all():
            try:
                with window_task(slots, win):
                    if not region_visible(win, MUTATION_REGION):
                        if not audit_due:
                            continue
                        moved_focus = True
                        if not cleanup_focus(win):
                            continue
                    observed = equipment_observation(win)
                    if observed is None or observed <= 0:
                        continue
                    now = time.monotonic()
                    _tl.putaway_pending.setdefault(win.hwnd, {
                        "slot": win.slot, "since": now, "sent_at": 0.0, "attempts": 0,
                        "observed": None, "observed_at": 0.0, "next_check": 0.0, "warn_at": now+2})
                    log(f"{win.name}: character visible outside Hallows' Eve; priority put-away recovery")
            except WindowUnavailable:
                continue
    finally:
        if audit_due:
            # Schedule from completion, so a slow scan cannot immediately repeat.
            _tl.idle_focus_audit_at = time.monotonic()+IDLE_FOCUS_AUDIT_SECONDS
        if moved_focus:
            restore_main(slots)


def ensure_state(win, want, known_popup_state=None):
    """
    Route corrections through the same confirmed input paths as event actions.
    A selected tool is a safe character state; an unreadable hotbar stays unknown.
    """
    if getattr(_tl, "automation", False):
        if want:
            return equip_character(win)
        observed = equipment_observation(win)
        if (win.hwnd in getattr(_tl, "putaway_pending", {}) or
                (observed is not None and observed > 0) or
                (observed is None and getattr(_tl, "commanded_slots", {}).get(win.hwnd, 0))):
            return unequip_character(win)
        if observed is None:
            return "skipped"
        sleep(CLEANUP_SAMPLE_SECONDS)
        if equipment_observation(win) != 0:
            return "skipped"
        _tl.commanded_slots[win.hwnd] = 0
        fallback = getattr(_tl, "manual_fallback", {}).get(win.hwnd)
        if fallback is not None:
            fallback["equipped"] = False
        UI.put(("state", win.slot, False))
        return "ok"
    raise RuntimeError("State corrections require initialized input tracking")


def close_welcome_popup(win):
    if not focus(win) or "welcome" not in popup_state(win):
        return False
    point = (win.left+int(win.w*WELCOME_CLOSE[0]), win.top+int(win.h*WELCOME_CLOSE[1]))
    if not verified_close_marker(win, point):
        return False
    click_abs(win, *point, validator=lambda: verified_close_marker(win, point))
    return True


def x_glyph_present(img):
    """Require both diagonals of a small light/dark X, not a solid button."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    yy, xx = np.indices((15,15))
    diagonal_a, diagonal_b = abs(xx-yy)<=2, abs(xx+yy-14)<=2
    for mask in ((gray>=180).astype(np.uint8), (gray<=90).astype(np.uint8)):
        _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        for index, (x,y,w,h,area) in enumerate(stats[1:],1):
            if not (5<=w<img.shape[1]*.85 and 5<=h<img.shape[0]*.85 and .7<=w/h<=1.4):
                continue
            glyph = cv2.resize((labels[y:y+h,x:x+w]==index).astype(np.uint8), (15,15),
                               interpolation=cv2.INTER_NEAREST)>0
            ink = int(glyph.sum())
            if (ink and (glyph & (diagonal_a|diagonal_b)).sum()/ink >= .85
                    and glyph[diagonal_a].mean() >= .60 and glyph[diagonal_b].mean() >= .60):
                return True
    return False


def verified_close_marker(win, point):
    x,y = point
    radius = max(12, round(win.w*.02))
    region = ((x-win.left-radius)/win.w, (y-win.top-radius)/win.h,
              (x-win.left+radius)/win.w, (y-win.top+radius)/win.h)
    if min(region)<0 or max(region)>1 or not region_visible(win, region):
        return False
    img = grab(win, region)
    return region_visible(win, region) and x_glyph_present(img)


def daily_rewards_x(img):
    """Recognize a white X inside a red square in the popup's heading strip."""
    import base64
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 130, 120]), np.array([12, 255, 255]))
    red |= cv2.inRange(hsv, np.array([170, 130, 120]), np.array([179, 255, 255]))
    _, _, stats, _ = cv2.connectedComponentsWithStats(red)
    template = cv2.imdecode(np.frombuffer(base64.b64decode(DAILY_CLOSE_PNG), np.uint8), cv2.IMREAD_GRAYSCALE)
    candidates = []
    for x, y, w, h, area in stats[1:]:
        if not (x > img.shape[1]*.65 and .018*img.shape[1] <= w <= .08*img.shape[1]
                and .75 <= w/max(h, 1) <= 1.3 and area > w*h*.45):
            continue
        white = cv2.inRange(img[y:y+h, x:x+w], np.array([175]*3), np.array([255]*3))
        white = cv2.resize(white, (32, 32), interpolation=cv2.INTER_AREA)
        score = float(cv2.matchTemplate(white, template, cv2.TM_CCOEFF_NORMED)[0, 0])
        if score >= .80:
            candidates.append((int(x+w//2), int(y+h//2)))
    return candidates[0] if len(candidates) == 1 else None


def daily_rewards_close_point(img):
    point = daily_rewards_x(img)
    if point is None:
        return None  # normal frames cost only the small visual check, no OCR
    # Read the heading left of the X, never the reward or paid skip buttons.
    title = img[:min(img.shape[0], point[1]+20), :max(1, point[0]-int(img.shape[1]*.08))]
    white = cv2.inRange(title, np.array([175]*3), np.array([255]*3))
    text = ocr(cv2.resize(255-white, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), config="--psm 11")
    words = re.findall(r"[a-z]+", text.lower())
    # Tesseract sometimes reads the trailing exclamation mark as a lowercase L.
    return point if re.search(r"\bdaily\s+rewardsl?\b", " ".join(words)) else None


def close_daily_rewards(win, cleanup=False):
    """Occasional idle-only check; click only a freshly verified Daily Rewards X."""
    if (SHARED.get("event_priority") and not cleanup) or SHARED["want"] or SHARED["holding"]:
        return False
    if not region_visible(win, DAILY_REWARDS_REGION):
        return False
    point = daily_rewards_close_point(grab(win, DAILY_REWARDS_REGION))
    if point is None:
        return False
    check_stop()
    if (SHARED.get("event_priority") and not cleanup) or not region_visible(win, DAILY_REWARDS_REGION):
        return False
    # OCR can take time: recognize the same title and X again on a fresh frame.
    current = daily_rewards_close_point(grab(win, DAILY_REWARDS_REGION))
    if current is None or max(abs(a-b) for a, b in zip(point, current)) > 3:
        return False
    check_stop()
    if (SHARED.get("event_priority") and not cleanup) or SHARED["want"] or SHARED["holding"]:
        return False
    x = win.left + int(win.w*DAILY_REWARDS_REGION[0]) + current[0]
    y = win.top + int(win.h*DAILY_REWARDS_REGION[1]) + current[1]
    guard_window(win)
    if _root_at(x, y) != win.hwnd:
        return False
    # A direct verified close avoids the longer hover gesture used by game menus.
    pyautogui.moveTo(x, y, duration=.08)
    check_stop()
    if ((SHARED.get("event_priority") and not cleanup) or SHARED["want"] or SHARED["holding"]
            or _root_at(x, y) != win.hwnd):
        return False
    guard_window(win)
    hold_click()
    log(f"{win.name}: Daily Rewards popup -> clicked the verified red X")
    sleep(.2)
    return True


def check_daily_rewards(win):
    if not S.get("close_daily_rewards", True) or SHARED.get("event_priority"):
        return False
    due = getattr(_tl, "daily_rewards_due", None)
    if due is None:
        due = _tl.daily_rewards_due = {}
    if time.monotonic() < due.get(win.hwnd, 0):
        return False
    due[win.hwnd] = time.monotonic() + DAILY_REWARDS_SECONDS
    return close_daily_rewards(win)


def click_abs(win, x, y, hold=0.1, validator=None):
    """Click a screen point. First makes sure no other window is on top of it."""
    guard_window(win)
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
    guard_window(win)
    def before_down():
        check_stop()
        guard_window(win)
        if _root_at(x,y) != win.hwnd or (validator is not None and not validator()):
            raise FrameUnavailable(f"{win.name}: click target changed during pointer movement")
    hover_click(x, y, hold, before_down=before_down)
    sleep(0.4)


def click_ratio(win, ratio, hold=0.1):
    click_abs(win, win.left + int(win.w * ratio[0]), win.top + int(win.h * ratio[1]), hold)


def save_rebirth_debug(win, note):
    """Save a screenshot of the window with the rebirth-icon click spot marked, plus what OCR read."""
    try:
        folder = os.path.join(APP_DIR, "rebirth_debug")
        os.makedirs(folder, exist_ok=True)
        if not region_visible(win, MENU_REGION):
            return
        img = grab(win, MENU_REGION).copy()
        cx, cy = int(win.w * REBIRTH_ICON[0]), int(win.h * REBIRTH_ICON[1])
        path = os.path.join(folder, f"rebirth_{win.slot + 1}_latest.png")
        cv2.imwrite(path, img)
        text = " ".join(read_text(grab(win, MENU_REGION), scale=2, n=2).split())[:90]
        log(f"  {win.name}: {note} | click spot ({win.left + cx},{win.top + cy}) | menu text read: {text!r}")
        log(f"  saved the latest menu crop: {path}")
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
        if "robux" not in popup_state(win):
            return True
        pt = robux_close_point(win)
        if pt is None or not verified_close_marker(win, pt):
            log(f"{win.name}: purchase dialog close control unconfirmed; no click sent")
            return False
        log(f"{win.name}: Robux purchase prompt -> closing it with the X (try {attempt + 1}/4)")
        if attempt:
            focus(win)
        click_abs(win, pt[0], pt[1], validator=lambda: verified_close_marker(win, pt))
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
    if "daily_rewards" in st:
        return False  # the occasional maintenance check owns this popup
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


def anti_idle_pulse(win):
    """Short foreground jump request; never select a slot or click game controls."""
    if not cleanup_focus(win):
        return False
    check_stop()
    guard_window(win)
    if win32gui.GetForegroundWindow() != win.hwnd:
        return False
    # A fresh transition must take precedence even after foreground activation.
    if (SHARED["want"] != SHARED["holding"] or
            SHARED.get("end_seq", 0) > SHARED.get("handled_end_seq", 0)):
        raise Preempt()
    tap_key("space", hold=.12)
    return True  # OS input completed, not proof of a jump or server idle reset


def service_anti_idle(slots):
    """Service one due window between urgent actions, independently of OCR/maintenance."""
    if not S.get("afk_enabled", True):
        return
    if (SHARED["want"] != SHARED["holding"] or
            SHARED.get("end_seq", 0) > SHARED.get("handled_end_seq", 0)):
        return
    entries = getattr(_tl, "anti_idle", None)
    if entries is None:
        entries = _tl.anti_idle = {}
    now = time.monotonic()
    due = []
    for i in slots.active_indices():
        win = slots.win(i)
        if win is None:
            continue
        entry = entries.setdefault(win.hwnd, {"next_at": now, "last_sent": None})
        if now >= entry["next_at"]:
            due.append((entry["next_at"], i, win, entry))
    if not due:
        return
    _, _, win, entry = min(due, key=lambda row: row[:2])
    try:
        with window_task(slots, win), preemptible():
            if not anti_idle_pulse(win):
                raise RuntimeError("foreground focus was not confirmed")
        sent_at = time.monotonic()
        gap = (f"; {sent_at-entry['last_sent']:.0f}s since previous input"
               if entry["last_sent"] is not None else "; first input this run")
        entry.update(last_sent=sent_at, next_at=sent_at+float(S["afk_minutes"])*60)
        log(f"{win.name}: anti-idle input sent (Space; foreground verified{gap}); "
            f"next due in {float(S['afk_minutes']):g} min. Game idle reset is not visually confirmed.")
    except WindowUnavailable:
        entries.pop(win.hwnd, None)
    except StopMacro:
        raise
    except Exception as exc:
        # Never consume the full configured interval on refused/failed input.
        entry["next_at"] = time.monotonic()+10
        log(f"{win.name}: anti-idle deferred ({type(exc).__name__}: {exc}); retry in 10s")
    finally:
        restore_main(slots)
    return True


def check_window(slots, i, force_afk=False):
    """Bring window i to the front; close a Robux prompt (always) and the Welcome Back popup (if
    enabled). Anti-idle runs independently; force_afk is an explicit diagnostic."""
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
    if check_daily_rewards(w):
        state = {"changed"}  # do not reuse the pre-close popup read for verification
    elif "daily_rewards" in state:
        return state  # leave its reward controls alone until the scheduled close check
    if force_afk:
        sent = anti_idle_pulse(w)
        log(f"{w.name}: diagnostic anti-idle Space {'sent; check for a jump in Roblox' if sent else 'NOT sent; focus refused'}")
        return None  # input may have changed the UI; verification must read again
    # Only reuse a clear read when no popup was acted on and no game input followed it.
    return state if not state else None


def maintenance(slots, force_afk=False, want=None):
    """Popup maintenance and optional character-state check; idle input has its own schedule."""
    origin = pyautogui.position()
    try:
        for i in slots.active_indices():
            w = slots.win(i)
            if w is None:
                continue
            try:
                with window_task(slots, w):
                    state = check_window(slots, i, force_afk)
                    if want is not None and (S["verify_state"] or S["dracula_rotation"]):
                        ensure_state(w, want, known_popup_state=state)
            except WindowUnavailable:
                continue
    finally:
        restore_main(slots)
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
    """Limit diagnostic copies to 5 Hz; the detector still inspects every frame.

    Losing or regaining visibility is published immediately. A preview is never
    used as input to the event or equipment state machines.
    """
    now = time.monotonic()
    with DATA_LOCK:
        previous = PREVIEW.get(key)
        if previous and (previous[0] is None) == (img is None) and now-previous[2] < .20:
            return
        PREVIEW[key] = (img.copy() if img is not None else None, status, now)


def passive_window(slots, i):
    # Observation must never restore or focus a window behind the action worker.
    if i is None or slots.is_invalid(i):
        return None
    h = slots.hwnds[i]
    try:
        if not h or not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h):
            return None
        if win32gui.GetWindowText(h) != "Roblox" or win32gui.IsIconic(h):
            return None
        return Win(h, *_frame_rect(h), i)
    except Exception:
        # The HWND may disappear between any two Win32 calls.
        return None


def event_window(slots):
    """Promote a remaining window without stealing focus from the input worker."""
    for _ in range(len(slots)):
        i = slots.main_slot
        if i is None:
            return None
        win = passive_window(slots, i)
        if win is not None:
            return win
        slots.invalidate(i, "closed, minimized or unavailable")
    return None


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
    return bool(owners - {win.hwnd}) and owners.issubset({slots.hwnds[i] for i in slots.active_indices()})


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
    slots.restore_requested.clear()
    tried = set()
    for _ in range(len(slots)):
        win = event_window(slots)
        if win is None:
            return
        tried.add(win.slot)
        try:
            if region_visible(win, EVENT_REGION) or bring_to_front(win.hwnd):
                return
            # A foreground refusal is not proof of disconnection. Keep this
            # window eligible for cleanup while trying another banner source.
            remaining = [i for i in slots.active_indices() if i not in tried]
            if not remaining:
                slots.restore_requested.set()
                return
            with slots.lock:
                slots.main_slot = remaining[0]
            log(f"Event monitor moved to {CORNERS[slots.main_slot]} while another window awaits focus.")
        except WindowUnavailable:
            slots.restore_requested.set()


def title_mask(img):
    return cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2HSV),
                       np.array([5, 140, 160]), np.array([35, 255, 255]))


class BannerMatcher:
    _templates = None

    def __init__(self):
        import base64
        if BannerMatcher._templates is None:
            raw = np.frombuffer(base64.b64decode(EVENT_TEMPLATE_PNG), np.uint8)
            template = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
            templates = tuple(cv2.resize(template, None, fx=float(s), fy=float(s),
                              interpolation=cv2.INTER_LINEAR)
                              for s in np.concatenate((np.arange(0.60, 1.0, 0.02), np.arange(1.0, 1.81, 0.04))))
            for image in templates:
                image.setflags(write=False)
            BannerMatcher._templates = templates
        self.templates = BannerMatcher._templates
        self.last_match = None

    def score(self, img):
        mask = title_mask(img)
        if not cv2.countNonZero(mask):
            return 0.0
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


class EventTitleWatch:
    """Watch the confirmed orange title at capture scale, excluding lower timers.

    A reference template or OCR must first identify Hallows' Eve. This learned
    image is only evidence of its continued presence, never of a new event.
    """
    def __init__(self):
        self.template = None
        self.shape = None

    def learn(self, img):
        mask = title_mask(img)
        _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        glyphs = [(i, c) for i, c in enumerate(stats[1:], 1)
                  if 3 <= c[3] <= mask.shape[0]*.4 and 2 <= c[2] <= mask.shape[1]*.25
                  and c[4] >= 4]
        candidates = []
        for _, anchor in glyphs:
            line = [(i, c) for i, c in glyphs
                    if abs(c[1]+c[3]-anchor[1]-anchor[3]) <= max(2, anchor[3]*.20)
                    and anchor[3]*.55 <= c[3] <= anchor[3]*1.6]
            if len(line) < 3:
                continue
            line.sort(key=lambda item: item[1][0])
            if any(b[1][0]-a[1][0]-a[1][2] > anchor[3]*2.5 for a,b in zip(line,line[1:])):
                continue
            x = min(c[0] for _,c in line)
            y = min(c[1] for _,c in line)
            right = max(c[0]+c[2] for _,c in line)
            bottom = max(c[1]+c[3] for _,c in line)
            if right-x < max(25, mask.shape[1]*.12) or bottom-y < 5:
                continue
            if abs((x+right)/2-mask.shape[1]/2) > mask.shape[1]*.25:
                continue
            # Prefer the largest central text line over tiny bonus descriptions.
            candidates.append((int(sum(c[4] for _,c in line)), x,y,right,bottom))
        if not candidates:
            return False
        _,x,y,right,bottom = max(candidates)
        self.template = mask[max(0,y-1):min(len(mask),bottom+1),
                             max(0,x-1):min(mask.shape[1],right+1)].copy()
        self.shape = mask.shape
        return True

    def score(self, img):
        mask = title_mask(img)
        if self.template is None or self.shape != mask.shape:
            return None
        return float(cv2.minMaxLoc(cv2.matchTemplate(mask, self.template, cv2.TM_CCOEFF_NORMED))[1])


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
                                                     "User-Agent": "HallowsMacro/3.5.1"}, method="POST")
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
    slots = getattr(_tl, "run_slots", None)
    if slots is not None and slots.is_invalid(win.slot):
        return
    target = choose_character(cards)
    if (getattr(_tl, "automation", False) and not SHARED.get("holding")
            and target is not None and target > 0):
        if not hasattr(_tl, "prepared_equips"):
            _tl.prepared_equips = {}
        _tl.prepared_equips[win.hwnd] = {
            "target": target, "kinds": tuple(c.kind for c in cards),
            "signature": card_layout_signature(cards),
            "size": (win.w, win.h)}
    elif getattr(_tl, "automation", False) and not SHARED.get("holding"):
        getattr(_tl, "prepared_equips", {}).pop(win.hwnd, None)
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


def all_complete(slots, now):
    active = slots.active_indices()
    with DATA_LOCK:
        return bool(active) and all(i in PROGRESS and PROGRESS[i]["complete"]
                                   and now - PROGRESS[i]["at"] < 45 for i in active)


def validate_runtime_start(slots):
    """A resumed run must pass fresh checks before any game input is sent."""
    try:
        return validate_visible_windows(slots)
    finally:
        restore_main(slots)


def validate_visible_windows(slots):
    for i in slots.active_indices():
        win = reveal_for_scan(slots, i)
        if not win:
            if passive_window(slots, i) is None:
                slots.invalidate(i, "closed, minimized or unavailable")
            else:
                log(f"{CORNERS[i]}: focus unavailable at startup; keeping window eligible for recovery")
            continue
        try:
            with window_task(slots, win):
                if not validate_one_window(slots, win):
                    return False
        except WindowUnavailable:
            continue
    return bool(slots.active_indices())


def validate_one_window(slots, win):
    i = win.slot
    text = read_text(grab(win, POPUP_REGION), scale=1, n=1).lower() if region_visible(win, POPUP_REGION) else ""
    if disconnected_text(text):
        slots.invalidate(i, "Roblox disconnected")
        return True
    check_daily_rewards(win)
    remember_exit_key(win)
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
                return True
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
        _tl.run_slots = self.slots
        missing, ocr_due, error_due = {}, {}, {}
        try:
            while not STOP.is_set() and not self.stop.is_set():
                for i in self.slots.active_indices():
                    check_stop()
                    try:
                        win = passive_window(self.slots, i)
                        if win is None:
                            self.slots.invalidate(i, "closed, minimized or unavailable")
                            continue
                        now = time.monotonic()
                        if not SHARED.get("event_priority", False):
                            cards, img = hotbar_snapshot(win, read_labels=False)
                            visible = hotbar_visible(win, cards)
                            publish_preview(f"hotbar_{i}", img if visible else None,
                                            f"Window {i+1} • {len(cards)} visible slots" if visible else
                                            f"Window {i+1} • covered/unconfirmed; awaiting focused scan")
                            if not visible and S["dracula_rotation"] and SHARED.get("menu_window") != i:
                                if now-missing.get(i, -100) >= 20:
                                    log(f"{win.name}: background hotbar unconfirmed; will recheck when focused.")
                                    missing[i] = now
                            else:
                                missing.pop(i, None)
                        if now >= ocr_due.get(i, 0) and region_visible(win, POPUP_REGION):
                            text = read_text(grab(win, POPUP_REGION), scale=1, n=1).lower()
                            ocr_due[i] = time.monotonic() + CONNECTION_CHECK_SECONDS
                            current = passive_window(self.slots, i)
                            if current is None:
                                self.slots.invalidate(i, "closed, minimized or unavailable")
                                continue
                            if ((current.left, current.top, current.w, current.h) !=
                                    (win.left, win.top, win.w, win.h) or not region_visible(current, POPUP_REGION)):
                                continue
                            if disconnected_text(text):
                                self.slots.invalidate(i, "Roblox disconnected")
                    except StopMacro:
                        raise
                    except Exception as exc:
                        # A capture/OCR hiccup in one window must not end the run.
                        if passive_window(self.slots, i) is None:
                            self.slots.invalidate(i, "closed, minimized or unavailable")
                        elif time.monotonic() >= error_due.get(i, 0):
                            log(f"Window {i+1}: health check will retry ({type(exc).__name__}).")
                            error_due[i] = time.monotonic() + 20
                self.stop.wait(0.5)
        except StopMacro:
            pass
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


def read_countdown_image(img):
    b, g, r = (img[:, :, i].astype(np.int16) for i in range(3))
    green = (g > 130) & (g > r*1.2) & (g > b*1.2)
    if np.count_nonzero(green) < 20:
        return None
    text = ocr(cv2.resize((~green).astype(np.uint8)*255, None, fx=6, fy=6), config="--psm 11")
    match = re.search(r"duration\s*:\s*(\d{1,2}\s*:\s*\d{2}|\d{3,4})\b", text.lower())
    if not match:
        return None
    digits = re.sub(r"[^0-9]", "", match.group(1))
    minutes, seconds = int(digits[:-2]), int(digits[-2:])
    return minutes*60+seconds if seconds < 60 and minutes*60+seconds <= MAX_HOLD_SECONDS else None


class EventCountdown:
    """Two decreasing, time-consistent reads before trusting an end deadline."""
    def __init__(self):
        self.previous = None
        self.deadline = None

    def observe(self, seconds, captured_at):
        if seconds is None or not 0 <= seconds <= MAX_HOLD_SECONDS:
            return
        if self.previous is not None:
            at, before = self.previous
            elapsed, decrease = captured_at-at, before-seconds
            if elapsed <= 0:
                return
            if decrease == 0 and elapsed < 5:
                return  # waiting for a real decrement, not duplicate OCR
            if .4 <= elapsed <= 5 and decrease >= 1 and abs(elapsed-decrease) <= 1.25:
                estimate = captured_at+seconds
                self.deadline = estimate if self.deadline is None else min(self.deadline, estimate)
        self.previous = (captured_at, seconds)

    def due(self, now, lead):
        return lead > 0 and self.deadline is not None and now >= self.deadline-lead


class Detector(threading.Thread):
    def __init__(self, slots):
        super().__init__(daemon=True)
        self.slots, self.stop = slots, threading.Event()
        self.changed_at = 0.0
        self.ocr_requests = queue.Queue(maxsize=1)
        self.ocr_results = queue.Queue(maxsize=1)
        self.ocr_epoch = 0

    def fallback_worker(self):
        _tl.stop = self.stop
        _tl.run_slots = self.slots
        error_at = 0.0
        try:
            while not STOP.is_set() and not self.stop.is_set():
                try:
                    epoch, source_hwnd, kind = self.ocr_requests.get(timeout=0.1)
                except queue.Empty:
                    continue
                win = event_window(self.slots)
                read_region = EVENT_TIMER_REGION if kind == "timer" else EVENT_REGION
                if (win is None or win.hwnd != source_hwnd or not region_visible(win, EVENT_REGION)
                        or not region_visible(win, read_region)):
                    continue
                captured_at = time.monotonic()
                try:
                    if kind == "timer":
                        captured = grab(win, EVENT_TIMER_REGION)
                        present = read_countdown_image(captured)
                    else:
                        present, _, captured = read_event(win)
                except StopMacro:
                    raise
                except Exception as exc:
                    if passive_window(self.slots, win.slot) is None:
                        self.slots.invalidate(win.slot, "closed, minimized or unavailable")
                        continue
                    if time.monotonic() >= error_at:
                        log(f"Event OCR unavailable ({type(exc).__name__}); visual monitoring continues")
                        error_at = time.monotonic()+10
                    continue
                current = event_window(self.slots)
                if current is None or current.hwnd != win.hwnd or (current.left, current.top, current.w, current.h) != (win.left, win.top, win.w, win.h):
                    continue
                if region_visible(current, EVENT_REGION) and region_visible(current, read_region):
                    try:
                        self.ocr_results.get_nowait()
                    except queue.Empty:
                        pass
                    self.ocr_results.put_nowait((kind, captured_at, epoch, present, captured))
        except StopMacro:
            pass
        except Exception as exc:
            safety_pause(f"OCR fallback failed: {exc}")
        finally:
            close_capture()

    def run(self):
        _tl.stop = self.stop
        _tl.run_slots = self.slots
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

    def request_cleanup(self, now, reason):
        self.changed_at = time.time()
        SHARED.update(want=False, event_priority=True, ended_at=now,
                      ended_wall_at=self.changed_at, end_seq=SHARED.get("end_seq", 0)+1)
        self.ocr_epoch += 1
        log(f"Event cleanup requested • {reason}")

    def detect(self):
        matcher, state, watch = BannerMatcher(), EventDebouncer(), EventTitleWatch()
        fast = S.get("fast_detection", True)
        fallback_due = 0.0
        active_since = None
        unknown_since = None
        source_hwnd = None
        countdown, timer_due = EventCountdown(), 0.0
        lead = float(S.get("unequip_lead_seconds", 2.0))
        while not STOP.is_set() and not self.stop.is_set():
            started = time.monotonic()
            win = event_window(self.slots)
            if win is None:
                return  # Slots stops the run only when no usable window remains.
            if win.hwnd != source_hwnd:
                source_hwnd = win.hwnd
                self.ocr_epoch += 1
                matcher, watch = BannerMatcher(), EventTitleWatch()
                countdown, timer_due = EventCountdown(), 0.0
                state.update(None, started)  # retain the verdict until fresh frames agree
                fallback_due, unknown_since = 0.0, None
            if state.active and not SHARED.get("event_ending") and countdown.due(started, lead):
                self.request_cleanup(started, f"validated countdown • {lead:.1f}s safety margin")
                SHARED["event_ending"] = True
            if not region_visible(win, EVENT_REGION):
                state.update(None, started)
                publish_preview("banner", None, "Unable to read • banner covered; previous verdict retained")
                unknown_since = unknown_since if unknown_since is not None else started
                if state.active and started-unknown_since >= .6 and not SHARED.get("event_ending"):
                    self.request_cleanup(started, "banner visibility lost • putting characters away protectively")
                    SHARED["event_ending"] = True
                if started - unknown_since > 15 and not state.active:
                    safety_pause("Main event banner covered for 15 seconds. Arrange windows so it stays visible.")
                    return
                self.stop.wait(POLL_SECONDS)
                continue
            try:
                img = grab(win, EVENT_REGION)
            except StopMacro:
                raise
            except Exception:
                state.update(None, started)
                unknown_since = unknown_since if unknown_since is not None else started
                if state.active and started-unknown_since >= .6 and not SHARED.get("event_ending"):
                    self.request_cleanup(started, "banner capture unavailable • protective put-away")
                    SHARED["event_ending"] = True
                publish_preview("banner", None, "Capture unavailable • retrying")
                self.stop.wait(POLL_SECONDS)
                continue
            if not region_visible(win, EVENT_REGION):
                state.update(None, time.monotonic())
                self.stop.wait(POLL_SECONDS)
                continue

            score = watch.score(img) if state.active else None
            visual = score is not None
            if visual:
                # Confirm absence across fresh frames, without any OCR wait.
                present = score >= .72
            else:
                score = matcher.score(img) if fast else 0.0
                present = (True if score >= .78 else False if score < .58 else None) if fast else None
                visual = fast

            # OCR is always asynchronous, including when fast idle detection is
            # disabled. Positive OCR must match the CURRENT title image before
            # it can start an event; late results cannot revive an ended event.
            if not state.active or watch.template is None:
                if started >= fallback_due and (not fast or present is not True):
                    try:
                        self.ocr_requests.put_nowait((self.ocr_epoch, win.hwnd, "banner"))
                    except queue.Full:
                        pass
                    fallback_due = started + (8.0 if fast else .4)
            if state.active and not SHARED.get("event_ending") and lead > 0 and started >= timer_due:
                try:
                    self.ocr_requests.put_nowait((self.ocr_epoch, win.hwnd, "timer"))
                    timer_due = started+1.0
                except queue.Full:
                    pass
            try:
                kind, at, epoch, detected, captured = self.ocr_results.get_nowait()
                if kind == "timer":
                    if epoch == self.ocr_epoch and state.active and started-at < 5:
                        countdown.observe(detected, at)
                elif epoch == self.ocr_epoch and started-at < OCR_TIMEOUT*2+1:
                    candidate = EventTitleWatch()
                    if detected and candidate.learn(captured):
                        current_score = candidate.score(img)
                        if current_score is not None and current_score >= .85:
                            watch = candidate
                            present, score, visual = True, current_score, True
                    elif not detected and not visual and started-at < 1.0:
                        present = False
            except queue.Empty:
                pass

            # Keep a confirmed candidate through the start debounce. This lets
            # one OCR result lead into fast frame checks without repeated OCR.
            if not state.active and watch.template is not None:
                score = watch.score(img)
                if score is not None:
                    present, visual = score >= .72, True
                else:
                    present = None
                if present is False:
                    watch = EventTitleWatch()
                    self.ocr_epoch += 1
            if present is True and watch.template is None:
                watch.learn(img)

            now = time.monotonic()
            if present is None:
                unknown_since = unknown_since if unknown_since is not None else now
                if state.active and now-unknown_since >= .6 and not SHARED.get("event_ending"):
                    self.request_cleanup(now, "event banner unreadable • protective put-away")
                    SHARED["event_ending"] = True
                if now - unknown_since > 15 and not state.active:
                    safety_pause("Event banner remained ambiguous for 15 seconds. Run guided setup.")
                    return
            else:
                unknown_since = None
            changed = state.update(present, now, .20, EVENT_END_CONFIRM_SECONDS)
            if changed:
                self.changed_at = time.time()
                active_since = now if state.active else None
                if state.active:
                    SHARED.update(want=True, event_priority=True, event_ending=False, started_at=now)
                    countdown, timer_due = EventCountdown(), 0.0
                    notify_webhook("events", "Hallows’ Eve detected — event started.")
                    log(f"Event started • {'visual priority' if visual else 'OCR'} detector")
                else:
                    if not SHARED.get("event_ending"):
                        self.request_cleanup(now, "event title disappeared")
                    SHARED["event_ending"] = False
                    watch = EventTitleWatch()
                    fallback_due = now+.4
                    log("Event title cleared; old event cannot trigger another equip")
            if active_since is not None and now-active_since > MAX_HOLD_SECONDS and not SHARED.get("event_ending"):
                self.request_cleanup(now, "maximum event watch time • protective put-away")
                SHARED["event_ending"] = True
            status = ("Protective put-away • waiting for title to clear" if SHARED.get("event_ending") else
                      "Unable to read" if present is None else "Event active • priority watch" if state.active else "Inactive")
            publish_preview("banner", img, f"{status} • match {score or 0:.0%}")
            self.stop.wait(max(.01, POLL_SECONDS - (time.monotonic() - started)))


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
            try:
                with window_task(slots, win):
                    rotation_state(win, SHARED["want"])
            except WindowUnavailable:
                waits.pop(hwnd, None)
    finally:
        restore_main(slots)


def refresh_mutation_progress(slots):
    """Report mutations after put-away, so notifications/completion stay current."""
    try:
        for i in range(len(slots)):
            check_stop()
            win = reveal_for_scan(slots, i)
            if win is None or win.hwnd in getattr(_tl, "manual_fallback", {}):
                continue
            try:
                with window_task(slots, win):
                    cards = stable_hotbar(win, read_labels=True)
                    if cards is not None:
                        publish_progress(win, cards)
                    else:
                        now = time.monotonic()
                        _tl.hotbar_waits.setdefault(win.hwnd, {
                            "since": now, "slot": win.slot, "retry_at": now+2})
                        UI.put(("rotation", win.slot, "Waiting for hotbar • idle scan will retry"))
            except WindowUnavailable:
                continue
    finally:
        restore_main(slots)


def initialize_run(slots):
    """One initialization path for live automation and the equipment diagnostic."""
    _tl.automation = True
    _tl.run_slots = slots
    _tl.hotbar_waits = {}
    _tl.daily_rewards_due = {}
    _tl.manual_fallback = {}
    _tl.commanded_slots = {}
    _tl.last_character_keys = {}
    _tl.exit_keys = {}
    _tl.exit_fingerprints = {}
    _tl.putaway_pending = {}
    _tl.equip_pending = {}
    _tl.event_equips = {}
    _tl.prepared_equips = {}
    _tl.rotation_scans = {}
    _tl.anti_idle = {}
    _tl.cleanup_seq = -1
    _tl.idle_focus_audit_at = time.monotonic()+IDLE_FOCUS_AUDIT_SECONDS
    with DATA_LOCK:
        PROGRESS.clear()
        DRACULA_NOTIFIED.clear()
    SHARED.update(want=False, holding=False, event_priority=False, end_seq=0, handled_end_seq=0,
                  started_at=0.0, ended_at=0.0, ended_wall_at=0.0, event_ending=False, equipping=False)


def job_macro():
    slots = scan_windows(passive=True)
    if not slots:
        return
    initialize_run(slots)
    try:
        ready = validate_runtime_start(slots)
    except BaseException:
        _tl.automation = False
        _tl.run_slots = None
        raise
    if not ready:
        _tl.automation = False
        _tl.run_slots = None
        return
    det = Detector(slots)
    health = SafetyMonitor(slots)
    health.start()
    det.start()
    log("Macro started. Watching the main window for Hallows' Eve (visual detection with OCR fallback).")
    log(f"Anti-idle: {'enabled; focused Space input every '+str(S['afk_minutes'])+' min per window' if S.get('afk_enabled', True) else 'DISABLED in Automation → Maintenance'}")
    last_maint = 0.0
    next_idle_check = 0.0
    next_rebirth = [0.0] * len(slots)
    post_event_scan = False
    try:
        while True:
            check_stop()
            try:
                # End transitions are latched. Always clean up the old event
                # before acting on a new one, even when want has already flipped.
                if (SHARED.get("end_seq", 0) > SHARED.get("handled_end_seq", 0)
                        or (SHARED["holding"] and not SHARED["want"])):
                    log("*** Hallows' Eve cleanup -> priority put-away and confirmation ***")
                    UI.put(("event_end", SHARED.get("ended_wall_at") or det.changed_at, False))
                    finish_event(slots)
                    post_event_scan = True
                    last_maint = 0.0
                    continue

                if _tl.putaway_pending:
                    service_putaway(slots)
                    if _tl.putaway_pending and not SHARED["want"]:
                        service_anti_idle(slots)
                        STOP.wait(.02)
                        continue

                if SHARED.get("event_ending"):
                    # The countdown guard has put characters away early. Keep
                    # watching this event and do not re-equip under its old title.
                    service_anti_idle(slots)
                    STOP.wait(.02)
                    continue

                if slots.restore_requested.is_set():
                    restore_main(slots)

                if SHARED["want"] and not SHARED["holding"]:
                    log("*** Hallows' Eve detected -> event priority; background tasks suspended ***")
                    SHARED["holding"] = True
                    SHARED["event_priority"] = True
                    UI.put(("event_start", det.changed_at))
                    _tl.equip_pending.clear()
                    _tl.event_equips.clear()
                    SHARED["equipping"] = True
                    try:
                        with preemptible():
                            run_on_all(slots, attempt_event_equip)
                    finally:
                        SHARED["equipping"] = False
                    restore_main(slots)
                    log(f"Event priority watch: {len(_tl.equip_pending)} window(s) awaiting equip retry; routine chores are suspended.")
                    continue

                if SHARED["want"] or SHARED["holding"]:
                    # Event retries run first. A due short anti-idle pulse may
                    # follow; popup/OCR chores remain suspended.
                    if _tl.equip_pending:
                        retry_event_equips(slots)
                    service_anti_idle(slots)
                    STOP.wait(.02)
                    continue

                if service_anti_idle(slots):
                    continue  # service other due windows before slow idle OCR/maintenance
                if time.monotonic() >= next_idle_check:
                    with preemptible():
                        check_idle_equipment(slots)
                    next_idle_check = time.monotonic()+1.0
                    if _tl.putaway_pending:
                        continue

                if post_event_scan and S["dracula_rotation"]:
                    with preemptible():
                        refresh_mutation_progress(slots)
                    post_event_scan = False

                if (S.get("stop_when_complete") and S["dracula_rotation"]
                        and not any(slots.hwnds[i] in _tl.manual_fallback for i in slots.active_indices())
                        and all_complete(slots, time.monotonic())):
                    log("All tracked characters have Dracula. Session complete.")
                    UI.put(("complete",))
                    break

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
                        maintenance(slots, want=SHARED["holding"])

                due = [i for i in slots.active_indices()
                       if S["rebirth"][i] and time.time() >= next_rebirth[i]]
                if due:
                    with preemptible():
                        origin = pyautogui.position()
                        for i in due:
                            w = slots.win(i)
                            if w is not None:
                                SHARED["menu_window"] = i
                                try:
                                    with window_task(slots, w):
                                        do_rebirth(w)
                                except WindowUnavailable:
                                    pass
                                finally:
                                    SHARED["menu_window"] = None
                            next_rebirth[i] = time.time() + S["rebirth_seconds"]
                        restore_main(slots)
                        pyautogui.moveTo(origin.x, origin.y)
            except Preempt:
                restore_main(slots)
                last_maint = 0.0  # redo the interrupted pass once the event has been handled
                continue
            except StopMacro:
                raise
            except pytesseract.TesseractNotFoundError:
                raise
            except Exception as e:  # one hiccup must not kill an overnight run
                log(f"[error] {type(e).__name__}: {e} -- continuing")
                # A transient error must not hide an event transition in a long sleep.
                STOP.wait(.05)
            sleep(0.05)
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
        clear_event_scans()
        health.stop.set()
        det.stop.set()
        _tl.automation = False
        _tl.run_slots = None
        SHARED["event_priority"] = False
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
            ("Welcome Back X", (w.left + int(w.w * WELCOME_CLOSE[0]), w.top + int(w.h * WELCOME_CLOSE[1]))),
            ("empty game area reference", (w.left + int(w.w * AFK_CLICK_SPOT[0]), w.top + int(w.h * AFK_CLICK_SPOT[1]))),
        ]
        for label, (x, y) in spots:
            log(f"  moving mouse to {label}")
            pyautogui.moveTo(x, y, duration=0.4)
            sleep(0.6)
    log("Layout test done. The mouse should have landed on the red X of the "
        "Welcome Back popup and an empty spot in each window. Window focus uses no mouse click.")


def job_test_event(seconds):
    """Explicit input diagnostic using the same confirmations as live automation."""
    slots = scan_windows(passive=True)
    if not slots:
        return
    initialize_run(slots)
    try:
        if not validate_runtime_start(slots):
            return
        log("TEST: simulated event start; using the live equip/confirmation path")
        SHARED.update(want=True, holding=True, event_priority=True, started_at=time.monotonic())
        SHARED["equipping"] = True
        try:
            run_on_all(slots, attempt_event_equip)
        finally:
            SHARED["equipping"] = False
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            check_stop()
            retry_event_equips(slots)
            sleep(.02)
        log("TEST: simulated event end; using priority put-away and visual confirmation")
        SHARED.update(want=False, end_seq=SHARED.get("end_seq", 0)+1, ended_at=time.monotonic())
        finish_event(slots)
        deadline = time.monotonic()+10
        while _tl.putaway_pending and time.monotonic() < deadline:
            service_putaway(slots)
            sleep(.02)
        if _tl.putaway_pending:
            log("TEST: UNEQUIP UNCONFIRMED in one or more windows; inspect them before starting another run")
        else:
            log("TEST: all remaining windows confirmed put away")
    finally:
        clear_event_scans()
        if not STOP.is_set():
            restore_main(slots)
        else:
            log("TEST stopped: input has stopped; check each game window and put away any held character manually")
        _tl.automation = False
        _tl.run_slots = None
        SHARED.update(want=False, holding=False, event_priority=False, equipping=False)


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
    maintenance(slots, force_afk=True)
    log("Maintenance test done. Review per-window popup and anti-idle results above.")


def job_test_anti_idle():
    """Explicit live input diagnostic, independent of popup OCR and hotbar visibility."""
    slots = scan_windows(passive=True)
    if not slots:
        return
    previous = getattr(_tl, "run_slots", None)
    # Diagnostics are exclusive jobs. A stopped run can leave a latched event
    # transition behind; it must not prevent this explicitly requested input.
    event_before = {key: SHARED.get(key, 0) for key in
                    ("want", "holding", "end_seq", "handled_end_seq")}
    SHARED.update(want=False, holding=False, end_seq=0, handled_end_seq=0)
    _tl.run_slots = slots
    try:
        for win in slots.all():
            try:
                with window_task(slots, win), preemptible():
                    sent = anti_idle_pulse(win)
                    log(f"{win.name}: diagnostic anti-idle Space {'sent; check for a jump in Roblox' if sent else 'NOT sent; focus refused'}")
            except WindowUnavailable:
                continue
            except StopMacro:
                raise
            except Exception as exc:
                log(f"{win.name}: diagnostic anti-idle failed ({type(exc).__name__}: {exc})")
        log("Anti-idle test finished. Input sent is not proof that Roblox reset its idle timer.")
    finally:
        try:
            if not STOP.is_set():
                restore_main(slots)
        finally:
            _tl.run_slots = previous
            SHARED.update(event_before)


def job_test_rebirth():
    slots = scan_windows()
    if not slots:
        return
    targets = [i for i in range(len(slots)) if S["rebirth"][i]]
    if not targets:
        log("Enable at least one window in Automation > Maintenance > Rebirth first.")
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
        observed = equipment_observation(w)
        sleep(CLEANUP_SAMPLE_SECONDS)
        second = equipment_observation(w)
        eq = None if observed is None or second != observed else observed > 0
        UI.put(("state", w.slot, eq))
        detail = "UNCONFIRMED" if eq is None else f"character slot {observed} selected" if eq else "no character selected"
        log(f"{w.name}: {detail}")
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
            log("ERROR: Tesseract OCR not found. Install it and set its path in Automation > App settings.")
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
from PySide6.QtCore import (
    Qt,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    QRectF,
    QPointF,
    QSize,
    QEvent,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QColor,
    QPainter,
    QPen,
    QLinearGradient,
    QRadialGradient,
    QFont,
    QPalette,
    QPainterPath,
    QPolygonF,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QAbstractButton,
    QAbstractSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QStackedWidget,
    QScrollArea,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QFileDialog,
    QDialog,
    QCheckBox,
    QProgressBar,
)

BG, SURFACE, BORDER = "#0c0e13", "#151820", "#2b303b"
TEXT, MUTED, ACCENT, GREEN = "#f5f0e9", "#a3a8b6", "#ff9b45", "#71d9ad"
RED = "#ff8590"


class Motion:
    enabled = True


def mix_color(a, b, amount):
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * amount,
        a.greenF() + (b.greenF() - a.greenF()) * amount,
        a.blueF() + (b.blueF() - a.blueF()) * amount,
    )


def label(text, size=10, color=TEXT, bold=False):
    widget = QLabel(text)
    widget.setFont(QFont("Segoe UI", size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setStyleSheet(
        f"color:{color};background:transparent;border:none;"
        f"font-size:{size}pt;font-weight:{600 if bold else 400};"
    )
    widget.setWordWrap(True)
    return widget


def draw_icon(p, name, rect, color):
    """Small vector icons share one stroke weight and scale cleanly with DPI."""
    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 24, rect.height() / 24)
    p.setPen(
        QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "dashboard":
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.5, 1.5)
    elif name == "controls":
        for x, y in ((5, 8), (12, 16), (19, 10)):
            p.drawLine(QPointF(x, 3), QPointF(x, y - 3))
            p.drawLine(QPointF(x, y + 3), QPointF(x, 21))
            p.drawEllipse(QPointF(x, y), 2.4, 2.4)
    elif name == "scan":
        for x, y, dx, dy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            p.drawLine(QPointF(x, y + 5 * dy), QPointF(x, y))
            p.drawLine(QPointF(x, y), QPointF(x + 5 * dx, y))
        p.drawEllipse(QPointF(12, 12), 4, 4)
        p.drawLine(QPointF(12, 6), QPointF(12, 18))
    elif name == "activity":
        path = QPainterPath(QPointF(2, 13))
        for x, y in ((7, 13), (10, 5), (14, 20), (17, 10), (19, 13), (22, 13)):
            path.lineTo(x, y)
        p.drawPath(path)
    elif name == "play":
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(21, 12), QPointF(7, 20)]))
    elif name == "stop":
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)
    elif name == "moon":
        path = QPainterPath(QPointF(16, 3))
        path.cubicTo(2, 0, 0, 20, 13, 21)
        path.cubicTo(17, 22, 21, 18, 22, 15)
        path.cubicTo(13, 18, 8, 10, 16, 3)
        p.drawPath(path)
    elif name == "arrow":
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
        p.drawLine(QPointF(14, 6), QPointF(20, 12))
        p.drawLine(QPointF(14, 18), QPointF(20, 12))
    elif name == "shield":
        path = QPainterPath(QPointF(12, 2))
        for x, y in ((21, 6), (20, 15), (12, 22), (4, 15), (3, 6), (12, 2)):
            path.lineTo(x, y)
        p.drawPath(path)
        p.drawLine(QPointF(8, 12), QPointF(11, 15))
        p.drawLine(QPointF(11, 15), QPointF(16, 9))
    p.restore()


class Emblem(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(46, 46)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#2b211b"))
        p.setPen(QPen(QColor("#68422b"), 1))
        p.drawRoundedRect(QRectF(1, 1, 44, 44), 13, 13)
        draw_icon(p, "moon", QRectF(10, 10, 26, 26), ACCENT)


class SoftButton(QPushButton):
    """Rounded native buttons with keyboard focus and lightweight hover motion."""

    def __init__(self, text, callback=None, kind="normal", parent=None, icon=None):
        super().__init__(text, parent)
        self.kind, self._hover, self.glyph = kind, 0.0, icon
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMinimumWidth(88)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.anim = QPropertyAnimation(self, b"hover", self)
        self.anim.setDuration(150)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if callback:
            self.clicked.connect(callback)

    def sizeHint(self):
        return QSize(
            max(88, self.fontMetrics().horizontalAdvance(self.text()) + (58 if self.glyph else 30)), 40
        )

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
            bg = mix_color("#f7943c", "#ffb66b", self._hover)
            fg, edge = QColor("#23150a"), QColor("#ffb46a")
        elif self.kind == "danger":
            bg = mix_color("#2b1d24", "#442a32", self._hover)
            fg, edge = QColor(RED), QColor("#55313d")
        elif self.kind == "nav":
            bg = mix_color("#2b211b" if active else "#101319", "#24252c", self._hover)
            fg, edge = QColor(ACCENT if active else MUTED), QColor("#5c3b27" if active else "#101319")
        else:
            bg = mix_color("#32241b" if active else "#1d222c", "#30343d", self._hover)
            fg, edge = QColor(ACCENT if active else TEXT), QColor("#795032" if active else "#373d49")
        if not self.isEnabled():
            bg, fg, edge = QColor("#171a21"), QColor("#626977"), QColor("#272c35")
        if self.isDown():
            bg = bg.darker(118)
        p.setBrush(bg)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(rect, 10, 10)
        if active and self.kind == "nav":
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(1, 12, 3, self.height() - 24), 1.5, 1.5)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 7, 7)
        p.setFont(self.font())
        p.setPen(fg)
        width = self.fontMetrics().horizontalAdvance(self.text())
        left = 16 if self.kind == "nav" else (self.width() - width - (29 if self.glyph else 0)) / 2
        if self.glyph:
            draw_icon(p, self.glyph, QRectF(left, (self.height() - 18) / 2, 18, 18), fg)
            left += 29
        p.drawText(
            QRectF(left, 0, self.width() - left - 10, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )


class ChoiceBox(QComboBox):
    """Keep the dropdown affordance legible on the dark palette."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(MUTED if self.isEnabled() else "#626977"), 1.6))
        x, y = self.width() - 17, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))


class Switch(QAbstractButton):
    def __init__(self, checked=False, name="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setAccessibleName(name)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 28)
        self._position = float(bool(checked))
        self.anim = QPropertyAnimation(self, b"position", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self.changed)

    def get_position(self):
        return self._position

    def set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, get_position, set_position)

    def changed(self, checked):
        self.setToolTip("On" if checked else "Off")
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
        p.setBrush(mix_color("#353b47", "#ef903b", self._position))
        p.drawRoundedRect(QRectF(1, 3, 46, 22), 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix_color("#b5bcc8", "#fff5e9", self._position))
        p.drawEllipse(QRectF(4 + self._position * 24, 6, 16, 16))


class Hero(QFrame):
    """Vector eclipse artwork; the timer is stopped whenever decoration is idle."""

    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.motion_allowed = True
        self.setMinimumHeight(170)
        self.timer = QTimer(self)
        self.timer.setInterval(75)
        self.timer.timeout.connect(self.advance)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 21, 210, 20)
        layout.setSpacing(9)
        self.eyebrow = label("HALLOWS’ EVE  /  EVENT MONITOR", 9, ACCENT, True)
        self.title = label("Ready for the next event.", 23, TEXT, True)
        self.description = label(
            "Watch the event. Rotate your characters.\nConfirm every put away.", 10, "#b8b4b2"
        )
        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)
        layout.addWidget(self.description)

    def sync_motion(self):
        active = (
            Motion.enabled
            and self.motion_allowed
            and self.isVisible()
            and self.window().isActiveWindow()
            and not self.window().isMinimized()
        )
        if active and not self.timer.isActive():
            self.timer.start()
        elif not active:
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_motion()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def advance(self):
        self.phase += 0.014
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor("#292018"))
        grad.setColorAt(0.48, QColor("#1c1b20"))
        grad.setColorAt(1, QColor("#161b25"))
        p.setBrush(grad)
        p.setPen(QPen(QColor("#53402e"), 1))
        p.drawRoundedRect(rect, 18, 18)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 18, 18)
        p.setClipPath(clip)
        p.setPen(QPen(QColor(255, 155, 69, 12), 1))
        for x in range(self.width() - 240, self.width(), 24):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 24):
            p.drawLine(self.width() - 240, y, self.width(), y)
        center = QPointF(self.width() - 105, self.height() / 2)
        glow = QRadialGradient(center, 105)
        glow.setColorAt(0, QColor(255, 139, 40, 64))
        glow.setColorAt(1, QColor(255, 139, 40, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 105, 105)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for radius, color in ((70, "#59402d"), (57, "#373538")):
            p.setPen(QPen(QColor(color), 1))
            p.drawEllipse(center, radius, radius)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawArc(
            QRectF(center.x() - 70, center.y() - 70, 140, 140), int((self.phase * 18 + 20) * 16), 42 * 16
        )
        p.setBrush(QColor("#ff9a3f"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 34, 34)
        p.setBrush(QColor("#1c1c22"))
        p.drawEllipse(center + QPointF(15, -10), 31, 31)
        point = center + QPointF(70 * math.cos(self.phase + 2.4), 70 * math.sin(self.phase + 2.4))
        p.setBrush(QColor("#ffd1a4"))
        p.drawEllipse(point, 3, 3)
        p.setPen(QColor("#c39a74"))
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(center.x() - 75, self.height() - 25, 150, 16),
            Qt.AlignmentFlag.AlignCenter,
            "HALLOWS / AUTOMATION",
        )


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(20, 18, 20, 18)
        self.box.setSpacing(9)


class LogHighlighter(QSyntaxHighlighter):
    """Colour new log blocks without rebuilding or converting the document to HTML."""

    def __init__(self, document, classify):
        super().__init__(document)
        self.classify = classify
        self.formats = {}
        for level, color in (("warning", RED), ("event", ACCENT), ("equipment", GREEN)):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.formats[level] = fmt

    def highlightBlock(self, text):
        fmt = self.formats.get(self.classify(text))
        if fmt is not None:
            self.setFormat(0, len(text), fmt)


def scroll_page():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 8, 12)
    layout.setSpacing(14)
    scroll.setWidget(content)
    return scroll, content, layout


def desktop_palette():
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, "#101319"),
        (QPalette.ColorRole.AlternateBase, SURFACE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, "#1d222c"),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, "#795032"),
        (QPalette.ColorRole.HighlightedText, TEXT),
        (QPalette.ColorRole.ToolTipBase, SURFACE),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#737b8a"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#737b8a"))
    return palette


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hallows’ Eve  •  Macro Studio 3.5.1")
        self.resize(1280, 900)
        self.setMinimumSize(1000, 700)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                max(1000, min(1280, available.width() - 48)), max(700, min(900, available.height() - 64))
            )
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
        self.invalid_windows = set()
        self.history = []
        self.logs = []
        self.log_revision = 0
        self._recent_revision = -1
        self._rendered_revision = -1
        self._log_signature = None
        self._preview_tokens = {}
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
            self.log_handler = RotatingFileHandler(
                self.log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
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
        for interval, fn in (
            (80, self.drain),
            (40, self.poll_hotkeys),
            (250, self.refresh_previews),
            (1000, self.tick),
        ):
            timer = QTimer(self)
            timer.setInterval(interval)
            timer.timeout.connect(fn)
            timer.start()
            self.timers.append(timer)
        self.refresh_tracker()
        self.flush_logs()
        if not S.get("setup_complete"):
            QTimer.singleShot(350, self.show_setup)

    @staticmethod
    def stylesheet():
        return """
        QMainWindow, QWidget { background:#0c0e13; color:#f5f0e9; font-family:'Segoe UI'; font-size:13px; }
        QWidget#sidebar { background:#101319; border-right:1px solid #272c35; }
        QFrame#card { background:#151820; border:1px solid #2b303b; border-radius:14px; }
        QFrame#card QWidget { background:transparent; }
        QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; border:0; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
          background:#101319; color:#f5f0e9; border:1px solid #3b414e; border-radius:8px;
          padding:8px 10px; min-height:22px; selection-background-color:#795032; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#ff9b45; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#747b8a; border-color:#2b303b; }
        QComboBox::drop-down { border:none; width:24px; }
        QComboBox::down-arrow { image:none; }
        QCheckBox { spacing:9px; }
        QCheckBox::indicator { width:16px; height:16px; border:1px solid #7d8492; border-radius:4px; background:#101319; }
        QCheckBox::indicator:checked { background:#ff9b45; border-color:#ff9b45; }
        QCheckBox::indicator:focus { border:2px solid #ffd1a4; }
        QComboBox QAbstractItemView { background:#20252f; color:#f5f0e9; selection-background-color:#67452c; padding:5px; }
        QScrollBar:vertical { background:transparent; width:10px; margin:3px; }
        QScrollBar::handle:vertical { background:#424957; border-radius:3px; min-height:32px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        QPlainTextEdit { background:#101319; border:1px solid #2b303b; border-radius:12px; padding:14px;
                         color:#c2c8d3; font-family:'Consolas'; font-size:12px; }
        QProgressBar { border:0; background:#272d38; border-radius:2px; max-height:4px; }
        QProgressBar::chunk { background:#ff9b45; border-radius:2px; }
        QToolTip { background:#252a34; color:#f5f0e9; border:1px solid #795032; padding:8px; }
        """

    def build_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        shell = QHBoxLayout(container)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(16, 25, 16, 18)
        left.setSpacing(9)
        left.addWidget(Emblem())
        left.addSpacing(6)
        left.addWidget(label("HALLOWS’ EVE", 14, TEXT, True))
        left.addWidget(label("MACRO STUDIO   /   3.5.1", 8, MUTED, True))
        left.addSpacing(27)
        left.addWidget(label("WORKSPACE", 8, "#7b8496", True))
        self.nav = []
        for index, (name, icon) in enumerate(
            (
                ("Dashboard", "dashboard"),
                ("Automation", "controls"),
                ("Diagnostics", "scan"),
                ("Activity log", "activity"),
            )
        ):
            button = SoftButton(name, lambda checked=False, i=index: self.navigate(i), "nav", icon=icon)
            button.setCheckable(True)
            button.setMinimumHeight(46)
            left.addWidget(button)
            self.nav.append(button)
        left.addStretch()
        self.setup_shortcut = SoftButton("Setup guide", self.show_setup, icon="shield")
        left.addWidget(self.setup_shortcut)
        left.addSpacing(12)
        note = Card()
        note.box.setContentsMargins(13, 14, 13, 14)
        note.box.addWidget(label("GLOBAL SHORTCUTS", 8, MUTED, True))
        self.shortcut_text = label("", 10, TEXT, True)
        note.box.addWidget(self.shortcut_text)
        note.box.addWidget(label("Available while Roblox\nis focused.", 9, MUTED))
        left.addWidget(note)
        left.addSpacing(8)
        self.side_status = label("●  Standing by", 9, GREEN)
        left.addWidget(self.side_status)
        left.addWidget(label("Fish! An Anime RNG", 8, "#7b8496"))
        shell.addWidget(sidebar)
        body = QWidget()
        right = QVBoxLayout(body)
        right.setContentsMargins(26, 23, 23, 16)
        right.setSpacing(18)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = label("Dashboard", 23, TEXT, True)
        self.page_subtitle = label("Event status and character protection at a glance.", 9, MUTED)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        top.addLayout(titles, 1)
        self.start_button = SoftButton("Start macro", self.start_macro, "primary", icon="play")
        self.stop_button = SoftButton("Stop", self.stop_job, "danger", icon="stop")
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
        self.footer_status = label("Ready • no automation running", 9, MUTED)
        footer.addWidget(self.footer_status, 1)
        self.footer_mode = label("SMART ROTATION", 8, ACCENT, True)
        self.footer_mode.setWordWrap(False)
        footer.addWidget(self.footer_mode)
        right.addLayout(footer)
        shell.addWidget(body, 1)
        self.navigate(0)
        self.update_hotkey_text()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        names = ("Dashboard", "Automation", "Diagnostics", "Activity log")
        descriptions = (
            "Event status and character protection at a glance.",
            "Choose how the macro behaves. Changes save automatically.",
            "Inspect what the macro sees and test each part of your setup.",
            "Follow events, equipment confirmations and recovery messages.",
        )
        self.page_title.setText(names[index])
        self.page_subtitle.setText(descriptions[index])
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)
        self.nav[index].setFocus(Qt.FocusReason.OtherFocusReason)
        self.hero.sync_motion()
        if index == 3:
            self.render_logs()

    def build_dashboard(self):
        page, _, layout = scroll_page()
        self.pages.addWidget(page)
        self.recovery_card = Card()
        self.recovery_text = label("", 10, ACCENT, True)
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
        for key, title, value, hint in (
            ("count", "EVENTS DETECTED", "0", "This session"),
            ("time", "EVENT WATCH TIME", "0m 00s", "Until cleanup begins"),
            ("last", "LAST EVENT DURATION", "—", "Time before put away"),
        ):
            card = Card()
            card.box.setContentsMargins(17, 13, 17, 13)
            card.box.setSpacing(4)
            card.box.addWidget(label(title, 8, MUTED, True))
            number = label(value, 23, TEXT, True)
            card.box.addWidget(number)
            card.box.addWidget(label(hint, 8, MUTED))
            self.metric_labels[key] = number
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        head = QHBoxLayout()
        head.addWidget(label("Roblox windows", 13, TEXT, True))
        head.addStretch()
        self.window_summary = label("Run a scan to check your windows", 9, MUTED)
        self.window_summary.setWordWrap(False)
        head.addWidget(self.window_summary)
        layout.addLayout(head)
        windows = QGridLayout()
        windows.setSpacing(12)
        self.window_badges, self.window_notes, self.window_progress, self.window_actions = {}, {}, {}, {}
        for i, name in enumerate(CORNERS):
            card = Card()
            card.box.setContentsMargins(16, 13, 16, 13)
            row = QHBoxLayout()
            row.addWidget(label(f"0{i+1}  /  {name.replace(' (main)', '').upper()}", 9, MUTED, True), 1)
            badge = label("Not checked", 10, MUTED, True)
            badge.setWordWrap(False)
            row.addWidget(badge)
            card.box.addLayout(row)
            action = label("Ready for a fresh check", 9, ACCENT, True)
            action.setAccessibleName(f"Window {i+1} current action")
            card.box.addWidget(action)
            self.window_actions[i] = action
            note = label("Scan to read characters and mutations.", 9, MUTED)
            note.setMinimumHeight(34)
            card.box.addWidget(note)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setTextVisible(False)
            progress.setFixedHeight(4)
            progress.setStyleSheet(
                "QProgressBar {background:#2b303b;border:0;border-radius:2px;} "
                "QProgressBar::chunk {background:#ff9b45;border-radius:2px;}"
            )
            progress.setAccessibleName(f"Window {i+1} confirmed Dracula progress")
            card.box.addWidget(progress)
            windows.addWidget(card, i // 2, i % 2)
            self.window_badges[i], self.window_notes[i], self.window_progress[i] = badge, note, progress
        layout.addLayout(windows)
        layout.addWidget(label("Shared event timing required • keep the main window’s event banner visible.", 9, MUTED))
        quick = Card()
        row = QHBoxLayout()
        words = QVBoxLayout()
        words.addWidget(label("Check your setup before a run", 11, TEXT, True))
        words.addWidget(label("Read character slots and Dracula labels without selecting a unit.", 9, MUTED))
        row.addLayout(words, 1)
        self.quick_scan = SoftButton(
            "Scan hotbars", lambda: self.start_job("Dracula scan", job_test_dracula), icon="scan"
        )
        row.addWidget(self.quick_scan)
        quick.box.addLayout(row)
        layout.addWidget(quick)
        recent = Card()
        row = QHBoxLayout()
        row.addWidget(label("Latest activity", 11, TEXT, True), 1)
        row.addWidget(SoftButton("Open activity", lambda: self.navigate(3), icon="arrow"))
        recent.box.addLayout(row)
        self.recent_log = label("No activity yet.", 9, MUTED)
        recent.box.addWidget(self.recent_log)
        layout.addWidget(recent)
        layout.addStretch()

    def section(self, layout, title, caption):
        card = Card()
        card.box.addWidget(label(title, 13, TEXT, True))
        card.box.addWidget(label(caption, 9, MUTED))
        card.box.addSpacing(5)
        layout.addWidget(card)
        return card.box

    def setting_row(self, box, title, description, control):
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 8)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        heading = label(title, 10, TEXT, True)
        heading.setBuddy(control)
        texts.addWidget(heading)
        texts.addWidget(label(description, 9, MUTED))
        row.addLayout(texts, 1)
        row.addSpacing(22)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(row)
        control.setAccessibleName(title)
        control.setAccessibleDescription(description)
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
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.pages.addWidget(page)
        row = QHBoxLayout()
        self.settings_tabs = []
        for index, name in enumerate(("Event & characters", "Maintenance", "Notifications", "App settings")):
            button = SoftButton(name, lambda checked=False, i=index: self.settings_navigate(i))
            button.setCheckable(True)
            row.addWidget(button)
            self.settings_tabs.append(button)
        row.addStretch()
        layout.addLayout(row)
        self.saved_text = label("●  All changes saved", 9, GREEN)
        layout.addWidget(self.saved_text)
        self.settings_content = QStackedWidget()
        layout.addWidget(self.settings_content, 1)
        sections = []
        for _ in range(4):
            scroll, _, content = scroll_page()
            self.settings_content.addWidget(scroll)
            sections.append(content)
        event, maintenance, notifications, application = sections

        box = self.section(
            event,
            "Character selection",
            "Keep your rod in slot 1. Smart rotation starts with character slot 2.",
        )
        self.rotation_toggle = self.setting_row(
            box,
            "Smart Dracula rotation",
            "Skip characters that already have Dracula. Unreadable scans retry, then use manual fallback.",
            self.toggle("dracula_rotation"),
        )
        self.char_combo = ChoiceBox()
        self.char_combo.addItems(list("1234567890"))
        self.char_combo.setCurrentText(str(S["char_key"]))
        self.char_combo.setFixedWidth(132)
        self.char_combo.currentTextChanged.connect(self.settings_changed)
        self.setting_row(
            box,
            "Manual / fallback character key",
            "Used in manual mode, or when no previous character slot is known. Key 0 selects slot 10.",
            self.char_combo,
        )
        self.mode_summary = label("", 9, ACCENT)
        box.addWidget(self.mode_summary)
        box = self.section(
            event,
            "Event detection & put away",
            "All windows follow the main event banner and must share its event timing.",
        )
        self.fast_toggle = self.setting_row(
            box,
            "Fast visual detection",
            "Watch the event title about every 40 ms. OCR helps recognize the start.",
            self.toggle("fast_detection"),
        )
        self.unequip_lead_spin = self.setting_row(
            box,
            "Unequip before timer ends",
            "Start putting characters away early when the countdown is reliable. Recommended: 2 seconds. Set 0 for title-only timing.",
            self.spin(S.get("unequip_lead_seconds", 2.0), 0, 10, 0.5, " sec"),
        )
        self.verify_toggle = self.setting_row(
            box,
            "Extra idle verification",
            "An additional manual-mode check between events. Equip and end-of-event visual confirmation are always on.",
            self.toggle("verify_state"),
        )
        box.addWidget(
            label("ALWAYS ON  •  Visual equip / put-away confirmation and missed-input recovery", 9, GREEN, True)
        )
        box = self.section(
            event, "Session completion", "Choose what happens after every tracked character has Dracula."
        )
        self.complete_toggle = self.setting_row(
            box,
            "Stop when all characters have Dracula",
            "Requires smart rotation and confirmed results for all active windows.",
            self.toggle("stop_when_complete"),
        )
        self.sound_toggle = self.setting_row(
            box,
            "Play completion sound",
            "Play a short sound when the automatic completion stop occurs.",
            self.toggle("completion_sound"),
        )

        box = self.section(
            maintenance,
            "Keep windows running",
            "Popup and rebirth work waits during events. Due anti-idle input runs between urgent equipment actions.",
        )
        self.popup_toggle = self.setting_row(
            box,
            "Close Welcome Back popups",
            "Close the popup when it blocks a game window.",
            self.toggle("close_popup"),
        )
        self.daily_toggle = self.setting_row(
            box,
            "Close Daily Rewards popups",
            "Check about every two minutes between events. Confirm the title and red X before clicking.",
            self.toggle("close_daily_rewards"),
        )
        self.afk_toggle = self.setting_row(
            box,
            "Prevent idle disconnects",
            "Send a short Space press with verified focus, even during prolonged hotbar recovery. Logs record every attempt.",
            self.toggle("afk_enabled"),
        )
        self.afk_spin = self.setting_row(
            box,
            "Anti-idle interval",
            "Time between Space presses per window. Failed attempts retry after 10 seconds.",
            self.spin(S["afk_minutes"], 0.5, 10, 0.5, " min"),
        )
        box = self.section(
            maintenance, "Rebirth", "Enable only the windows where you want automatic rebirth attempts."
        )
        grid = QGridLayout()
        self.rebirth_toggles = []
        for i, name in enumerate(CORNERS):
            cell = QHBoxLayout()
            cell.addWidget(label(f"{i+1:02d}  {name.replace(' (main)', '')}", 10), 1)
            switch = Switch(S["rebirth"][i], f"Rebirth {name}")
            switch.toggled.connect(self.settings_changed)
            self.rebirth_toggles.append(switch)
            cell.addWidget(switch)
            cell.setContentsMargins(0, 8, 18, 8)
            grid.addLayout(cell, i // 2, i % 2)
        box.addLayout(grid)
        self.rebirth_spin = self.setting_row(
            box,
            "Rebirth attempt interval",
            "Wait this long after each window’s attempt. Robux prompts are closed.",
            self.spin(S["rebirth_seconds"], 10, 3600, 10, " sec", True),
        )
        box = self.section(
            maintenance,
            "Window switching",
            "Normal actions can wait for Roblox to respond after switching focus.",
        )
        self.settle_spin = self.setting_row(
            box,
            "Normal focus delay",
            "Applies to maintenance and diagnostic actions. Event equip and unequip always use the fast path.",
            self.spin(S["settle"], 0, 10, 0.5, " sec"),
        )

        box = self.section(
            notifications,
            "Webhook notifications",
            "Send alerts to a Discord-compatible HTTPS webhook. Delivery runs in the background.",
        )
        self.webhook_edit = QLineEdit(S.get("webhook_url", ""))
        self.webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook_edit.setPlaceholderText("https://discord.com/api/webhooks/…")
        self.webhook_edit.setAccessibleName("Webhook URL")
        self.webhook_edit.textChanged.connect(self.settings_changed)
        box.addWidget(label("Webhook URL", 10, TEXT, True))
        box.addWidget(self.webhook_edit)
        box.addWidget(
            label("Saved only on this computer. Hidden here and excluded from support exports.", 9, MUTED)
        )
        self.webhook_events_toggle = self.setting_row(
            box,
            "Hallows’ Eve alerts",
            "Notify when the detector confirms that an event has started.",
            self.toggle("webhook_events"),
        )
        self.webhook_dracula_toggle = self.setting_row(
            box,
            "Dracula alerts",
            "Notify on the first confirmed Dracula for each slot during a run, including existing mutations. Requires smart rotation.",
            self.toggle("webhook_dracula"),
        )

        box = self.section(
            application,
            "Keyboard shortcuts",
            "Global shortcuts work while Roblox is focused. Select Bind, then press a key.",
        )
        self.bind_buttons = {}
        for key, title in (("start", "Start macro"), ("stop", "Stop everything")):
            button = SoftButton("", lambda checked=False, k=key: self.begin_bind(k))
            button.setFixedWidth(154)
            self.bind_buttons[key] = button
            self.setting_row(box, title, "Press Escape to cancel key binding.", button)
        self.bind_hint = label("Choose different keys for Start and Stop.", 9, ACCENT)
        box.addWidget(self.bind_hint)
        box = self.section(application, "Appearance", "A quiet interface for long sessions.")
        self.motion_toggle = self.setting_row(
            box,
            "Reduce motion",
            "Disable decorative animation and button transitions.",
            self.toggle("reduce_motion"),
        )
        box = self.section(
            application,
            "Tesseract OCR",
            "First-run setup handles installation. Change this path only for a different installation.",
        )
        path_row = QHBoxLayout()
        self.tess_edit = QLineEdit(S["tesseract"])
        self.tess_edit.setAccessibleName("Tesseract executable path")
        self.tess_edit.textChanged.connect(self.settings_changed)
        path_row.addWidget(self.tess_edit, 1)
        path_row.addWidget(SoftButton("Browse", self.browse_tesseract))
        box.addLayout(path_row)
        box.addWidget(
            SoftButton(
                "Open installation log", lambda: self.open_path(os.path.join(_setup_folder(), "setup.log"))
            )
        )
        for content in sections:
            content.addStretch()
        self.settings_navigate(0)

    def build_diagnostics(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.pages.addWidget(page)
        row = QHBoxLayout()
        self.diagnostic_tabs = []
        for index, name in enumerate(("Live view", "Tests", "Support & exports")):
            button = SoftButton(name, lambda checked=False, i=index: self.diagnostics_navigate(i))
            button.setCheckable(True)
            row.addWidget(button)
            self.diagnostic_tabs.append(button)
        row.addStretch()
        layout.addLayout(row)
        self.diagnostic_pages = QStackedWidget()
        layout.addWidget(self.diagnostic_pages, 1)
        sections = []
        for _ in range(3):
            scroll, _, content = scroll_page()
            self.diagnostic_pages.addWidget(scroll)
            sections.append(content)
        live, tests_layout, support = sections
        self.build_live_tools(live)
        tip = self.section(
            tests_layout,
            "Run a focused check",
            "Screen-reading tests do not select characters. Tests marked SENDS INPUT interact with Roblox.",
        )
        tip.addWidget(
            label(
                "Results appear in Activity log. Stop the current job before starting another test.",
                9,
                ACCENT,
            )
        )
        self.test_buttons = []
        grid = QGridLayout()
        grid.setSpacing(12)
        tests = [
            (
                "Dracula scan",
                "READS SCREEN",
                "Read mutations and report the next character slot.",
                job_test_dracula,
            ),
            (
                "Event banner",
                "READS SCREEN",
                "Read the main banner and save its diagnostic crop.",
                job_test_detection,
            ),
            ("Character state", "READS SCREEN", "Inspect each window’s equipped outline.", job_check_state),
            (
                "Window layout",
                "MOVES POINTER",
                "Visit expected popup and maintenance locations.",
                job_test_layout,
            ),
            (
                "Event simulation",
                "SENDS INPUT",
                "Equip, wait, then put away. Does not count as an event.",
                None,
            ),
            (
                "Popup & idle check",
                "SENDS INPUT",
                "Close recognized popups and request a jump in each window.",
                job_test_maintenance,
            ),
            (
                "Anti-idle",
                "SENDS INPUT",
                "Send Space once per window. Watch Roblox for a jump; no popup scan required.",
                job_test_anti_idle,
            ),
            (
                "Rebirth attempt",
                "SENDS INPUT",
                "Attempt one rebirth in the enabled windows.",
                job_test_rebirth,
            ),
            (
                "Manual key toggle",
                "SENDS INPUT",
                "Press the manual character key once in every window.",
                job_toggle_all,
            ),
        ]
        self.test_seconds_spin = self.spin(S["test_seconds"], 3, 300, 1, " sec", True)
        for i, (title, tag, description, fn) in enumerate(tests):
            card = Card()
            card.box.addWidget(label(tag, 8, GREEN if tag == "READS SCREEN" else ACCENT, True))
            card.box.addWidget(label(title, 12, TEXT, True))
            text = label(description, 9, MUTED)
            text.setMinimumHeight(38)
            card.box.addWidget(text)
            row = QHBoxLayout()
            if fn is None:
                row.addWidget(self.test_seconds_spin)
                callback = lambda: self.start_job(
                    "Event simulation", job_test_event, int(self.test_seconds_spin.value())
                )
            else:
                callback = lambda checked=False, f=fn, t=title: self.start_job(t, f)
            row.addStretch()
            button = SoftButton("Run test", callback)
            row.addWidget(button)
            self.test_buttons.append(button)
            card.box.addLayout(row)
            grid.addWidget(card, i // 2, i % 2)
        tests_layout.addLayout(grid)
        self.build_support(support)
        for content in sections:
            content.addStretch()
        self.diagnostics_navigate(0)

    def build_live_tools(self, layout):
        card = Card()
        card.box.addWidget(label("Live detection", 14, TEXT, True))
        card.box.addWidget(
            label(
                "Updates while the macro or read-only preview is running. A stale or covered image is not a verdict.",
                9,
                MUTED,
            )
        )
        row = QHBoxLayout()
        self.preview_start = SoftButton(
            "Start read-only preview", lambda: self.start_job("Live preview", job_live_preview)
        )
        self.setup_button = SoftButton("Guided setup", self.show_setup)
        row.addWidget(self.preview_start)
        row.addWidget(self.setup_button)
        row.addStretch()
        card.box.addLayout(row)
        self.banner_status = label("No banner captured yet", 9, MUTED)
        self.banner_image = QLabel("Start preview to inspect the event banner")
        self.banner_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_image.setFixedHeight(105)
        self.banner_image.setStyleSheet(
            "background:#0c0e13;border:1px solid #2b303b;border-radius:10px;color:#a3a8b6;"
        )
        card.box.addWidget(self.banner_status)
        card.box.addWidget(self.banner_image)
        row = QHBoxLayout()
        self.preview_window = ChoiceBox()
        self.preview_window.addItems([f"Window {i+1} — {n}" for i, n in enumerate(CORNERS)])
        row.addWidget(self.preview_window)
        row.addStretch()
        card.box.addLayout(row)
        self.hotbar_status = label("No hotbar captured yet", 9, MUTED)
        self.hotbar_image = QLabel("Hotbar preview")
        self.hotbar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotbar_image.setFixedHeight(110)
        self.hotbar_image.setStyleSheet(
            "background:#0c0e13;border:1px solid #2b303b;border-radius:10px;color:#a3a8b6;"
        )
        card.box.addWidget(self.hotbar_status)
        card.box.addWidget(self.hotbar_image)
        layout.addWidget(card)

    def refresh_previews(self):
        if (
            not hasattr(self, "banner_image")
            or self.pages.currentIndex() != 2
            or self.diagnostic_pages.currentIndex() != 0
            or self.isMinimized()
        ):
            return
        with DATA_LOCK:
            samples = dict(PREVIEW)
        for key, image_label, status_label in (
            ("banner", self.banner_image, self.banner_status),
            (f"hotbar_{self.preview_window.currentIndex()}", self.hotbar_image, self.hotbar_status),
        ):
            sample = samples.get(key)
            token = (key, sample[2] if sample else None, image_label.width(), image_label.height())
            if sample is None:
                status_label.setText("Not observed")
                if self._preview_tokens.get(image_label) != token:
                    image_label.setText("No capture for this window yet")
            else:
                img, status, at = sample
                age = time.monotonic() - at
                status_label.setText(status + (f" • STALE ({age:.0f}s ago)" if age > 2 else ""))
                if self._preview_tokens.get(image_label) != token:
                    if img is None:
                        image_label.setText("Unable to read • uncover the game")
                    else:
                        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        qimage = QImage(
                            rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888
                        ).copy()
                        image_label.setPixmap(
                            QPixmap.fromImage(qimage).scaled(
                                image_label.size(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
            self._preview_tokens[image_label] = token

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
        box.addWidget(
            label(
                "1. Open Roblox and enter the game.\n2. Arrange up to four windows; overlap is supported. Keep the main banner visible.\n3. Close menus; keep your rod in slot 1 and characters from slot 2 onward.\n4. Move this setup window away from Roblox, then run the checks.",
                10,
                MUTED,
            )
        )
        self.setup_labels = []
        for title in (
            "Dependencies and English OCR",
            "Roblox window layout",
            "Event banner capture",
            "Hotbar and mutation recognition",
        ):
            item = label("○  " + title, 10, TEXT)
            box.addWidget(item)
            self.setup_labels.append(item)
        self.setup_result = label(
            "These checks bring each Roblox window forward without selecting characters. An inactive event cannot validate the title match.",
            9,
            MUTED,
        )
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

        path, _ = QFileDialog.getSaveFileName(
            self, "Export diagnostic bundle", "hallows_diagnostics.zip", "ZIP archives (*.zip)"
        )
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
                archive.writestr(
                    "diagnostics.json",
                    json.dumps(
                        {
                            "app_version": "3.5.1",
                            "platform": platform.platform(),
                            "python": platform.python_version(),
                            "frozen": bool(getattr(sys, "frozen", False)),
                            "opencv": cv2.__version__,
                            "recovery_reason": RECOVERY["reason"],
                            "progress": progress,
                            "previews": {
                                k: {"status": v[1], "age_seconds": round(time.monotonic() - v[2], 2)}
                                for k, v in previews.items()
                            },
                        },
                        indent=2,
                    ),
                )
                archive.writestr("session.log", "\n".join(text for _, text in self.logs))
                if self.log_handler:
                    self.log_handler.flush()
                for filename in (
                    [self.log_path]
                    + [self.log_path + f".{i}" for i in range(1, 4)]
                    + [os.path.join(_setup_folder(), "setup.log")]
                ):
                    if os.path.isfile(filename):
                        archive.write(filename, "logs/" + os.path.basename(filename))
                if self.export_crops.isChecked():
                    for key, (img, _, _) in previews.items():
                        if img is not None:
                            ok, encoded = cv2.imencode(".png", img)
                            if ok:
                                archive.writestr("crops/" + key + ".png", encoded.tobytes())
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
        self.log_filter = ChoiceBox()
        self.log_filter.addItems(["All messages", "Events", "Warnings & errors", "Equipment"])
        self.log_filter.currentIndexChanged.connect(self.render_logs)
        row.addWidget(self.log_filter)
        self.follow_log = QCheckBox("Follow live")
        self.follow_log.setChecked(True)
        row.addWidget(self.follow_log)
        row.addWidget(SoftButton("Export log", self.export_log))
        layout.addLayout(row)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAccessibleName("Macro activity log")
        self.log_view.document().setMaximumBlockCount(1500)
        self.log_highlighter = LogHighlighter(self.log_view.document(), self.message_level)
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
        smart = self.rotation_toggle.isChecked()
        self.complete_toggle.setEnabled(smart)
        self.sound_toggle.setEnabled(smart and self.complete_toggle.isChecked())
        self.char_combo.setEnabled(True)
        self.verify_toggle.setEnabled(not smart)
        self.afk_spin.setEnabled(self.afk_toggle.isChecked())
        self.rebirth_spin.setEnabled(any(s.isChecked() for s in self.rebirth_toggles))
        self.webhook_dracula_toggle.setEnabled(smart)
        self.mode_summary.setText(
            "SMART MODE  •  Characters with Dracula are skipped automatically."
            if smart
            else "MANUAL MODE  •  Hold the selected key’s character only during Hallows’ Eve."
        )
        Motion.enabled = not self.motion_toggle.isChecked()
        if not Motion.enabled:
            for control in self.findChildren(Switch):
                control.anim.stop()
                control.set_position(float(control.isChecked()))
            for control in self.findChildren(SoftButton):
                control.anim.stop()
        self.hero.sync_motion()
        self.footer_mode.setText("SMART ROTATION" if smart else "MANUAL KEY MODE")

    def apply_settings(self):
        self.save_timer.stop()
        S.update(
            char_key=self.char_combo.currentText(),
            settle=float(self.settle_spin.value()),
            afk_enabled=self.afk_toggle.isChecked(),
            afk_minutes=float(self.afk_spin.value()),
            close_popup=self.popup_toggle.isChecked(),
            verify_state=self.verify_toggle.isChecked(),
            close_daily_rewards=self.daily_toggle.isChecked(),
            dracula_rotation=self.rotation_toggle.isChecked(),
            rebirth=[s.isChecked() for s in self.rebirth_toggles],
            rebirth_seconds=float(self.rebirth_spin.value()),
            tesseract=self.tess_edit.text().strip(),
            test_seconds=int(self.test_seconds_spin.value()),
            reduce_motion=self.motion_toggle.isChecked(),
            fast_detection=self.fast_toggle.isChecked(),
            unequip_lead_seconds=float(self.unequip_lead_spin.value()),
            stop_when_complete=self.complete_toggle.isChecked(),
            completion_sound=self.sound_toggle.isChecked(),
            webhook_url=self.webhook_edit.text().strip(),
            webhook_events=self.webhook_events_toggle.isChecked(),
            webhook_dracula=self.webhook_dracula_toggle.isChecked(),
        )
        setup_tesseract()
        # Report save errors instead of claiming persistence when a folder is read-only.
        try:
            atomic_settings(SETTINGS_FILE, S)
            self.settings_saved = True
            self.saved_text.setText("●  All changes saved")
        except OSError as exc:
            self.settings_saved = False
            self.saved_text.setText("Changes active • could not save to disk")
            self.append_log(f"Warning: settings could not be saved: {exc}")

    def browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select tesseract.exe", self.tess_edit.text(), "Tesseract (tesseract.exe)"
        )
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
        self.invalid_windows.clear()
        self.states.clear()
        for i, badge in self.window_badges.items():
            note = self.window_notes[i]
            badge.setText("Waiting")
            badge.setStyleSheet(
                f"color:{MUTED};background:transparent;border:none;font-size:10pt;font-weight:600;"
            )
            badge.setToolTip("")
            note.setText("Waiting for a fresh window check")
            self.window_actions[i].setText("Checking window")
        for bar in self.window_progress.values():
            bar.setValue(0)
        self.window_summary.setText("Checking windows…")
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
        self.hero.motion_allowed = not running
        self.hero.sync_motion()
        self.side_status.setText("●  Running" if running else "●  Standing by")
        self.saved_text.setText(
            "Stop the current job to edit settings."
            if running
            else (
                "●  All changes saved" if self.settings_saved else "Changes active • could not save to disk"
            )
        )
        self.footer_status.setText(self.job_label if running else "Ready when you are")
        self.hero.title.setText(
            "Watching for Hallows’ Eve."
            if running and self.job_label == "Macro running"
            else ("Checking your windows." if running else "Ready for the next event.")
        )
        self.hero.eyebrow.setText("HALLOWS’ EVE  /  " + ("MONITORING" if running else "STANDBY"))
        self.hero.description.setText(
            "Event monitoring and put-away recovery take priority."
            if running
            else "Watch the event. Rotate your characters.\nConfirm every put away."
        )

    def begin_bind(self, which):
        self.binding = which
        self.binding_ready_at = time.monotonic() + 0.25
        self.bind_hint.setText(f"Press your {which} key now. Escape cancels.")
        self.bind_buttons[which].setText("Press a key…")

    def update_hotkey_text(self):
        for kind in ("start", "stop"):
            self.bind_buttons[kind].setText(f"{vk_name(S[kind + '_vk'])}   ·   Bind")
        self.shortcut_text.setText(
            f"{vk_name(S['start_vk'])}   Start macro\n{vk_name(S['stop_vk'])}   Stop macro"
        )
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
                self.bind_hint.setText(
                    "That key is already assigned. Choose another key, or Escape to cancel."
                )
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
        self.hero.title.setText("Hallows’ Eve is active.")
        self.hero.description.setText("Equipping eligible characters. Each window shows its confirmed state.")
        self.refresh_tracker()

    def on_event_end(self, ts, stopped):
        if self.current_start is None:
            return
        duration = max(0, ts - self.current_start)
        self.total_time += duration
        self.last_duration = duration
        self.history.insert(
            0,
            f"#{self.count}   {fmt_clock(self.current_start)} → {fmt_clock(ts)}   ·   "
            f"{fmt_dur(duration)}" + ("   ·   stopped" if stopped else ""),
        )
        self.history = self.history[:100]
        self.current_start = None
        self.hero.eyebrow.setText("HALLOWS’ EVE  /  CLEANUP")
        self.hero.title.setText("Putting characters away." if not stopped else "Session stopped.")
        self.hero.description.setText(
            "Each window stays in recovery until its hotbar confirms the character is put away."
            if not stopped
            else "Check held characters before starting another run."
        )
        self.refresh_tracker()

    def refresh_tracker(self):
        live = max(0, time.time() - self.current_start) if self.current_start else 0
        self.metric_labels["count"].setText(str(self.count))
        self.metric_labels["time"].setText(fmt_dur(self.total_time + live))
        self.metric_labels["last"].setText(
            fmt_dur(self.last_duration) if self.last_duration is not None else "—"
        )
        self.history_label.setText("\n".join(self.history[:3]) or "No completed events in this session.")

    def reset_session(self):
        self.count = 1 if self.current_start else 0
        self.total_time = 0.0
        self.last_duration = None
        self.history.clear()
        self.refresh_tracker()
        self.append_log("Session counters and history reset.")

    def tick(self):
        if self.isVisible() and not self.isMinimized():
            self.refresh_tracker()

    @staticmethod
    def message_level(text):
        lower = text.lower()
        if any(
            word in lower
            for word in (
                "error",
                "warning",
                "failed",
                "couldn't",
                "uncertain",
                "unreadable",
                "unconfirmed",
                "disconnected",
                "skipped",
                "paused:",
            )
        ):
            return "warning"
        if any(word in lower for word in ("unequip", "put-away", "put away", "equipped", "fallback")):
            return "equipment"
        if "***" in text or any(
            word in lower
            for word in (
                "hallows' eve",
                "hallows’ eve",
                "event started",
                "event cleanup requested",
                "event title cleared",
            )
        ):
            return "event"
        return "info"

    def append_log(self, text):
        if not text.startswith("["):
            text = time.strftime("[%H:%M:%S] ") + text
        level = self.message_level(text)
        if level == "warning" and self.job_alive():
            self.job_had_error = True
        self.logs.append((level, text))
        if len(self.logs) > 1500:
            del self.logs[:-1500]
        self.log_revision += 1
        if self.log_handler:
            self.file_logger.info(text)

    def render_logs(self, *args):
        query = self.search_log.text().casefold()
        selected = self.log_filter.currentIndex()
        signature = (query, selected)
        if self._rendered_revision == self.log_revision and self._log_signature == signature:
            return
        delta = self.log_revision - self._rendered_revision
        bar = self.log_view.verticalScrollBar()
        follow = self.follow_log.isChecked() and bar.value() >= bar.maximum() - 3
        old_position = bar.value()
        category = {1: "event", 2: "warning", 3: "equipment"}.get(selected)
        lines = [
            text
            for level, text in self.logs
            if query in text.casefold() and (category is None or level == category)
        ]
        # Incremental appends preserve selection and avoid rebuilding the entire document per line.
        if signature == self._log_signature and not query and selected == 0 and 0 < delta <= len(self.logs):
            self.log_view.appendPlainText("\n".join(text for _, text in self.logs[-delta:]))
        else:
            self.log_view.setPlainText("\n".join(lines))
        bar.setValue(bar.maximum() if follow else old_position)
        self.log_count.setText(f"{len(lines)} shown  /  {len(self.logs)} recent messages  •  Rotating log saved")
        self._rendered_revision, self._log_signature = self.log_revision, signature

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export current session log", "hallows_session.log", "Log files (*.log);;Text files (*.txt)"
        )
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
        deadline = time.monotonic() + 0.008
        for _ in range(200):
            if time.monotonic() >= deadline:
                break
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
                if msg[1] in self.invalid_windows:
                    continue
                info = msg[2]
                done = [str(c["slot"]) for c in info["slots"] if c["dracula"] is True]
                self.window_progress[msg[1]].setValue(round(100 * len(done) / max(1, len(info["slots"]))))
                self.window_notes[msg[1]].setText(
                    f"Selected: {info['selected'] or 'none'} • Dracula {len(done)}/{len(info['slots'])}\nSlots: {', '.join(done) or 'none'}"
                    + ("\nAll complete" if info["complete"] else "")
                )
            elif msg[0] == "setup_check":
                if hasattr(self, "setup_labels"):
                    self.setup_labels[msg[1]].setText(("✓  " if msg[2] else "!  ") + msg[3])
            elif msg[0] == "setup_finished":
                if hasattr(self, "setup_result") and not msg[1]:
                    self.setup_result.setText(
                        "Checks finished with an issue. Review the marked step and Activity log, then rerun checks."
                    )
            elif msg[0] == "setup_done":
                S["setup_complete"] = True
                save_settings()
                if hasattr(self, "setup_result"):
                    self.setup_result.setText(
                        "Checks passed. Review Automation options, close setup and press Start when ready."
                    )
            elif msg[0] == "complete":
                self.recovery_text.setText("Session complete • All tracked characters have Dracula.")
                self.recovery_card.show()
                self.navigate(0)
                if S.get("completion_sound", True):
                    QApplication.beep()
            elif msg[0] == "window_invalid":
                i, reason, active = msg[1:]
                self.invalid_windows.add(i)
                self.states.pop(i, None)
                self.window_badges[i].setText("Skipped")
                self.window_badges[i].setToolTip(reason)
                self.window_badges[i].setStyleSheet(
                    f"color:{MUTED};background:transparent;border:none;font-size:10pt;font-weight:600;"
                )
                self.window_notes[i].setText(reason + "\nReconnect and restart to include this window.")
                self.window_actions[i].setText("Disconnected or unavailable")
                self.window_summary.setText(f"{active} active • {len(self.invalid_windows)} skipped")
            elif msg[0] == "rotation":
                if msg[1] in self.invalid_windows:
                    continue
                self.window_badges[msg[1]].setToolTip(msg[2])
                self.window_actions[msg[1]].setText(msg[2])
                if msg[1] not in PROGRESS:
                    self.window_notes[msg[1]].setText("Mutation progress appears after a readable scan.")
            elif msg[0] == "windows_found":
                count = msg[1]
                self.window_summary.setText(f"{count} window(s) detected")
                for i in range(count, len(CORNERS)):
                    self.window_badges[i].setText("Not detected")
                    self.window_notes[i].setText("Open this game window, then restart to include it.")
                    self.window_actions[i].setText("Not detected")
            elif msg[0] == "cleanup":
                if self.current_start is None:
                    if msg[1]:
                        self.hero.eyebrow.setText("HALLOWS’ EVE  /  PUT-AWAY RECOVERY")
                        self.hero.title.setText("Confirming characters are put away.")
                        self.hero.description.setText(
                            f"{msg[1]} window(s) awaiting visual confirmation. Missed inputs will retry."
                        )
                    else:
                        self.hero.eyebrow.setText("HALLOWS’ EVE  /  PUT AWAY CONFIRMED")
                        self.hero.title.setText("Characters are put away.")
                        self.hero.description.setText(
                            "Watching for the next event. Equipment checks continue between events."
                        )
            elif msg[0] == "state":
                i, value = msg[1], msg[2]
                if i in self.invalid_windows:
                    continue
                self.states[i] = value
                self.window_badges[i].setText(
                    "Equipped" if value is True else "Put away" if value is False else "Unconfirmed"
                )
                self.window_badges[i].setStyleSheet(
                    f"color:{ACCENT if value is True else GREEN if value is False else ACCENT};background:transparent;border:none;font-size:10pt;font-weight:600;"
                )
                if not self.invalid_windows:
                    self.window_summary.setText(
                        f"{len(self.states)} window{'s' if len(self.states) != 1 else ''} checked"
                    )
        self.flush_logs()
        if self.job is not None and not self.job.is_alive():
            name = self.job_label
            self.job = None
            self.set_running(False)
            if RECOVERY["reason"]:
                self.side_status.setText("●  Paused — fix issue")
                self.footer_status.setText(RECOVERY["reason"])
            self.append_log(
                f"Finished: {name}"
                + (
                    " — review warnings in Activity log."
                    if self.job_had_error
                    else " — see Activity log for results."
                )
            )
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

    def settings_navigate(self, index):
        self.settings_content.setCurrentIndex(index)
        for i, button in enumerate(self.settings_tabs):
            button.setChecked(i == index)

    def diagnostics_navigate(self, index):
        self.diagnostic_pages.setCurrentIndex(index)
        for i, button in enumerate(self.diagnostic_tabs):
            button.setChecked(i == index)

    def build_support(self, layout):
        tools = Card()
        tools.box.addWidget(label("Diagnostic bundle", 14, TEXT, True))
        tools.box.addWidget(
            label(
                "Collect logs, settings and scan results in one ZIP for troubleshooting. The webhook URL is excluded.",
                10,
                MUTED,
            )
        )
        self.export_crops = QCheckBox("Include latest banner and hotbar images")
        self.export_crops.setChecked(False)
        tools.box.addWidget(self.export_crops)
        tools.box.addWidget(
            label(
                "Images and logs may contain game details, account names or local paths. Review before sharing.",
                9,
                MUTED,
            )
        )
        tools.box.addWidget(SoftButton("Export diagnostic bundle", self.export_diagnostics, "primary"))
        layout.addWidget(tools)
        box = self.section(
            layout, "Saved files", "Full activity logs are saved automatically and rotated to limit disk use."
        )
        row = QHBoxLayout()
        row.addWidget(SoftButton("Open saved log", lambda: self.open_path(self.log_path)))
        row.addWidget(SoftButton("Open debug folder", lambda: self.open_path(APP_DIR)))
        row.addStretch()
        box.addLayout(row)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange) and hasattr(
            self, "hero"
        ):
            self.hero.sync_motion()

    def flush_logs(self):
        if self._recent_revision != self.log_revision:
            self.recent_log.setText("\n".join(line for _, line in self.logs[-3:]))
            self._recent_revision = self.log_revision
        if self.pages.currentIndex() == 3 and not self.isMinimized():
            self.render_logs()

def main():
    load_settings()
    if _BOOTSTRAP_TESSERACT:
        S["tesseract"] = _BOOTSTRAP_TESSERACT
    setup_tesseract()
    app = QApplication(sys.argv)
    app.setApplicationName("Hallows’ Eve Macro Studio 3.5.1")
    app.setStyle("Fusion")
    app.setPalette(desktop_palette())
    app.setFont(QFont("Segoe UI", 10))
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
