"""Replay anti-idle scheduling and real input wrapper; no Windows input is sent."""
import ast
import queue
import threading
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))
NAMES={'StopMacro','WindowUnavailable','FrameUnavailable','Preempt','preemptible','window_task',
       'check_stop','tap_key','anti_idle_pulse','service_anti_idle','initialize_run','job_macro',
       'job_test_anti_idle'}


def scenario():
    clock=NS(now=100.,wall=1000.)
    focus=NS(hwnd=99,refuse=set())
    commands=[];logs=[];actions=[]
    windows=[NS(hwnd=i+1,slot=i,name=f'Window {i+1}') for i in range(4)]
    class Slots:
        restore_requested=threading.Event()
        def __init__(self):self.invalid=set()
        def __len__(self):return len(windows)
        def active_indices(self):return [i for i in range(4) if i not in self.invalid]
        def is_invalid(self,i):return i in self.invalid
        def all(self):return [windows[i] for i in self.active_indices()]
        def win(self,i):return None if i in self.invalid else windows[i]
    slots=Slots()
    def advance(delay):clock.now+=delay
    def activate(win):
        actions.append(('focus',win.hwnd))
        if win.hwnd in focus.refuse:return False
        focus.hwnd=win.hwnd
        return True
    def forbidden(*a,**kw):raise AssertionError('Anti-idle must not run OCR, click or select a character')
    ns=dict(_tl=NS(),time=NS(monotonic=lambda:clock.now,time=lambda:clock.wall,sleep=advance),
            STOP=threading.Event(),SHARED=dict(want=False,holding=False,end_seq=0,handled_end_seq=0),
            cleanup_focus=activate,guard_window=lambda _:None,
            win32gui=NS(GetForegroundWindow=lambda:focus.hwnd),
            _send_scan=lambda scan,flags:commands.append((focus.hwnd,scan,flags,clock.now)),
            SCANCODES={'space':0x39},KEYEVENTF_SCANCODE=8,KEYEVENTF_KEYUP=2,
            restore_main=lambda _:actions.append(('restore',)),log=logs.append,
            UI=queue.Queue(),DATA_LOCK=threading.Lock(),PROGRESS={},DRACULA_NOTIFIED=set(),
            IDLE_FOCUS_AUDIT_SECONDS=20,MAINTENANCE_SECONDS=20,
            S=dict(afk_enabled=True,afk_minutes=4,dracula_rotation=False,
                   char_key='2',rebirth=[False]*4,rebirth_seconds=60),
            ocr=forbidden,press_char=forbidden,click_abs=forbidden,pyautogui=NS(keyDown=forbidden),
            pytesseract=NS(TesseractNotFoundError=type('TesseractNotFoundError',(Exception,),{})))
    for node in TREE.body:
        if getattr(node,'name','') in NAMES:
            exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
    return ns,slots,clock,focus,commands,logs,actions


ns,slots,clock,focus,commands,logs,actions=scenario()
for _ in range(4):assert ns['service_anti_idle'](slots)
assert [(h,s,f) for h,s,f,t in commands]==[(h,57,f) for h in range(1,5) for f in (8,10)]
assert len([m for m in logs if 'anti-idle input sent' in m])==4
assert all(e['last_sent'] is not None for e in ns['_tl'].anti_idle.values())
for _ in range(100):assert ns['service_anti_idle'](slots) is None
assert len(commands)==8
clock.wall-=999999 # system clock corrections must not change the schedule
assert ns['service_anti_idle'](slots) is None
clock.now+=241
for _ in range(4):ns['service_anti_idle'](slots)
assert len(commands)==16
print('PASS independent per-window monotonic schedule; four foreground Space pairs, no repeated focus before due, wall-clock changes ignored')


ns,slots,clock,focus,commands,logs,actions=scenario()
focus.refuse.add(1)
for _ in range(4):ns['service_anti_idle'](slots)
assert [h for h,s,f,t in commands if f==8]==[2,3,4]
entry=ns['_tl'].anti_idle[1]
assert entry['last_sent'] is None and entry['next_at']==110
focus.refuse.clear();clock.now=110
ns['service_anti_idle'](slots)
assert [h for h,s,f,t in commands if f==8]==[2,3,4,1]
assert ns['_tl'].anti_idle[1]['last_sent'] is not None
print('PASS refused focus retries after 10 seconds without blocking healthy windows or recording a successful input')


for reason in ('focus_loss','geometry','release'):
    ns,slots,clock,focus,commands,logs,actions=scenario()
    if reason=='focus_loss':ns['guard_window']=lambda _:setattr(focus,'hwnd',99)
    if reason=='geometry':
        def moved(_):raise ns['FrameUnavailable']('moved')
        ns['guard_window']=moved
    if reason=='release':
        def send(scan,flags):
            commands.append((focus.hwnd,scan,flags,clock.now))
            if flags==10:raise RuntimeError('release rejected')
        ns['_send_scan']=send
    ns['service_anti_idle'](slots)
    assert ns['_tl'].anti_idle[1]['last_sent'] is None
    assert ns['_tl'].anti_idle[1]['next_at']<clock.now+11
    if reason!='release':assert not commands
    else:assert [f for h,s,f,t in commands]==[8,10,10]
