"""Run regression tests without starting Roblox input or the application bootstrap."""
import argparse
import ast
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def test_python(no_ui):
    probe='import cv2,numpy,pytesseract'+('' if no_ui else ',PySide6')
    candidates=[Path(sys.executable)]
    if os.name=='nt':
        folder=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'HallowsEveMacro'
        candidates+=sorted(folder.glob('python-*/Scripts/python.exe'),reverse=True)
        candidates.append(ROOT/'.build-venv/Scripts/python.exe')
    for candidate in candidates:
        if candidate.is_file():
            try:
                if subprocess.run([str(candidate),'-c',probe],capture_output=True,timeout=20).returncode==0:
                    return str(candidate)
            except (OSError,subprocess.TimeoutExpired):
                pass
    raise SystemExit('Test packages are unavailable. Run RUN_MACRO.cmd once to finish setup, then rerun RUN_TESTS.cmd.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-ui',action='store_true',help='Explicitly skip the Qt interface suite')
    parser.add_argument('--log',default='VALIDATION_3_5_1.log')
    args=parser.parse_args()
    python=test_python(args.no_ui)
    env=dict(os.environ,PYTHONUTF8='1',QT_QPA_PLATFORM='offscreen')
    if os.name=='nt' and not shutil.which('tesseract'):
        folder=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'HallowsEveMacro'
        candidates=[ROOT/'Tesseract-OCR/tesseract.exe',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Tesseract-OCR/tesseract.exe']
        for config in (folder/'hallows_macro_settings.json',folder/'setup.json'):
            try:candidates.insert(0,Path(json.loads(config.read_text(encoding='utf-8')).get('tesseract','')))
            except (OSError,ValueError,TypeError):pass
        for exe in candidates:
            if exe.is_file():
                env['PATH']=str(exe.parent)+os.pathsep+env.get('PATH','');break
    path=Path(args.log)
    if not path.is_absolute():path=ROOT/path
    failed=[]
    tests=sorted((ROOT/'tests').glob('test_*.py'))
    if args.no_ui:tests=[p for p in tests if p.name!='test_frontend.py']
    with path.open('w',encoding='utf-8') as log:
        log.write('Hallows Eve Macro Studio 3.5.1 validation\n')
        log.write(datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n')
        log.write('Windows input simulated; real fixture processing and offscreen Qt where included.\n')
        for source in ROOT.rglob('*.py'):
            if any(part.startswith('.') for part in source.relative_to(ROOT).parts):continue
            ast.parse(source.read_text(encoding='utf-8'),filename=str(source))
        log.write('All project Python sources parsed successfully.\n\n')
        for test in tests:
            print('Running '+test.name,flush=True)
            try:
                result=subprocess.run([python,str(test)],cwd=ROOT,env=env,
                                      capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
                output=result.stdout+result.stderr;code=result.returncode
            except subprocess.TimeoutExpired:
                output='FAILED: test exceeded 120 seconds.\n';code=1
            log.write('=== '+test.name+' ===\n'+output+f'Exit code: {code}\n\n');log.flush()
            if code:failed.append(test.name);print(output,flush=True)
        summary=f'{len(tests)-len(failed)}/{len(tests)} suites passed.'
        log.write(summary+'\n')
        if args.no_ui:log.write('Qt interface suite explicitly skipped.\n')
    print(summary+' Results: '+str(path))
    return bool(failed)


if __name__=='__main__':
    raise SystemExit(main())
