"""Real offscreen Qt checks; Windows automation and first-run installers are not run.

Run: python tests/test_frontend.py
Requires PySide6, OpenCV and NumPy. Test settings/logs use a temporary folder.
"""
import ast
import copy
import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_frontend(folder, source_path=None):
    source_path = Path(source_path or ROOT/'hallows_eve_macro.py')
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    defaults = next(n.value for n in tree.body if isinstance(n, ast.Assign) and
                    any(getattr(t, 'id', '') == 'DEFAULTS' for t in n.targets))
    settings = copy.deepcopy(eval(compile(ast.Expression(defaults), 'defaults', 'eval'),
                                  {'DEFAULT_TESSERACT': ''}))
    settings['setup_complete'] = True
    start = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.Import)
                 and any(a.name == 'math' for a in n.names))
    nodes = [n for n in tree.body[start:] if not isinstance(n, ast.If)]
    sys.path.insert(0, str(ROOT))
    from macro_runtime import atomic_settings
    ns = dict(atomic_settings=atomic_settings, os=os, sys=sys, json=json, queue=queue, time=time, threading=threading,
              S=settings, UI=queue.Queue(), STOP=threading.Event(),
              CORNERS=['Top-left (main)', 'Top-right', 'Bottom-left', 'Bottom-right'],
              APP_DIR=str(ROOT), SETTINGS_FILE=str(Path(folder)/'settings.json'),
              _setup_folder=lambda: str(folder), setup_tesseract=lambda: None,
              vk_name=lambda vk: f'F{vk-0x6f}', pressed_vk=lambda: None, is_down=lambda vk: False,
              fmt_dur=lambda x: f'{int(x)//60}m {int(x)%60:02d}s',
              fmt_clock=lambda ts: time.strftime('%H:%M:%S', time.localtime(ts)),
              DATA_LOCK=threading.Lock(), PREVIEW={}, PROGRESS={}, RECOVERY={'reason': ''},
              cv2=cv2, save_settings=lambda: None, __name__='frontend_test')
    for name in ('job_macro', 'job_test_dracula', 'job_test_detection', 'job_check_state',
                 'job_test_layout', 'job_test_event', 'job_test_maintenance', 'job_test_anti_idle', 'job_test_rebirth',
                 'job_toggle_all', 'job_live_preview', 'job_preflight'):
        ns[name] = lambda *args: None

    class Job(threading.Thread):
        def __init__(self, fn, *args):
            super().__init__(daemon=True)
            self.fn, self.args = fn, args

        def run(self):
            self.fn(*self.args)

    ns['Job'] = Job
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), 'exec'), ns)
    return ns


