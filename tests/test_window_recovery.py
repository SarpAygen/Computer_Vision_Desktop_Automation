"""Replay window loss and Daily Rewards using real OCR/images, with Windows input mocked.
Run from any directory: python tests/test_window_recovery.py
Requires OpenCV, NumPy, pytesseract, and an installed Tesseract executable.
"""
import ast
import cv2
import difflib
import numpy as np
import pytesseract
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'hallows_eve_macro.py').read_text(encoding='utf-8'))
NAMES = {
    'StopMacro', 'WindowUnavailable', 'FrameUnavailable', 'Preempt', 'card_fingerprint', 'card_layout_signature', 'clear_event_scans', 'send_tracked_key', 'initialize_run', 'preemptible', 'window_task',
    'check_stop', 'sleep', 'guard_window', 'Win', 'Slots', 'passive_window',
    'event_window', 'restore_main', 'run_on_all', 'finish_event', 'press_char',
    'disconnected_text', 'exclude_disconnected', 'popup_state', 'all_complete',
    'validate_visible_windows', 'validate_one_window', 'SafetyMonitor', 'Detector',
    'EventCountdown', 'read_countdown_image', 'title_mask', 'BannerMatcher', 'EventDebouncer', 'EventTitleWatch',
    'daily_rewards_x', 'daily_rewards_close_point', 'close_daily_rewards',
    'check_daily_rewards', 'maintenance', 'check_window', 'has_word', 'service_anti_idle', 'anti_idle_pulse',
}
CONSTANTS = {'DAILY_CLOSE_PNG', 'DAILY_REWARDS_SECONDS', 'DAILY_REWARDS_REGION',
             'CONNECTION_CHECK_SECONDS', 'EVENT_TEMPLATE_PNG', 'EVENT_REGION',
             'POPUP_REGION', 'POLL_SECONDS', 'EVENT_END_CONFIRM_SECONDS', 'MAX_HOLD_SECONDS'}


def environment():
    live = {1: True, 2: True, 3: True}
    focus = {'hwnd': 1}
    actions, logs, pauses = [], [], []
    win32 = NS(IsWindow=lambda h: live.get(h, False),
               IsWindowVisible=lambda h: live.get(h, False),
               GetWindowText=lambda h: 'Roblox', IsIconic=lambda h: False,
               GetForegroundWindow=lambda: focus['hwnd'])
    ns = dict(cv2=cv2, np=np, re=re, difflib=difflib, time=time, threading=threading,
              queue=queue, dataclass=dataclass, _tl=threading.local(),
              STOP=threading.Event(), UI=queue.Queue(), DATA_LOCK=threading.Lock(),
              PROGRESS={}, CORNERS=['Top-left', 'Top-right', 'Bottom-left', 'Bottom-right'],
              SHARED=dict(want=False, holding=False, event_priority=False, end_seq=0,
                          handled_end_seq=0, ended_at=0), win32gui=win32,
              _frame_rect=lambda h: (0, 0, 1004, 790),
              S={'fast_detection': True, 'unequip_lead_seconds': 0, 'dracula_rotation': False, 'char_key': '2',
                 'close_daily_rewards': True, 'close_popup': True, 'afk_enabled': False,
                 'verify_state': False},
              log=logs.append, publish_preview=lambda *a: None, close_capture=lambda: None,
              notify_webhook=lambda *a: None, region_visible=lambda *a: True,
              tracked_overlap=lambda *a: False, OCR_TIMEOUT=5,
              pyautogui=NS(position=lambda: NS(x=0, y=0),
                           moveTo=lambda x, y, **kw: actions.append(('move', x, y))),
              _root_at=lambda *a: focus['hwnd'],
              hold_click=lambda: actions.append(('click', focus['hwnd'])),
              tap_key=lambda key: actions.append(('key', focus['hwnd'], key)),
              ocr=lambda img, **kw: pytesseract.image_to_string(img, timeout=5, **kw))
    for node in TREE.body:
        if (getattr(node, 'name', '') in NAMES or isinstance(node, ast.Assign)
                and any(getattr(t, 'id', '') in CONSTANTS for t in node.targets)):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'macro', 'exec'), ns)
    def bring(hwnd):
        focus['hwnd'] = hwnd
        return live[hwnd]
    def pause(reason):
        pauses.append(reason)
        ns['STOP'].set()
    ns.update(bring_to_front=bring, safety_pause=pause, _live=live, _focus=focus,
              _actions=actions, _logs=logs, _pauses=pauses)
    return ns


def slots_for(ns):
    slots = ns['Slots']([1, 2, 3])
    ns['_tl'].run_slots = slots
    return slots


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate(), 'timed out waiting for a worker'


