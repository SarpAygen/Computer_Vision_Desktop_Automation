"""Build on Windows: python build_windows.py [--tesseract-dir PATH]."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def run(command):
    print("Running:", subprocess.list2cmdline([str(x) for x in command]), flush=True)
    subprocess.run([str(x) for x in command], check=True, cwd=ROOT)


def find_tesseract(explicit=None):
    candidates = [Path(explicit)] if explicit else []
    candidates += [ROOT / "Tesseract-OCR"]
    found = shutil.which("tesseract")
    if found:
        candidates.append(Path(found).parent)
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        if os.environ.get(var):
            candidates += [Path(os.environ[var])/"Tesseract-OCR", Path(os.environ[var])/"Programs"/"Tesseract-OCR"]
    for folder in candidates:
        exe = folder/"tesseract.exe"
        if not exe.is_file() or not (folder/"tessdata"/"eng.traineddata").is_file():
            continue
        result = subprocess.run([str(exe), "--list-langs"], capture_output=True, text=True, timeout=20)
        if result.returncode == 0 and "eng" in result.stdout.splitlines():
            return folder
    return None


def main():
    if sys.platform != "win32":
        raise SystemExit("Build this Windows app on Windows. No dependencies were installed.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tesseract-dir", help="A complete Tesseract-OCR folder, including DLLs and tessdata")
    parser.add_argument("--without-tesseract", action="store_true", help="Let first launch install OCR through winget instead of bundling it")
    args = parser.parse_args()
    if not (ROOT/"hallows_eve_macro.py").is_file():
        raise SystemExit("Keep this script beside hallows_eve_macro.py.")
    tess = None if args.without_tesseract else find_tesseract(args.tesseract_dir)
    if not args.without_tesseract and tess is None:
        winget = shutil.which("winget")
        if not winget:
            raise SystemExit("Install Tesseract by running the macro once, then build again; or supply --tesseract-dir.")
        print("Installing Tesseract for the bundle. Approve the Windows installer if prompted.")
        subprocess.run([winget,"install","--id","UB-Mannheim.TesseractOCR","--exact","--source","winget",
                        "--silent","--accept-package-agreements","--accept-source-agreements"], check=False)
        tess = find_tesseract(args.tesseract_dir)
        if tess is None:
            raise SystemExit("Tesseract not found after installation. Supply --tesseract-dir with its install folder.")
    env = ROOT/".build-venv"
    if not (env/"Scripts"/"python.exe").is_file():
        venv.create(env, with_pip=True)
    python = env/"Scripts"/"python.exe"
    run([python,"-m","pip","--isolated","install","--index-url","https://pypi.org/simple",
         "-r",ROOT/"requirements-build.txt"])
    run([python,"-m","PyInstaller","--noconfirm","--clean","--onedir","--windowed",
         "--name","HallowsEveMacro","--noupx",ROOT/"hallows_eve_macro.py"])
    bundle = ROOT/"dist"/"HallowsEveMacro"
    if tess:
        shutil.copytree(tess, bundle/"Tesseract-OCR", dirs_exist_ok=True)
        # The complete folder retains the distributor's DLLs, language data and notices.
        run([bundle/"Tesseract-OCR"/"tesseract.exe","--list-langs"])
    elif (bundle/"Tesseract-OCR").exists():
        raise SystemExit("Unexpected old Tesseract folder in the output; use a clean build directory.")
    shutil.copy2(ROOT/"README.md", bundle/"README.md")
    freeze = subprocess.check_output([str(python),"-m","pip","freeze"], text=True)
    (bundle/"build-versions.txt").write_text(freeze, encoding="utf-8")
    # Retain Python package license metadata for distribution alongside Qt/Tesseract notices.
    run([python, ROOT/"collect_notices.py", bundle/"THIRD_PARTY_NOTICES"])
    archive = shutil.make_archive(str(ROOT/"dist"/"HallowsEveMacro-Windows"),"zip",bundle.parent,bundle.name)
    print(f"\nBuilt: {archive}\nExtract the ZIP and open HallowsEveMacro.exe. Share the whole ZIP, not just the EXE.")
    print("Before sharing, test on a Windows account without Python/Tesseract installed. This script does not claim an in-game test.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Build failed (exit {exc.returncode}). Review build.log.")