def run_checks():
    with tempfile.TemporaryDirectory(prefix='hallows-ui-') as folder:
        ns = load_frontend(folder)
        app = ns['QApplication'].instance() or ns['QApplication']([])
        app.setStyle('Fusion')
        app.setPalette(ns['desktop_palette']())
        window = ns['App']()
        window.show()
        app.processEvents()
        # Every category remains reachable, including at the smallest supported window.
        for width, height in ((1280, 900), (1000, 700)):
            window.resize(width, height)
            for page in range(4):
                window.navigate(page)
                app.processEvents()
                assert window.pages.currentIndex() == page
                assert window.start_button.geometry().right() < window.width()
            window.navigate(1)
            for index, button in enumerate(window.settings_tabs):
                button.click()
                app.processEvents()
                assert window.settings_content.currentIndex() == index
                assert button.geometry().right() <= button.parentWidget().width()
            window.navigate(2)
            for index, button in enumerate(window.diagnostic_tabs):
                button.click()
                app.processEvents()
                assert window.diagnostic_pages.currentIndex() == index
        print('PASS real Qt navigation: all 4 main pages, 4 settings categories and 3 diagnostic categories at 1280 and 1000 px')

        window.rotation_toggle.setChecked(False)
        assert window.verify_toggle.isEnabled() and not window.complete_toggle.isEnabled()
        window.char_combo.setCurrentText('0')
        window.unequip_lead_spin.setValue(3.5)
        window.daily_toggle.setChecked(False)
        window.rebirth_toggles[2].setChecked(True)
        window.webhook_edit.setText('https://example.invalid/test-webhook')
        window.webhook_events_toggle.setChecked(True)
        window.apply_settings()
        saved = json.loads(Path(ns['SETTINGS_FILE']).read_text(encoding='utf-8'))
        assert saved['char_key'] == '0' and saved['unequip_lead_seconds'] == 3.5
        assert not saved['dracula_rotation'] and not saved['close_daily_rewards']
        assert saved['rebirth'] == [False, False, True, False] and saved['webhook_events']
        assert window.webhook_edit.echoMode() == ns['QLineEdit'].EchoMode.Password
        print('PASS settings bindings and persistence across categories; webhook remains masked')

        ns['UI'].put(('windows_found', 3))
        ns['UI'].put(('window_invalid', 1, 'Roblox disconnected', 2))
        ns['UI'].put(('state', 1, True))
        ns['UI'].put(('progress', 0, {'slots': [{'slot': 2, 'dracula': True}, {'slot': 3, 'dracula': False}],
                                    'selected': 3, 'complete': False}))
        ns['UI'].put(('cleanup', 2))
        window.drain()
        assert window.window_badges[1].text() == 'Skipped'
        assert window.window_badges[3].text() == 'Not detected'
        assert window.window_progress[0].value() == 50
        assert 'Confirming' in window.hero.title.text()
        ns['UI'].put(('cleanup', 0))
        window.drain()
        assert window.hero.title.text() == 'Characters are put away.'
        print('PASS skipped and absent windows, mutation progress and explicit cleanup confirmation states')

        window.navigate(3)
        calls = {'append': 0, 'replace': 0}
        append, replace = window.log_view.appendPlainText, window.log_view.setPlainText
        def counted_append(text):
            calls['append'] += 1
            append(text)
        def counted_replace(text):
            calls['replace'] += 1
            replace(text)
        window.log_view.appendPlainText = counted_append
        window.log_view.setPlainText = counted_replace
        started = time.perf_counter()
        for index in range(600):
            ns['UI'].put(('log', f'Benchmark message {index}'))
        while not ns['UI'].empty():
            window.drain()
        elapsed = time.perf_counter()-started
        assert calls['replace'] == 0 and 1 <= calls['append'] < 40, calls
        assert 'Benchmark message 599' in window.log_view.toPlainText()
        print(f'PASS 600-message UI burst: {calls["append"]} batched appends, zero full document replacements ({elapsed*1000:.0f} ms local replay)')
        window.append_log('UNEQUIP UNCONFIRMED; continuing recovery')
        window.append_log('UNEQUIP CONFIRMED visually')
        window.log_filter.setCurrentIndex(2)
        assert 'UNCONFIRMED' in window.log_view.toPlainText() and 'CONFIRMED visually' not in window.log_view.toPlainText()
        window.log_filter.setCurrentIndex(3)
        assert 'CONFIRMED visually' in window.log_view.toPlainText()
        window.search_log.setText('no matching phrase')
        assert not window.log_view.toPlainText()
        window.search_log.clear()
        window.log_filter.setCurrentIndex(0)
        for index in range(1700):
            window.append_log(f'Rolling log {index}')
        window.flush_logs()
        assert len(window.logs) == 1500 and window.log_view.document().blockCount() == 1500
        assert 'Rolling log 199\n' not in window.log_view.toPlainText()
        assert window.log_view.toPlainText().endswith('Rolling log 1699')
        print('PASS warning/equipment search filters and bounded 1500-line log retention')

        window.navigate(2)
        window.diagnostics_navigate(0)
        app.processEvents()
        ns['PREVIEW']['banner'] = (np.zeros((70, 320, 3), np.uint8), 'Inactive', time.monotonic())
        conversions = []
        ns['cv2'] = NS(cvtColor=lambda *a: conversions.append(1) or cv2.cvtColor(*a), COLOR_BGR2RGB=cv2.COLOR_BGR2RGB)
        for _ in range(6):
            window.refresh_previews()
        assert len(conversions) == 1
        window.diagnostics_navigate(1)
        ns['PREVIEW']['banner'] = (np.ones((70, 320, 3), np.uint8), 'Active', time.monotonic())
        window.refresh_previews()
        assert len(conversions) == 1
        window.diagnostics_navigate(0)
        window.refresh_previews()
        assert len(conversions) == 2
        ns['PREVIEW']['banner'] = (None, 'Covered', time.monotonic()-3)
        window.refresh_previews()
        assert 'STALE' in window.banner_status.text() and 'Unable to read' in window.banner_image.text()
        assert window.banner_image.pixmap().isNull()
        print('PASS preview reuse, hidden-tab work suppression and stale/covered image replacement')

        window.navigate(0)
        window.motion_toggle.setChecked(True)
        assert not window.hero.timer.isActive()
        window.motion_toggle.setChecked(False)
        window.navigate(1)
        assert not window.hero.timer.isActive()
        release = threading.Event()
        window.start_job('Fixture run', lambda: release.wait(2))
        assert not window.start_button.isEnabled() and window.stop_button.isEnabled()
        assert not window.settings_content.isEnabled() and not window.hero.timer.isActive()
        assert not window.invalid_windows and window.window_badges[1].text() == 'Waiting'
        # Stop remains available on every page and propagates to the worker.
        window.navigate(2)
        window.stop_button.click()
        assert ns['STOP'].is_set()
        release.set()
        window.job.join()
        window.drain()
        assert window.start_button.isEnabled() and window.settings_content.isEnabled()
        print('PASS reduced motion, hidden-page timer suspension, running-state locks, Stop and restart reset')
        window.close()
        app.processEvents()
    print('Windows input, actual game rendering and real monitor DPI remain untested.')


if __name__ == '__main__':
    run_checks()
