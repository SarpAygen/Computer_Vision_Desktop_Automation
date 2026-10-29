"""Replay missed equips, actual highlight screenshots, and event-end preemption.

Windows focus/input are simulated. These tests never launch Roblox.
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))
support = ast.parse((Path(__file__).parent/'test_window_recovery.py').read_text(encoding='utf-8'))
common = {'__file__': __file__}
for node in support.body:
    if (isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
            isinstance(node, ast.Assign) and any(getattr(t, 'id', '') in
                {'ROOT', 'TREE', 'NAMES', 'CONSTANTS'} for t in node.targets)):
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'support', 'exec'), common)


def load():
    ns = common['environment']()
    names = {'event_equip_allowed', 'event_slot_observation', 'confirm_event_equip',
             'event_equip_slot', 'verify_event_selection', 'prepared_event_equip', 'equip_character', 'attempt_event_equip',
             'retry_event_equips', 'manual_fallback_state', 'rotation_state',
             'ensure_state', 'equipment_observation', 'unequip_character', 'cleanup_one_window',
             'send_putaway', 'confirm_putaway_in_place', 'confirm_putaway', 'choose_character', 'HotbarCard', 'locate_hotbar', 'fit_hotbar_grid',
             'card_is_equipped', 'hotbar_card_kind', 'hotbar_snapshot', 'hotbar_visible', '_runs'}
    for node in TREE.body:
        if (getattr(node, 'name', '') in names or isinstance(node, ast.Assign) and
                any(getattr(t, 'id', '').startswith(('EQUIP_', 'CLEANUP_')) or getattr(t, 'id', '') in
                    {'SLOT_KEYS', 'STEP_DELAY', 'MUTATION_REGION'} for t in node.targets)):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'macro', 'exec'), ns)
    ns['_tl'].automation = True
    ns['_tl'].equip_pending = {}
    ns['_tl'].event_equips = {}
    ns['_tl'].putaway_pending = {}
    ns['_tl'].commanded_slots = {}
    ns['_tl'].last_character_keys = {}
    ns['_tl'].manual_fallback = {}
    ns['SHARED'].update(want=True, holding=True, event_ending=False)
    ns['S'].update(settle=0, dracula_rotation=False, char_key='2')
    ns['pytesseract'] = common['pytesseract']
    # Isolate target selection/confirmation here; async scan integration has its own suite.
    ns['event_rotation_scan'] = lambda win: ns['rotation_state'](win, True)
    return ns


def game(ns, missed=None, delay=0):
    clock = NS(now=100.)
    state = {1: 0, 2: 0, 3: 0}
    missed = dict(missed or {})
    sent, queued, hidden = [], [], set()
    slots = common['slots_for'](ns)
    def advance(seconds):
        clock.now += seconds
        for at, hwnd, target in queued[:]:
            if clock.now >= at:
                state[hwnd] = 0 if state[hwnd] == target else target
                queued.remove((at, hwnd, target))
    def snapshot(win, read_labels=False):
        assert not read_labels, 'Equip confirmation must not invoke mutation OCR'
        if win.hwnd in hidden:
            return [], None
        return [NS(number=i, kind='item' if i==1 else 'character',
                   equipped=state[win.hwnd]==i, dracula=False)
                for i in range(1, 11)], None
    def focus(win):
        ns['_focus']['hwnd'] = win.hwnd
        return True
    def sleep(seconds):
        ns['check_stop'](); advance(seconds); ns['check_stop']()
    def press(win, label, key=None):
        ns['check_stop']()
        assert ns['_focus']['hwnd'] == win.hwnd
        assert ns['event_equip_allowed'](win)
        sent.append((win.hwnd, key, clock.now))
        if missed.get(win.hwnd, 0):
            missed[win.hwnd] -= 1
        else:
            queued.append((clock.now+delay, win.hwnd, 10 if key=='0' else int(key)))
        advance(.12)
    ns.update(time=NS(monotonic=lambda: clock.now), sleep=sleep, focus=focus, cleanup_focus=focus,
              hotbar_snapshot=snapshot, hotbar_visible=lambda w, c: bool(c),
              press_char=press, restore_main=lambda _: None)
    return slots, clock, state, sent, hidden, advance


def retry_until_done(ns, slots, advance, limit=8):
    for _ in range(limit):
        if not ns['_tl'].equip_pending:
            return
        advance(2.1)
        ns['retry_event_equips'](slots)
    assert not ns['_tl'].equip_pending


# Sending succeeds but Roblox drops the first key in two of three windows.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns, missed={1:1, 2:1})
for win in slots.all():
    ns['attempt_event_equip'](win)
assert state=={1:0, 2:0, 3:2}
assert set(ns['_tl'].equip_pending)=={1,2}
assert not any('EQUIP CONFIRMED' in m and 'Top-left' in m for m in ns['_logs'])
retry_until_done(ns, slots, advance)
assert state=={1:2, 2:2, 3:2}
assert [h for h, _, _ in sent]==[1,2,3,1,2]
assert sum('EQUIP CONFIRMED' in m for m in ns['_logs'])==3
print('PASS dropped inputs in two windows are visually detected and retried; successful third window is never toggled again')

# A late original key arrives after the confirmation timeout but before retry.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns, delay=1.1)
ns['attempt_event_equip'](slots.win(0))
assert set(ns['_tl'].equip_pending)=={1}
retry_until_done(ns, slots, advance)
assert state[1]==2 and len(sent)==1
print('PASS delayed input is recognized before retry and does not toggle the unit off')

# A secondary retry covering the main banner yields immediately after input.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
ns['region_visible']=lambda *a:False
ns['S']['settle']=10  # recovery must not repeat the initial user delay
ns['_tl'].equip_pending={2:{'slot':1,'retry_at':0,'attempts':1}}
restores=[]
ns['restore_main']=lambda _:restores.append(clock.now)
started=clock.now
ns['retry_event_equips'](slots)
assert state[2]==2 and len(sent)==1 and restores
assert clock.now-started < .3  # simulated input/samples, excluding real focus latency
assert not ns['_tl'].equip_pending
advance(2.1); ns['retry_event_equips'](slots)
assert len(sent)==1 and not ns['_tl'].equip_pending
print('PASS covered-banner retry confirms in its original visit without repeating the key or initial settle delay')

# Manual mode and manual fallback use the same mandatory visual confirmation.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns, missed={1:1})
ns['_tl'].manual_fallback={1:{'key':'3','equipped':True}}
assert ns['manual_fallback_state'](slots.win(0), True)=='sent'
assert ns['_tl'].event_equips[1]['target']==3
advance(2.1)
ns['attempt_event_equip'](slots.win(0))
assert state[1]==3 and len(sent)==2
print('PASS fallback ignores stale equipped flags and confirms its configured slot')

# A catch animation permits one manual best-effort command, never blind retries.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns, missed={1:1})
hidden.add(1)
ns['attempt_event_equip'](slots.win(0))
for _ in range(15):
    advance(2.1); ns['retry_event_equips'](slots)
assert len(sent)==1 and set(ns['_tl'].equip_pending)=={1}
assert not any('EQUIP CONFIRMED' in m for m in ns['_logs'])
hidden.clear(); retry_until_done(ns, slots, advance)
assert state[1]==2 and len(sent)==2
print('PASS 30-second hidden hotbar stays unconfirmed; retries resume only after readable absence')

# Fresh screenshots must agree; selected target on only one frame is insufficient.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
samples=iter([(2,10), (0,10)] + [(0,10)]*10)
ns['event_slot_observation']=lambda *a: next(samples)
ns['attempt_event_equip'](slots.win(0))
assert not sent and set(ns['_tl'].equip_pending)=={1}
print('PASS conflicting pre-input observations defer without a toggle or false confirmation')

# A late key between absence samples and the final read must stop a retry.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
samples=iter([(0,10), (0,10), (2,10)])
ns['event_slot_observation']=lambda *a: next(samples)
ns['attempt_event_equip'](slots.win(0))
assert not sent and set(ns['_tl'].equip_pending)=={1}
print('PASS final fresh read catches a late selection before a repeat toggle')

# Exact slot, including key 0 for slot 10; another selected character isn't enough.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
ns['S']['char_key']='0'; state[1]=3
ns['attempt_event_equip'](slots.win(0))
assert state[1]==10 and sent[0][1]=='0' and not ns['_tl'].equip_pending
retry_until_done(ns, slots, advance)
assert not ns['_tl'].equip_pending
print('PASS wrong selected character is corrected to the exact target; slot 10 uses key 0')

# Smart rotation chooses once, then verification retries use no mutation scans.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns, missed={1:1})
ns['S']['dracula_rotation']=True
cards=ns['hotbar_snapshot'](slots.win(0))[0]
cards[1].dracula=True; cards[2].dracula=True
scans=[]
ns.update(stable_hotbar=lambda *a,**kw: scans.append(1) or cards,
          publish_progress=lambda *a:None, popup_state=lambda w:set())
ns['attempt_event_equip'](slots.win(0))
retry_until_done(ns, slots, advance)
assert state[1]==4 and len(scans)==1 and [key for _,key,_ in sent]==['4','4']
print('PASS smart rotation skips Dracula slots and retries its chosen slot without repeating mutation OCR')

# No eligible character remains: do not queue an equip or send any character key.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
ns['S']['dracula_rotation']=True
cards=ns['hotbar_snapshot'](slots.win(0))[0]
for card in cards[1:]: card.dracula=True
ns.update(stable_hotbar=lambda *a,**kw:cards, publish_progress=lambda *a:None,
          popup_state=lambda w:set())
ns['attempt_event_equip'](slots.win(0))
assert not sent and not ns['_tl'].equip_pending
print('PASS all-Dracula window remains unequipped with no endless equip retry')

# An end transition is checked after reading and before pressing, even if a new
# event has already turned want=True again before cleanup handles the old one.
for mode in ('end', 'early', 'back_to_back'):
    ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
    real=ns['event_slot_observation']; reads=[]
    def observe(win, target):
        reads.append(1)
        if len(reads)==3:
            ns['SHARED'].update(want=mode!='end', event_ending=mode=='early', end_seq=1)
        return real(win, target)
    ns['event_slot_observation']=observe
    ns['attempt_event_equip'](slots.win(0))
    assert not sent
print('PASS event end, early cleanup, and a latched back-to-back event block a late equip')

# End during the post-input wait interrupts confirmation and preserves cleanup hint.
ns=load(); slots, clock, state, sent, hidden, advance=game(ns)
real_press=ns['press_char']
def end_after_press(*a,**kw):
    real_press(*a,**kw); ns['SHARED'].update(want=False, end_seq=1)
ns['press_char']=end_after_press
try:
    with ns['preemptible'](): ns['attempt_event_equip'](slots.win(0))
except ns['Preempt']:
    pass
else:
    raise AssertionError('Event end must interrupt confirmation')
assert len(sent)==1 and ns['_tl'].commanded_slots[1]==2
assert not any('EQUIP CONFIRMED' in m for m in ns['_logs'])
print('PASS event-end preempts confirmation; tracked command remains available to immediate cleanup')

# Exercise real OpenCV selection detection on the supplied game screenshots.
ns=load(); cv2=ns['cv2']; win=NS(hwnd=1,slot=0,name='Fixture',w=1004,h=790)
for fixture, expected in [('equipped_hotbar.png',2), ('unselected_hotbar.png',0)]:
    crop=cv2.imread(str(Path(__file__).parent/'fixtures'/fixture))
    ns.update(grab=lambda *a:crop, region_visible=lambda *a:True)
    observed=ns['event_slot_observation'](win,2)
    assert observed is not None and observed[0]==expected, (fixture,observed)
ns['grab']=lambda *a:ns['np'].zeros_like(crop)
assert ns['event_slot_observation'](win,2) is None
print('PASS real equipped/unselected screenshots classified correctly; blank frame remains unknown')
