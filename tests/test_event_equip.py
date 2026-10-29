"""Reproduce a three-window event where the first two equips are skipped."""
import ast
import threading
import pytesseract
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))
support_tree = ast.parse((Path(__file__).parent/'test_window_recovery.py').read_text(encoding='utf-8'))
common = {'__file__': __file__}
for node in support_tree.body:
    if (isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
            isinstance(node, ast.Assign) and any(getattr(t,'id','') in
                {'ROOT','TREE','NAMES','CONSTANTS'} for t in node.targets)):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'support','exec'),common)


def load():
    ns = common['environment']()
    ns['pytesseract'] = pytesseract
    for node in TREE.body:
        if (getattr(node,'name','') in {'attempt_event_equip','retry_event_equips','job_macro','equip_character','event_equip_allowed'} or
                isinstance(node,ast.Assign) and any(getattr(t,'id','') in
                    {'IDLE_FOCUS_AUDIT_SECONDS','MAINTENANCE_SECONDS','SLOT_KEYS','STEP_DELAY','EQUIP_RETRY_SECONDS','EQUIP_SAMPLE_SECONDS','EQUIP_UNREADABLE_SECONDS','EQUIP_BATCH_SECONDS'} for t in node.targets)):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
    ns['_tl'].automation = True
    ns['_tl'].equip_pending = {}
    ns['_tl'].putaway_pending = {}
    ns['SHARED'].update(want=True,holding=True,event_ending=False)
    return ns


ns=load();slots=common['slots_for'](ns)
clock=NS(now=100.)
ns['time']=NS(monotonic=lambda:clock.now,time=lambda:clock.now)
done={'yes':False};calls=[];attempts={1:0,2:0,3:0}
def advance(seconds):
    clock.now+=seconds
    if attempts[1]==attempts[2]==2:
        done["yes"]=True
ns['STOP']=NS(is_set=lambda:done['yes'],wait=advance)
ns['sleep']=lambda seconds:(ns['check_stop'](),advance(seconds),ns['check_stop']())
def equip(win):
    attempts[win.hwnd]+=1
    calls.append((win.hwnd,clock.now))
    if win.hwnd in (1,2) and attempts[win.hwnd]==1:
        return 'skipped'  # refused focus / unreadable hotbar on the first pass
    return 'fixed'
class Monitor:
    def __init__(self,*a): self.stop=threading.Event();self.changed_at=clock.now
    def start(self): pass
    def join(self): pass
class Detector(Monitor):
    def start(self): ns['SHARED'].update(want=True,event_priority=True)
def forbidden(*a,**kw): raise AssertionError('Routine idle work ran during the event')
ns.update(scan_windows=lambda **kw:slots,validate_runtime_start=lambda _:True,
          Detector=Detector,SafetyMonitor=Monitor,equip_character=equip,
          DRACULA_NOTIFIED=set(),restore_main=lambda _:None,
          maintenance=forbidden,retry_hidden_hotbars=forbidden,check_idle_equipment=forbidden,
          refresh_mutation_progress=forbidden)
ns['S'].update(dracula_rotation=True,rebirth=[False]*4,rebirth_seconds=60)
try:
    ns['job_macro']()
except ns['StopMacro']:
    pass
assert [h for h,t in calls]==[1,2,3,1,2],calls
assert calls[3][1]-calls[0][1]>=1.0
assert not ns['_tl'].equip_pending
assert any('event equip pending' in m for m in ns['_logs'])
print('PASS actual scheduler: first two windows skipped, third equipped, only skipped windows retried and recovered')

# The actual preemption guard must stop a retry the moment this event ends.
ns=load();slots=common['slots_for'](ns)
ns['_tl'].equip_pending={1:{'slot':0,'retry_at':0,'attempts':1}}
sent=[]
def end_during_retry(win):
    assert not ns['SHARED'].get('equipping', False), 'Retries must retain covered-banner protection'
    ns['SHARED'].update(want=False,end_seq=1)
    ns['check_stop']()
    sent.append(win.hwnd)
ns.update(equip_character=end_during_retry,restore_main=lambda _:None)
try:
    ns['retry_event_equips'](slots)
except ns['Preempt']:
    pass
else:
    raise AssertionError('Event end must interrupt an equip retry')
assert sent==[] and not ns['SHARED']['equipping']
ns['service_putaway']=lambda *a,**kw:None
ns['finish_event'](slots)
assert ns['_tl'].equip_pending=={} and ns['SHARED']['handled_end_seq']==1
print('PASS event end interrupts a retry before input and cleanup clears old pending equips')

ns=load();slots=common['slots_for'](ns)
ns['_tl'].equip_pending={1:{'slot':0,'retry_at':0,'attempts':1},2:{'slot':1,'retry_at':0,'attempts':1}}
ns['_tl'].putaway_pending={1:{'slot':0}}
sent=[]
ns.update(equip_character=lambda w:sent.append(w.hwnd) or 'fixed',restore_main=lambda _:None)
ns['retry_event_equips'](slots)
assert sent==[2] and set(ns['_tl'].equip_pending)=={1}
ns['SHARED']['event_ending']=True
ns['retry_event_equips'](slots)
assert sent==[2] and not ns['_tl'].equip_pending
print('PASS unconfirmed cleanup blocks only its window; early cleanup cancels all further event equips')

ns=load();slots=common['slots_for'](ns)
ns['_tl'].equip_pending={1:{'slot':0,'retry_at':0,'attempts':1}}
slots.invalidate(0,'disconnected')
ns['equip_character']=lambda w:(_ for _ in ()).throw(AssertionError('Invalid window was retried'))
ns['retry_event_equips'](slots)
assert not ns['_tl'].equip_pending and not ns['STOP'].is_set()
print('PASS disconnected pending window is dropped without stopping surviving windows')

ns=load();slots=common['slots_for'](ns)
ns['S'].update(dracula_rotation=False,char_key='2',settle=0)
ns['_tl'].commanded_slots={1:2}
checks=[]
ns['event_equip_slot']=lambda win, target, **kw: checks.append((win.hwnd,target)) or 'skipped'
assert ns['equip_character'](slots.win(0))=='skipped'
assert checks==[(1,2)]
print('PASS a previously sent manual equip still requires visual verification')


ns=load();slots=common['slots_for'](ns)
ns['equip_character']=lambda w:(_ for _ in ()).throw(RuntimeError('temporary capture failure'))
ns['attempt_event_equip'](slots.win(0))
assert set(ns['_tl'].equip_pending)=={1}
ns['equip_character']=lambda w:'ok'  # all eligible slots complete is also terminal
ns['attempt_event_equip'](slots.win(1))
assert set(ns['_tl'].equip_pending)=={1}
print('PASS per-window exceptions schedule recovery; completed/all-Dracula windows are not retried')