# Invalid windows retain their original slot number and cannot be used again mid-run.
ns = environment(); slots = slots_for(ns)
slots.invalidate(1, 'Roblox disconnected')
assert slots.active_indices() == [0, 2] and slots.win(1) is None
assert slots.win(2).slot == 2 and not ns['STOP'].is_set()
slots.invalidate(1, 'duplicate report')
assert len([m for m in ns['_logs'] if 'skipped for this run' in m]) == 1
ns['_live'][2] = True
assert slots.win(1) is None
# The input worker may already hold a Win object when the monitor excludes it.
ns['_focus']['hwnd'] = 2
try:
    ns['press_char'](ns['Win'](2, 0, 0, 1004, 790, 1), 'equip')
except ns['WindowUnavailable']:
    pass
else:
    raise AssertionError('cached invalid window accepted input')
assert not ns['_actions']
print('PASS secondary disconnect stays excluded; original slots preserved; stale input blocked')

# A close between constructing the window list and using it must not skip window 3.
ns = environment(); slots = slots_for(ns); visits = []
def action(win):
    visits.append(win.hwnd)
    if win.hwnd == 1:
        ns['_live'][2] = False
ns['run_on_all'](slots, action)
assert visits == [1, 3] and slots.is_invalid(1) and not ns['STOP'].is_set()
print('PASS window closes mid-pass: both remaining windows continue')

# Startup disconnects are skipped, including the original event source.
ns = environment(); slots = slots_for(ns)
ns.update(reveal_for_scan=lambda slots, i: slots.win(i), grab=lambda win, region: win.hwnd,
          read_text=lambda hwnd, **kw: 'Disconnected. Error Code: 277' if hwnd == 1 else 'game',
          check_daily_rewards=lambda win: False, remember_exit_key=lambda win:None)
assert ns['validate_visible_windows'](slots)
assert slots.active_indices() == [1, 2] and slots.main_slot == 1
ns['region_visible'] = lambda win, region: win.hwnd == ns['_focus']['hwnd']
ns['restore_main'](slots)
ns['region_visible'] = lambda *args: True
assert ns['_focus']['hwnd'] == 2 and not slots.restore_requested.is_set()
assert not ns['_pauses']
print('PASS disconnected main window at startup is skipped; event source promoted')

# Completion excludes skipped windows; losing every usable window stops safely.
ns = environment(); slots = slots_for(ns)
slots.invalidate(0, 'Roblox disconnected')
ns['PROGRESS'].update({i: {'complete': True, 'at': time.monotonic()} for i in (1, 2)})
assert ns['all_complete'](slots, time.monotonic())
slots.invalidate(1, 'closed'); assert not ns['STOP'].is_set()
slots.invalidate(2, 'closed'); assert ns['STOP'].is_set() and len(ns['_pauses']) == 1
assert not ns['all_complete'](slots, time.monotonic())
print('PASS completion excludes invalid windows; no windows stops safely')

# Foreground maintenance catches a disconnect even if its window was covered before.
ns = environment(); slots = slots_for(ns); verified = []
ns.update(grab=lambda win, region: win.hwnd,
          read_text=lambda hwnd, **kw: 'Connection lost' if hwnd == 2 else '',
          check_daily_rewards=lambda win: False, sleep=lambda _: ns['check_stop'](),
          ensure_state=lambda win, *a, **kw: verified.append(win.hwnd))
ns['S']['verify_state'] = True
ns['maintenance'](slots, want=False)
assert verified == [1, 3] and slots.is_invalid(1) and not ns['STOP'].is_set()
print('PASS foreground maintenance excludes a disconnected window and verifies the other two')

# Connection health remains available during an event; hotbar work remains suspended.
ns = environment(); slots = slots_for(ns)
ns['SHARED'].update(want=True, holding=True, event_priority=True)
def no_hotbar(*a, **kw):
    raise AssertionError('active event must not scan hotbars')
ns.update(grab=lambda win, region: win.hwnd,
          read_text=lambda hwnd, **kw: 'Disconnected' if hwnd == 1 else '',
          hotbar_snapshot=no_hotbar)
health = ns['SafetyMonitor'](slots); health.start()
try:
    wait_for(lambda: slots.is_invalid(0))
    assert slots.main_slot == 1 and not ns['STOP'].is_set() and not ns['_pauses']
finally:
    health.stop.set(); health.join(2)
assert not health.is_alive()
print('PASS independent connection monitor excludes a disconnected event source during an event')

# Losing the source must not fabricate an event end; the replacement's actual end still cleans up.
ns = environment(); slots = slots_for(ns)
positive = cv2.imread(str(Path(__file__).parent / 'fixtures/event.png'))
negative = cv2.imread(str(Path(__file__).parent / 'fixtures/no_event.png'))
frames = {1: positive, 2: positive, 3: positive}
ns.update(grab=lambda win, region: frames[win.hwnd],
          read_event=lambda win: (True, 'Hallows', frames[win.hwnd]))
