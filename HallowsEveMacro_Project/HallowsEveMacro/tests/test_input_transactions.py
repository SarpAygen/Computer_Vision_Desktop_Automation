"""Foreground transactions, delayed frames and key release; no live game input."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
source = ast.parse((Path(__file__).parent/'test_fast_events.py').read_text(encoding='utf-8'))
support = {'__file__': __file__}
for node in source.body:
    if (isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
            isinstance(node, ast.Assign) and any(getattr(t, 'id', '') in
                {'ROOT', 'support', 'base'} for t in node.targets) or
            isinstance(node, ast.For) and getattr(node.target, 'id', '') == 'node'):
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'support', 'exec'), support)


def overlapped_game():
    ns, slots, clock, state, commands, focuses, advance, _ = support['scenario']()
    ready_at = {h: clock.now for h in state}
    queued = []
    original_snapshot = ns['hotbar_snapshot']
    def tick(seconds):
        advance(seconds)
        for at, hwnd, target in queued[:]:
            if clock.now >= at:
                state[hwnd] = 0 if state[hwnd] == target else target
                queued.remove((at, hwnd, target))
    def sleep(seconds):
        ns['check_stop'](); tick(seconds); ns['check_stop']()
    def activate(hwnd):
        focuses.append(hwnd)
        ns['_focus']['hwnd'] = hwnd
        ready_at[hwnd] = clock.now + .06
        return True
    def tap(key, hold=.12):
        hwnd = ns['_focus']['hwnd']
        assert clock.now >= ready_at[hwnd], 'key-down preceded game activation readiness'
        target = 10 if key == '0' else int(key)
        commands.append((hwnd, target, clock.now, hold))
        queued.append((clock.now+.13, hwnd, target))
        tick(hold)
    def snapshot(win, read_labels=False):
        if ns['_focus']['hwnd'] != win.hwnd:
            return [], None
        return original_snapshot(win, read_labels)
    def observation(win):
        if ns['_focus']['hwnd'] != win.hwnd:
            return None
        return 0 if state[win.hwnd] in (0,1) else state[win.hwnd]
    for node in support['base']['TREE'].body:
        if (getattr(node,'name','') == 'cleanup_focus' or isinstance(node, ast.Assign)
                and any(getattr(t,'id','') == 'EVENT_FOCUS_GRACE' for t in node.targets)):
            exec(compile(ast.Module(body=[node],type_ignores=[]), 'macro', 'exec'), ns)
    ns.update(sleep=sleep, bring_to_front=activate, tap_key=tap,
              hotbar_snapshot=snapshot, equipment_observation=observation,
              region_visible=lambda win, region: ns['_focus']['hwnd'] == win.hwnd)
    return ns, slots, clock, state, commands, focuses, tick


# Actual urgent focus and input functions, with overlapping/hidden background
# hotbars and a 130ms visual acknowledgement. Old code needed another sweep.
ns,slots,clock,state,commands,focuses,tick = overlapped_game()
started = clock.now
for win in slots.all():
    ns['attempt_event_equip'](win)
assert not ns['_tl'].equip_pending and all(v == 2 for v in state.values())
assert [h for h,*_ in commands] == [1,2,3,4]
assert focuses == [2,3,4], focuses
assert clock.now-started < 1.5
print(f'PASS overlapping four-window equip with 130ms delayed response: {clock.now-started:.3f}s, one visit each, four keys')
ns['_tl'].exit_keys = {h:'1' for h in state}
ns['SHARED'].update(want=False,holding=True,end_seq=1,ended_at=clock.now)
focuses.clear(); commands.clear(); started=clock.now
ns['finish_event'](slots)
assert not ns['_tl'].putaway_pending and all(v == 1 for v in state.values())
assert focuses == [1,2,3,4] and len(commands) == 4
assert clock.now-started < 1.5
print(f'PASS overlapping four-window put-away with 130ms delayed response: {clock.now-started:.3f}s, no return sweep')


# A readable absence during the retry cooldown must not acquire focus again.
ns,slots,clock,state,commands,focuses,tick,_ = support['scenario'](dropped={1:1})
ns['attempt_event_equip'](slots.win(0))
ns['_focus']['hwnd']=2
before=list(focuses)
assert ns['event_equip_slot'](slots.win(0),2)=='waiting'
assert focuses==before and len(commands)==1
print('PASS pending late input is observed without refocusing or repeating a toggle during cooldown')


# No safe tool: a toggle that arrives after 700ms must not be repeated at the
# old 350ms boundary. No acknowledgement before that boundary means pending.
ns,slots,clock,state,commands,focuses,tick = overlapped_game()
state.update({1:2,2:3,3:4,4:5})
ns['_tl'].commanded_slots=state.copy(); ns['_tl'].exit_keys={}
ns['SHARED'].update(want=False,holding=True,end_seq=1,ended_at=clock.now)
delayed=[]
original_tick=tick
def advance(seconds):
    original_tick(seconds)
    for at, hwnd, target in delayed[:]:
        if clock.now >= at:
            state[hwnd]=0 if state[hwnd]==target else target
            delayed.remove((at,hwnd,target))
def late_tap(key,hold=.12):
    hwnd=ns['_focus']['hwnd']; target=int(key)
    commands.append((hwnd,target,clock.now,hold))
    delayed.append((clock.now+.7,hwnd,target))
    advance(hold)
ns['tap_key']=late_tap
ns['sleep']=lambda seconds:(ns['check_stop'](),advance(seconds),ns['check_stop']())
ns['finish_event'](slots)
for _ in range(50):
    advance(.1); ns['service_putaway'](slots)
    if not ns['_tl'].putaway_pending:break
assert len(commands)==4 and all(v==0 for v in state.values())
assert not ns['_tl'].putaway_pending
print('PASS 700ms late put-away toggles do not cause a second toggle or accidental re-equip')


# Choosing slot 2 is independent of a later unreadable item. An unknown earlier
# slot still prevents skipping ahead; all-Dracula requires every character known.
ns,slots,*_ = support['scenario']()
card=lambda n,k='character',d=False:NS(number=n,kind=k,dracula=d)
assert ns['choose_character']([card(1,'item'),card(2),card(3,'unknown')])==2
assert ns['choose_character']([card(1,'item'),card(2,'unknown'),card(3)]) is None
assert ns['choose_character']([card(1,'item'),card(2,d=True),card(3,'unknown')]) is None
assert ns['choose_character']([card(1,'item'),card(2,d=True),card(3,d=True)])==0
print('PASS later unknown slot does not block an earlier eligible character; earlier uncertainty still blocks guessing')


# Maintenance must distinguish an equipped safe tool from a character. The old
# boolean outline check saw both as True and could select slot 2 outside events.
ns,slots,clock,state,commands,focuses,tick,_ = support['scenario']()
ns['SHARED'].update(want=False,holding=False)
state[1]=1
ns['_tl'].manual_fallback[1]={'key':'2','equipped':True}
assert ns['ensure_state'](slots.win(0),False)=='ok'
assert not commands and state[1]==1
ns['_tl'].manual_fallback[1]['equipped']=True
assert ns['manual_fallback_state'](slots.win(0),False)=='ok'
assert not commands and not ns['_tl'].manual_fallback[1]['equipped']
state[1]=3
assert ns['ensure_state'](slots.win(0),False)=='fixed'
assert state[1]==0 and len(commands)==1 and commands[0][1]==3
print('PASS idle maintenance/fallback leave selected tools alone and put away the actual selected character, not a configured guess')


# An idle recovery from an unreadable startup scan must produce the next smart
# target; otherwise the next event unnecessarily requires a full mutation scan.
ns,slots,clock,state,commands,focuses,tick,_ = support['scenario']()
ns['SHARED'].update(want=False,holding=False)
ns['S']['dracula_rotation']=True
ns['_tl'].hotbar_waits={1:{'slot':0,'since':clock.now}}
def scan(win,read_labels=True,**kwargs):
    assert read_labels, 'Idle smart recovery must actually read mutation labels'
    return ns['hotbar_snapshot'](win)[0]
ns['stable_hotbar']=scan
assert ns['rotation_state'](slots.win(0),False)=='ok'
assert ns['_tl'].prepared_equips[1]['target']==2 and not ns['_tl'].hotbar_waits
assert not commands
print('PASS idle scan recovery prepares a smart target before the next event without sending a key')


# Exercise actual scan-code tap's finally block, including a stop/exception
# during the hold. The release is sent before any subsequent action can run.
tree=support['base']['TREE']
events=[]
tap_ns=dict(_tl=NS(),check_stop=lambda:None,SCANCODES={'2':3},KEYEVENTF_SCANCODE=8,KEYEVENTF_KEYUP=2,
            _send_scan=lambda scan,flags:events.append((scan,flags)),
            time=NS(sleep=lambda _:None))
node=next(n for n in tree.body if getattr(n,'name','')=='tap_key')
exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),tap_ns)
tap_ns['tap_key']('2')
assert events==[(3,8),(3,10)]
events.clear()
def interrupted(_):raise InterruptedError('simulated interrupted hold')
tap_ns['time'].sleep=interrupted
try:tap_ns['tap_key']('2')
except InterruptedError:pass
else:raise AssertionError('Interrupted hold must propagate')
assert events==[(3,8),(3,10)]
print('PASS actual key-down/key-up pairing survives an interrupted hold')

# A rejected release gets one retry without sending another key-down.
events.clear()
tap_ns['time'].sleep=lambda _:None
def reject_first_release(scan,flags):
    events.append((scan,flags))
    if flags==10 and len(events)==2:
        raise RuntimeError('simulated rejected release')
tap_ns['_send_scan']=reject_first_release
tap_ns['tap_key']('2')
assert events==[(3,8),(3,10),(3,10)]
print('PASS rejected key-up retries release without another key-down')
