"""Focus and idle scheduling regressions; no real Windows input is generated."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from contextlib import nullcontext
import threading

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'hallows_eve_macro.py').read_text(encoding='utf-8'))
NAMES = {'wait_for_foreground', 'bring_to_front', 'focus', 'cleanup_focus', 'press_char',
         'check_idle_equipment', 'restore_main'}


def environment():
    clock = NS(now=100.)
    state = NS(hwnd=1, refuse=False)
    calls = []
    windows = [NS(hwnd=i, slot=i-1, name=f'Window {i}') for i in (1, 2, 3)]

    def forbidden(*args, **kwargs):
        raise AssertionError('Window activation must not move/click the mouse or change topmost state')

    def activate(hwnd):
        calls.append(('activate', hwnd))
        if not state.refuse:
            state.hwnd = hwnd

    def sleep(delay):
        calls.append(('sleep', delay))
        clock.now += delay

    def raise_window(hwnd, insert_after, x, y, width, height, flags):
        assert insert_after == 0 and (x, y, width, height) == (0, 0, 0, 0)
        assert flags == (1 | 2 | 64 | 16384)
        calls.append(('raise', hwnd))

    ns = dict(
        _tl=NS(putaway_pending={}), time=NS(monotonic=lambda: clock.now),
        win32gui=NS(GetForegroundWindow=lambda: state.hwnd,
                    SetForegroundWindow=activate, BringWindowToTop=activate,
                    SetWindowPos=raise_window),
        win32con=NS(SWP_NOSIZE=1, SWP_NOMOVE=2, SWP_SHOWWINDOW=64, SWP_ASYNCWINDOWPOS=16384, HWND_TOP=0),
        win32api=NS(GetCurrentThreadId=lambda: 7, SetCursorPos=forbidden),
        win32process=NS(GetWindowThreadProcessId=lambda h: (8, 1),
                        AttachThreadInput=lambda *a: None),
        ctypes=NS(windll=NS(user32=NS(keybd_event=lambda *a: None, SendInput=forbidden))),
        pyautogui=NS(moveTo=forbidden, mouseDown=forbidden, mouseUp=forbidden),
        hold_click=forbidden, guard_window=lambda w: None, check_stop=lambda: None,
        sleep=sleep, log=lambda m: calls.append(('log', m)),
        window_task=lambda *a: nullcontext(), region_visible=lambda *a: True,
        equipment_observation=lambda w: 0, MUTATION_REGION=None, EVENT_REGION=None,
        S={'char_key': '2'}, foreground_title=lambda: 'Other',
        tap_key=lambda *a, **kw: calls.append(('key', a)),
        WindowUnavailable=type('WindowUnavailable', (Exception,), {}))
    for node in TREE.body:
        if (getattr(node, 'name', '') in NAMES or isinstance(node, ast.Assign)
                and any(getattr(t, 'id', '') in {'IDLE_FOCUS_AUDIT_SECONDS', 'CLEANUP_KEY_HOLD', 'EVENT_FOCUS_GRACE'}
                        for t in node.targets)):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'macro', 'exec'), ns)
    slots = NS(all=lambda: windows, restore_requested=threading.Event())
    restored = []
    ns['restore_main'] = lambda s: restored.append(clock.now)
    return ns, clock, state, calls, windows, slots, restored


for name in ('focus', 'cleanup_focus'):
    ns, clock, state, calls, windows, slots, restored = environment()
    assert ns[name](windows[0]) is True and calls == []
    assert ns[name](windows[1]) is True and state.hwnd == 2
    assert [c for c in calls if c[0] == 'activate'] == [('activate', 2)]
    calls.clear()
    state.refuse = True
    assert ns[name](windows[2]) is False
    assert not any(c[0] == 'key' for c in calls)
print('PASS normal/urgent focus is mouse-free; already-focused windows are a no-op; refusal is reported')

ns, clock, state, calls, windows, slots, restored = environment()
state.refuse = True
ns['_tl'].event_cleanup = True
try:
    ns['press_char'](windows[1], 'priority put-away')
except RuntimeError:
    pass
else:
    raise AssertionError('Must reject input to an unfocused window')
assert calls == []
print('PASS urgent keypress cannot leak into another foreground window')

ns, clock, state, calls, windows, slots, restored = environment()
for _ in range(60):
    ns['check_idle_equipment'](slots)
    clock.now += 1
assert calls == [] and restored == []
print('PASS 60 seconds of visible idle hotbar checks causes zero focus changes')

ns, clock, state, calls, windows, slots, restored = environment()
ns['region_visible'] = lambda win, region: win.hwnd == 1
focused = []
ns['cleanup_focus'] = lambda win: focused.append(win.hwnd) or True
for _ in range(60):
    ns['check_idle_equipment'](slots)
    clock.now += 1
assert focused == [2, 3] * 3 and len(restored) == 3, (focused, restored)
assert ns['_tl'].putaway_pending == {}
print('PASS covered idle hotbars are audited once per 20 seconds, not once per second')

ns, clock, state, calls, windows, slots, restored = environment()
ns['equipment_observation'] = lambda win: 2 if win.hwnd == 2 else 0
ns['check_idle_equipment'](slots)
assert set(ns['_tl'].putaway_pending) == {2} and calls[-1][0] == 'log'
assert not any(c[0] == 'activate' for c in calls)
print('PASS a visible late equip still queues immediate priority cleanup without focusing first')

ns, clock, state, calls, windows, slots, restored = environment()
node = next(n for n in TREE.body if getattr(n, 'name', '') == 'restore_main')
exec(compile(ast.Module(body=[node], type_ignores=[]), 'macro', 'exec'), ns)
class Slots:
    restore_requested = threading.Event()
    def __len__(self): return 3
ns['event_window'] = lambda s: windows[0]
state.hwnd = 3
ns['restore_main'](Slots())
assert calls == [] and state.hwnd == 3
ns['region_visible'] = lambda *a: False
ns['restore_main'](Slots())
assert state.hwnd == 1
print('PASS returning to the event monitor only changes focus when its banner is covered')

# Windows can accept activation before GetForegroundWindow reports the target.
ns, clock, state, calls, windows, slots, restored = environment()
activate_at = clock.now + .04
ns['win32gui'].SetForegroundWindow = lambda hwnd: calls.append(('activate', hwnd))
ns['win32gui'].GetForegroundWindow = lambda: 2 if clock.now >= activate_at else 1
assert ns['bring_to_front'](2) is True
assert clock.now < 100.13 and [c for c in calls if c[0]=='activate'] == [('activate',2)]
assert not any(c[0]=='raise' for c in calls)
print('PASS asynchronous Windows activation is awaited before declaring failure')

# A rejected request may need the overlap/z-order fallback, without mouse input.
ns, clock, state, calls, windows, slots, restored = environment()
state.refuse = True
original_raise = ns['win32gui'].SetWindowPos
def permit_after_raise(*args):
    original_raise(*args)
    state.refuse = False
ns['win32gui'].SetWindowPos = permit_after_raise
assert ns['bring_to_front'](2) is True and state.hwnd == 2
assert ('raise',2) in calls and clock.now < 100.37
print('PASS bounded overlap fallback preserves coordinates, size and topmost state')

ns, clock, state, calls, windows, slots, restored = environment()
state.refuse = True
ns['_tl'].event_cleanup = True
assert ns['bring_to_front'](2) is False and clock.now <= 100.121
print('PASS refused urgent focus is bounded to 120 ms of polling, so peers can proceed')
