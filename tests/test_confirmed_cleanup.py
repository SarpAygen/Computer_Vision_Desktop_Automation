"""Dropped/late input recovery and countdown protection; Windows input is mocked."""
import ast
import cv2
import numpy as np
import pytesseract
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
common_tree = ast.parse((Path(__file__).parent/'test_window_recovery.py').read_text(encoding='utf-8'))
common = {'__file__': __file__}
for node in common_tree.body:
    if (isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
            isinstance(node, ast.Assign) and any(getattr(t,'id','') in {'ROOT','TREE','NAMES','CONSTANTS'} for t in node.targets)):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'test_support','exec'),common)
TREE = ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))
extra = {'equipment_observation','confirm_putaway','send_putaway','confirm_putaway_in_place','cleanup_one_window',
         'service_putaway','repair_cleanup_popup','finish_event','equip_character','check_idle_equipment',
         'EventCountdown','read_countdown_image','remember_exit_key','known_exit_tool',
         'HotbarCard','locate_hotbar','fit_hotbar_grid','card_is_equipped','hotbar_card_kind',
         'hotbar_snapshot','hotbar_visible','read_text','_runs'}

def load():
    ns = common['environment']()
    for node in TREE.body:
        if (getattr(node,'name','') in extra or isinstance(node,ast.Assign) and
                any(getattr(t,'id','').startswith('CLEANUP_') or getattr(t,'id','') in
                    {'IDLE_FOCUS_AUDIT_SECONDS','SLOT_KEYS','EVENT_TIMER_REGION','EVENT_END_CONFIRM_SECONDS','POLL_SECONDS','EXIT_TOOL_ICONS','MUTATION_REGION'} for t in node.targets)):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
    ns['_tl'].automation = True
    ns['_tl'].commanded_slots = {1:2,2:3,3:4}
    ns['_tl'].manual_fallback = {2:{'key':'3','equipped':True}}
    ns['_tl'].exit_keys = {1:'1',2:'1',3:'1'}
    ns['_tl'].putaway_pending = {}
    return ns


class Clock:
    def __init__(self): self.now=100.
    def monotonic(self): return self.now
    def time(self): return self.now


def game(ns, *, missed=None, hidden=None, delayed=None, focus_fail=None):
    clock=Clock(); selected={1:2,2:3,3:4}; sent=[]; queued=[]
    missed=dict(missed or {}); hidden=hidden or set(); focus_fail=focus_fail or set()
    def apply():
        for at, hwnd, key in queued[:]:
            if at <= clock.now:
                selected[hwnd]=0 if key==1 or selected[hwnd]==key else key
                queued.remove((at,hwnd,key))
    def observe(win):
        apply()
        return None if win.hwnd in hidden else selected[win.hwnd]
    def focus(win):
        if win.hwnd in focus_fail: return False
        clock.now += .025
        return True
    def press(win,label,key=None):
        sent.append((win.hwnd,key,clock.now))
        clock.now += .08
        if missed.get(win.hwnd,0): missed[win.hwnd]-=1; return
        queued.append((clock.now+(delayed or 0),win.hwnd,10 if key=='0' else int(key)))
        apply()
    ns.update(time=clock,sleep=lambda seconds:(ns['check_stop'](), setattr(clock,'now',clock.now+seconds), ns['check_stop']()),
              cleanup_focus=focus,press_char=press,equipment_observation=observe,
              restore_main=lambda _:None,repair_cleanup_popup=lambda _:None)
    ns['SHARED'].update(want=False,holding=True,event_priority=True,end_seq=1,ended_at=clock.now)
    slots=common['slots_for'](ns)
    return slots,clock,selected,sent,hidden,focus_fail


def recover(ns,slots,clock,limit=4):
    deadline=clock.now+limit
    while ns['_tl'].putaway_pending and clock.now<deadline:
        clock.now+=.07
        ns['service_putaway'](slots)