print('PASS focus loss, moved window and rejected release never consume a full interval; release failure retries only key-up')


for phase in ('start','end','after_focus','stop'):
    ns,slots,clock,focus,commands,logs,actions=scenario()
    if phase=='start':ns['SHARED']['want']=True
    if phase=='end':ns['SHARED']['end_seq']=1
    if phase=='stop':ns['STOP'].set()
    if phase=='after_focus':
        activate=ns['cleanup_focus']
        def changed(win):
            activate(win);ns['SHARED']['end_seq']=1;return True
        ns['cleanup_focus']=changed
    try:ns['service_anti_idle'](slots)
    except (ns['Preempt'],ns['StopMacro']):pass
    assert not commands
print('PASS start/end transitions and Stop preempt anti-idle, including an event ending during foreground activation')


ns,slots,clock,focus,commands,logs,actions=scenario()
def end_during_hold(seconds):
    clock.now+=seconds;ns['SHARED']['end_seq']=1;ns['STOP'].set()
ns['time'].sleep=end_during_hold
ns['service_anti_idle'](slots)
assert [f for h,s,f,t in commands]==[8,10]
print('PASS event end/Stop during the 120ms hold still releases Space without selecting any hotbar slot')


ns,slots,clock,focus,commands,logs,actions=scenario()
slots.invalid.add(1)
for _ in range(4):ns['service_anti_idle'](slots)
assert [h for h,s,f,t in commands if f==8]==[1,3,4]
ns['S']['afk_enabled']=False;clock.now+=1000
ns['service_anti_idle'](slots)
assert len(commands)==6
print('PASS excluded windows are skipped without remapping peers; the saved disabled setting is respected')


# Run the actual main scheduler through 30 simulated minutes in paths that used
# to skip maintenance forever. Its urgent handler must run before each heartbeat.
for mode in ('cleanup','early_end','active'):
    ns,slots,clock,focus,commands,logs,actions=scenario()
    deadline=clock.now+1800
    class Stop:
        def is_set(self):return clock.now>=deadline
        def wait(self,seconds):clock.now+=max(seconds,.5)
    ns['STOP']=Stop()
    urgent=[]
    class Monitor:
        def __init__(self,*a):self.stop=threading.Event();self.changed_at=clock.wall
        def start(self):pass
        def join(self):pass
    class Detector(Monitor):
        def start(self):
            if mode=='cleanup':ns['_tl'].putaway_pending={1:{}}
            if mode=='early_end':ns['SHARED']['event_ending']=True
            if mode=='active':
                ns['SHARED'].update(want=True,holding=True,event_priority=True)
                ns['_tl'].equip_pending={1:{}}
    def putaway(_):urgent.append(('cleanup',clock.now))
    def retry(_):urgent.append(('equip',clock.now))
    def forbidden(*a,**kw):raise AssertionError('Slow maintenance must stay suspended in these paths')
    ns.update(scan_windows=lambda **kw:slots,validate_runtime_start=lambda _:True,
              Detector=Detector,SafetyMonitor=Monitor,service_putaway=putaway,
              retry_event_equips=retry,clear_event_scans=lambda:None,
              maintenance=forbidden,refresh_mutation_progress=forbidden,
              retry_hidden_hotbars=forbidden,check_idle_equipment=forbidden)
    original=ns['_send_scan']
    def ordered(scan,flags):
        if flags==8 and mode!='early_end':
            assert urgent and 0<=clock.now-urgent[-1][1]<.2
        original(scan,flags)
    ns['_send_scan']=ordered
    try:ns['job_macro']()
    except ns['StopMacro']:pass
    else:raise AssertionError('Replay did not stop at its deadline')
    assert not any('[error]' in m for m in logs),logs[-5:]
    for hwnd in range(1,5):
        times=[t for h,s,f,t in commands if h==hwnd and f==8]
        assert len(times)>=7,(mode,hwnd,times)
        assert max(b-a for a,b in zip(times,times[1:]))<243,(mode,times)
    assert all(s==57 for h,s,f,t in commands)
    print(f'PASS actual scheduler: 30-minute {mode} replay services all four windows within configured interval; urgent actions run first')


ns,slots,clock,focus,commands,logs,actions=scenario()
ns['scan_windows']=lambda **kw:slots
ns['SHARED'].update(want=False,holding=True,end_seq=2,handled_end_seq=1)
prior=dict(ns['SHARED'])
ns['job_test_anti_idle']()
assert [h for h,s,f,t in commands if f==8]==[1,2,3,4]
assert ns['_tl'].run_slots is None
assert ns['SHARED']==prior
print('PASS standalone diagnostic visits every window without OCR/clicks/slot input; stale stopped-run transitions are isolated and restored')
print('Windows acceptance, visible jumping and the server idle timer still require a live check on Windows.')