det = ns['Detector'](slots); det.start()
try:
    wait_for(lambda: ns['SHARED']['want'])
    ns['_live'][1] = False
    wait_for(lambda: slots.main_slot == 1)
    time.sleep(.35)
    assert ns['SHARED']['want'] and ns['SHARED']['end_seq'] == 0
    frames[2] = negative
    wait_for(lambda: not ns['SHARED']['want'])
    assert ns['SHARED']['end_seq'] == 1 and not ns['_pauses']
finally:
    det.stop.set(); det.join(3)
assert not det.is_alive()
print('PASS active event survives main-window closure; replacement detects the actual event end')

# Pending OCR from the disconnected source cannot start an event on the replacement.
ns = environment(); slots = slots_for(ns); entered, release = threading.Event(), threading.Event()
ns['S']['fast_detection'] = False
ns['grab'] = lambda win, region: positive if win.hwnd == 1 else negative
def old_ocr(win):
    if win.hwnd == 1:
        entered.set(); release.wait(2)
        return True, 'Hallows', positive
    return False, '', negative
ns['read_event'] = old_ocr
det = ns['Detector'](slots); det.start()
try:
    assert entered.wait(1)
    ns['_live'][1] = False
    wait_for(lambda: slots.main_slot == 1)
    release.set(); time.sleep(.7)
    assert not ns['SHARED']['want'] and not ns['_pauses']
finally:
    release.set(); det.stop.set(); det.join(3)
print('PASS stale positive OCR from a disconnected source is discarded')

# The supplied image is processed with real OpenCV and Tesseract at several sizes.
ns = environment()
fixture = cv2.imread(str(Path(__file__).parent / 'fixtures/daily_rewards.png'))
for scale in (.75, 1, 1.25, 1.5):
    img = cv2.resize(fixture, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    point = ns['daily_rewards_close_point'](img)
    assert point is not None and abs(point[0]/scale-578) <= 2 and abs(point[1]/scale-81) <= 2, (scale, point)
no_x = fixture.copy(); no_x[60:100, 555:600] = 0
no_title = fixture.copy(); no_title[45:90, 95:420] = 0
assert ns['daily_rewards_close_point'](no_x) is None
assert ns['daily_rewards_close_point'](no_title) is None
print('PASS real Daily Rewards title/X detected at 75%, 100%, 125%, 150%; missing title or X rejected')

# Verify absolute coordinates on a moved window, confirmation on a fresh frame, and click gating.
slots = slots_for(ns); win = ns['Win'](1, 80, 35, 1084, 825, 0)
ns.update(grab=lambda *a: fixture, sleep=lambda _: None,
          _frame_rect=lambda h: (80,35,1084,825) if h==1 else (0,0,1004,790))
assert ns['close_daily_rewards'](win)
assert ('move', 909, 226) in ns['_actions'] and ns['_actions'].count(('click', 1)) == 1, ns['_actions']
ns['_actions'].clear()
captures = iter([fixture, no_x]); ns['grab'] = lambda *a: next(captures)
assert not ns['close_daily_rewards'](win) and not ns['_actions']
ns['SHARED'].update(want=True, event_priority=True)
ns['grab'] = lambda *a: (_ for _ in ()).throw(AssertionError('popup scanned during event'))
assert not ns['close_daily_rewards'](win)
# A newly detected event while OCR returns must also prevent the close click.
ns['SHARED'].update(want=False, event_priority=False)
ns['grab'] = lambda *a: fixture
real_ocr = ns['ocr']
def event_during_ocr(img, **kw):
    result = real_ocr(img, **kw)
    ns['SHARED'].update(want=True, event_priority=True)
    return result
ns['ocr'] = event_during_ocr
assert not ns['close_daily_rewards'](win) and not ns['_actions']
print('PASS moved-window click lands on red X; disappearing popup and an event during OCR prevent clicks')

# Check scheduling: at most one check per 120 seconds/window, disabled and event checks deferred.
ns = environment(); slots = slots_for(ns); checks = []
ns['close_daily_rewards'] = lambda win: checks.append(win.hwnd) or False
w1, w2 = slots.win(0), slots.win(1)
ns['check_daily_rewards'](w1); ns['check_daily_rewards'](w1); ns['check_daily_rewards'](w2)
assert checks == [1, 2]
ns['SHARED']['event_priority'] = True
ns['_tl'].daily_rewards_due[1] = 0
ns['check_daily_rewards'](w1); assert checks == [1, 2]
ns['SHARED']['event_priority'] = False
ns['check_daily_rewards'](w1); assert checks == [1, 2, 1]
ns['S']['close_daily_rewards'] = False
ns['_tl'].daily_rewards_due[1] = 0
ns['check_daily_rewards'](w1); assert checks == [1, 2, 1]
print('PASS popup checks are rate limited per window, deferred during events, and configurable')
print('Windows focus and input are mocked. Live Roblox acceptance and unseen popup layouts are not verified.')