# Actual cleanup state machine: one dropped key, fallback mode, and three windows.
ns=load();slots,clock,selected,sent,_,_=game(ns,missed={1:1})
ns['finish_event'](slots)
assert [w for w,_,_ in sent]==[1,2,3]
assert ns['_tl'].commanded_slots=={1:2,2:0,3:0}, 'only visually confirmed windows may clear their hints'
assert ns['_tl'].manual_fallback[2]['equipped'] is False
assert sum('UNEQUIP CONFIRMED' in m for m in ns['_logs'])==2
recover(ns,slots,clock)
assert not ns['_tl'].putaway_pending and all(x==0 for x in selected.values())
assert ns['_tl'].manual_fallback[2]['equipped'] is False
assert len([x for x in sent if x[0]==1])==2
assert all(x==0 for x in ns['_tl'].commanded_slots.values())
print(f'PASS three-window dropped-key replay: first sweep {sent[2][2]-100+.08:.3f}s; all visually confirmed by {clock.now-100:.3f}s (simulated focus/input delays)')

# A late toggle must not be toggled again after it succeeds.
ns=load();ns['_tl'].exit_keys={}
slots,clock,selected,sent,_,_=game(ns,delayed=.25)
ns['finish_event'](slots);recover(ns,slots,clock)
assert not ns['_tl'].putaway_pending and len(sent)==3 and all(x==0 for x in selected.values()),sent
print('PASS delayed toggle acknowledgements do not re-equip characters')

# No safe tool: retry only after repeated fresh evidence of a still-selected unit.
ns=load();ns['_tl'].exit_keys={}
slots,clock,selected,sent,_,_=game(ns,missed={1:1})
ns['finish_event'](slots);recover(ns,slots,clock)
assert not ns['_tl'].putaway_pending and len([x for x in sent if x[0]==1])==2
assert all(x==0 for x in selected.values())
print('PASS missed toggle is retried using current selected slot, not an old commanded flag')

# Slot 10 uses key 0, and a repeated acknowledged end cannot toggle it back on.
ns=load();ns['_tl'].exit_keys={}
slots,clock,selected,sent,_,_=game(ns)
selected[1]=10;ns['_tl'].commanded_slots[1]=10
ns['finish_event'](slots);recover(ns,slots,clock)
assert (1,'0') in [(h,k) for h,k,_ in sent] and selected[1]==0
before=len(sent);ns['finish_event'](slots)
assert len(sent)==before and not ns['_tl'].putaway_pending
print('PASS slot 10/key 0 cleanup and repeated event-end acknowledgement do not re-toggle')

# Unknown hotbar during a 30-second catch animation is never reported as successful.
ns=load();slots,clock,selected,sent,hidden,_=game(ns,hidden={1})
ns['finish_event'](slots);recover(ns,slots,clock,limit=31)
assert set(ns['_tl'].putaway_pending)=={1} and ns['_tl'].commanded_slots[1]==2
ns['SHARED']['want']=True
before=len(sent)
assert ns['equip_character'](slots.win(0))=='skipped' and len(sent)==before
hidden.clear();recover(ns,slots,clock)
assert not ns['_tl'].putaway_pending and selected[1]==0
assert any('UNEQUIP UNCONFIRMED' in m for m in ns['_logs'])
print('PASS hidden animation stays pending for 30 seconds; confirmed peers continue; no re-equip before confirmation')

# An unreadable animation must not cause another focus sweep every 60 ms.
ns=load();slots,clock,selected,sent,hidden,_=game(ns,hidden={1,2,3})
ns['finish_event'](slots)
clock.now+=.07
ns['service_putaway'](slots)  # establish hidden-hotbar retry intervals
for pending in ns['_tl'].putaway_pending.values():
    assert pending.get('check_delay') == ns['CLEANUP_UNREADABLE_SECONDS']
focus_calls=[];original_focus=ns['cleanup_focus']
ns['cleanup_focus']=lambda win: focus_calls.append(win.hwnd) or original_focus(win)
clock.now+=.07
ns['service_putaway'](slots)
assert focus_calls == [], focus_calls
clock.now+=.5
ns['service_putaway'](slots)
assert focus_calls == [1,2,3]
assert set(ns['_tl'].putaway_pending)=={1,2,3}
print('PASS unreadable recovery waits between focus sweeps and keeps all windows pending')

# Refusing focus must not delay other windows, or silently remove a still-held unit.
ns=load();real_restore=ns['restore_main']
slots,clock,selected,sent,_,blocked=game(ns,focus_fail={1})
ns.update(restore_main=real_restore,bring_to_front=lambda h:h not in blocked,
          region_visible=lambda win,region:win.hwnd not in blocked)
ns['finish_event'](slots);recover(ns,slots,clock,limit=1)
assert set(ns['_tl'].putaway_pending)=={1} and selected[2]==selected[3]==0
assert not slots.is_invalid(0) and not ns['STOP'].is_set() and slots.main_slot==1
blocked.clear();recover(ns,slots,clock)
assert not ns['_tl'].putaway_pending
print('PASS refused focus remains in recovery while the other windows are put away')

# A dialog swallowing keys is repaired only after the fast pass on every window.
ns=load();real_repair=ns['repair_cleanup_popup']
slots,clock,selected,sent,_,_=game(ns)
blocked={'yes':True};normal_press=ns['press_char']
def blocked_press(win,label,key=None):
    if win.hwnd==1 and blocked['yes']:
        sent.append((win.hwnd,key,clock.now));clock.now+=.08
    else:
        normal_press(win,label,key)
ns.update(press_char=blocked_press,repair_cleanup_popup=real_repair,
          popup_state=lambda win:{'welcome'} if win.hwnd==1 and blocked['yes'] else set(),
          close_welcome_popup=lambda win:blocked.update(yes=False))
ns['finish_event'](slots);recover(ns,slots,clock)
assert not blocked['yes'] and not ns['_tl'].putaway_pending and all(x==0 for x in selected.values())
assert [x[0] for x in sent[:3]]==[1,2,3]
print('PASS a key-blocking popup is closed after the other windows receive their first put-away')

# Detect an idle character even if an older command said it was already put away.
ns=load();slots,clock,selected,sent,_,_=game(ns)
ns['_tl'].commanded_slots={1:0,2:0,3:0};selected.update({1:2,2:0,3:0})
ns['check_idle_equipment'](slots)
assert set(ns['_tl'].putaway_pending)=={1}
recover(ns,slots,clock)
assert selected[1]==0 and not ns['_tl'].putaway_pending
print('PASS late idle equip overrides an old put-away command and triggers recovery')

# The snapshot classifier must distinguish unknown/occluded from truly put away.
ns=load();win=NS(hwnd=1);visible={'yes':True};cards=[]
ns.update(hotbar_snapshot=lambda *a,**kw:(cards,None),hotbar_visible=lambda *a:visible['yes'])
real_observation=ns['equipment_observation']
visible['yes']=False;assert real_observation(win) is None
visible['yes']=True;cards.extend([NS(number=1,equipped=False,kind='item'),NS(number=2,equipped=True,kind='character')])
assert real_observation(win)==2
cards[1].kind='unknown';assert real_observation(win) is None
cards[1].equipped=False;cards[0].equipped=True;assert real_observation(win)==0
print('PASS hidden or unknown selection is not mistaken for a confirmed unequip')

# Actual selected unit screenshot, recognized rod icon, and no OCR in equipment observation.
ns=load();crop=cv2.imread(str(Path(__file__).parent/'fixtures/equipped_hotbar.png'))
ns.update(grab=lambda *a:crop,region_visible=lambda *a:True)
win=NS(hwnd=1,slot=0,name='Reference',w=1004,h=790)
assert ns['equipment_observation'](win)==2
ns['_tl'].exit_keys={}
ns['ocr']=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('known tool should not need OCR'))
ns['remember_exit_key'](win)
assert ns['_tl'].exit_keys=={1:'1'}
cards,_=ns['hotbar_snapshot'](win,False)
assert not ns['known_exit_tool'](crop,cards[1].box)
unselected=cv2.imread(str(Path(__file__).parent/'fixtures/unselected_hotbar.png'))
ns['grab']=lambda *a:unselected
assert ns['equipment_observation'](win)==0
ns['grab']=lambda *a:np.zeros_like(unselected)
assert ns['equipment_observation'](win) is None
print('PASS real selected hotbar recognized; known rod artwork enables repeatable put-away; character artwork rejected')

# Real countdown OCR and temporal validation: an isolated wrong read cannot arm it.
ns=load();img=cv2.imread(str(Path(__file__).parent/'fixtures/event_timer.png'))
assert ns['read_countdown_image'](img)==36
assert ns['read_countdown_image'](np.zeros_like(img)) is None
count=ns['EventCountdown']();count.observe(3,100);assert not count.due(500,2)
count.observe(36,101);assert not count.due(500,2)
count.observe(35,102);assert count.deadline==137 and not count.due(134.9,2) and count.due(135,2)
assert not count.due(140,0)
print('PASS real countdown OCR; two decreasing consistent readings required; 2-second margin and disabled margin')

# Real detector: early cleanup is latched, old banner cannot re-equip, then next event may start.
ns=load();slots=common['slots_for'](ns)
ns['S']['unequip_lead_seconds']=2
positive=cv2.imread(str(Path(__file__).parent/'fixtures/event.png'))
negative=cv2.imread(str(Path(__file__).parent/'fixtures/no_event.png'))
frame={'value':positive}; timer_calls=[]
ns['grab']=lambda win, region: img if region==ns['EVENT_TIMER_REGION'] else frame['value']
ns['read_event']=lambda win:(True,'Hallows',frame['value'])
def countdown_image(_):
    timer_calls.append(time.monotonic())
    return 3 if len(timer_calls)==1 else 2
ns['read_countdown_image']=countdown_image
ns['SHARED'].update(want=False,holding=False,event_ending=False,end_seq=0,handled_end_seq=0)
det=ns['Detector'](slots);det.start()
try:
    common['wait_for'](lambda:ns['SHARED']['want'])
    common['wait_for'](lambda:ns['SHARED'].get('event_ending'),timeout=4)
    assert not ns['SHARED']['want'] and ns['SHARED']['end_seq']==1
    time.sleep(.25);assert ns['SHARED']['end_seq']==1 and not ns['SHARED']['want']
    frame['value']=negative
    common['wait_for'](lambda:not ns['SHARED'].get('event_ending'))
    assert ns['SHARED']['end_seq']==1
    frame['value']=positive
    common['wait_for'](lambda:ns['SHARED']['want'])
    assert not ns['_pauses']
finally:
    det.stop.set();det.join(3)
assert not det.is_alive()
print('PASS countdown triggers early cleanup once; old title cannot re-equip; a subsequent event starts normally')
ns=load();slots=common['slots_for'](ns)
ns['S']['unequip_lead_seconds']=2
frame={'value':positive}; attempts=[]
ns.update(grab=lambda win,region:frame['value'],read_event=lambda win:(True,'Hallows',frame['value']))
def failed_timer(_):
    attempts.append(1)
    raise RuntimeError('simulated OCR timeout')
ns['read_countdown_image']=failed_timer
ns['SHARED'].update(want=False,holding=False,event_ending=False,end_seq=0,handled_end_seq=0)
det=ns['Detector'](slots);det.start()
try:
    common['wait_for'](lambda:ns['SHARED']['want'])
    common['wait_for'](lambda:bool(attempts))
    frame['value']=negative
    common['wait_for'](lambda:not ns['SHARED']['want'])
    assert ns['SHARED']['end_seq']==1 and not ns['_pauses']
finally:
    det.stop.set();det.join(3)
print('PASS countdown OCR failure leaves fast visual cleanup working')

# Losing the banner for an extended period requests cleanup, rather than holding indefinitely.
ns=load();slots=common['slots_for'](ns);visible={'yes':True}
ns.update(grab=lambda *a:positive,read_event=lambda win:(True,'Hallows',positive),
          region_visible=lambda *a:visible['yes'])
ns['SHARED'].update(want=False,holding=False,event_ending=False,end_seq=0,handled_end_seq=0)
det=ns['Detector'](slots);det.start()
try:
    common['wait_for'](lambda:ns['SHARED']['want'])
    visible['yes']=False
    common['wait_for'](lambda:ns['SHARED'].get('event_ending'))
    assert not ns['SHARED']['want'] and ns['SHARED']['end_seq']==1 and not ns['_pauses']
    visible['yes']=True;time.sleep(.25)
    assert not ns['SHARED']['want'], 'same obscured event must not restart equipment'
finally:
    det.stop.set();det.join(3)
print('PASS extended banner occlusion triggers protective cleanup without a global pause')

print('Input timing is simulated; image processing/OCR and detector threads are real. No live Windows/Roblox guarantee.')
