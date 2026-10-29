"""Event-priority regressions with real image processing and mocked Windows input."""
import ast, cv2, numpy as np, threading, queue, time, re, difflib
from pathlib import Path
from types import SimpleNamespace as NS
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / 'hallows_eve_macro.py').read_text(encoding='utf-8'))
names = {'WindowUnavailable','FrameUnavailable','clear_event_scans','send_tracked_key','initialize_run','window_task','guard_window','StopMacro','Preempt','preemptible','check_stop','sleep','ocr','title_mask',
         'EventCountdown','read_countdown_image','BannerMatcher','EventTitleWatch','EventDebouncer','Detector','finish_event',
         'event_equip_allowed','event_equip_slot','verify_event_selection','confirm_event_equip','attempt_event_equip','retry_event_equips','unequip_character','equip_character','manual_fallback_state','press_char','job_macro','service_anti_idle'}
ns = dict(cv2=cv2,np=np,threading=threading,queue=queue,time=time,re=re,difflib=difflib,
          FutureTimeout=FutureTimeout,OCR_EXECUTOR=ThreadPoolExecutor(max_workers=2),
          OCR_TIMEOUT=5.0,EVENT_END_CONFIRM_SECONDS=.16,POLL_SECONDS=.08,MAX_HOLD_SECONDS=600,
          _tl=threading.local(),STOP=threading.Event(),UI=queue.Queue(),DATA_LOCK=threading.Lock(),
          SHARED=dict(want=False,holding=False,end_seq=0,handled_end_seq=0,event_priority=False),
          log=lambda _:None,close_capture=lambda:None,notify_webhook=lambda *a:None)
for node in tree.body:
    if getattr(node,'name','') in names or isinstance(node,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id in {'IDLE_FOCUS_AUDIT_SECONDS','EVENT_TEMPLATE_PNG','POLL_SECONDS','EVENT_END_CONFIRM_SECONDS','EQUIP_SAMPLE_SECONDS','EQUIP_CONFIRM_SECONDS','EQUIP_RETRY_SECONDS'} for t in node.targets):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)

# A blocked OCR result cannot delay the input worker or restart its old task.
entered, release = threading.Event(), threading.Event()
def blocked_ocr(*a,**kw):
    entered.set(); release.wait(2); return 'stale OCR result'
ns['pytesseract']=NS(image_to_string=blocked_ocr,TesseractNotFoundError=type('Missing', (Exception,), {}))
ns['_tl'].automation=True
def end_during_ocr():
    assert entered.wait(1)
    ns['SHARED'].update(end_seq=1,ended_at=time.monotonic(),want=True,holding=True)
t=threading.Thread(target=end_during_ocr);t.start()
started=time.monotonic()
try:
    with ns['preemptible'](): ns['ocr'](np.zeros((20,20),np.uint8))
except ns['Preempt']: pass
else: raise AssertionError('latched end must interrupt even when want == holding')
latency=time.monotonic()-started
release.set();t.join()
assert latency < .25,latency
print(f'PASS slow OCR interrupted by latched event-end in {latency*1000:.0f} ms; stale result discarded')

# Use real reference images to exercise both visual and OCR-assisted starts.
positive=cv2.imread(str(Path(__file__).parent / 'fixtures' / 'event.png'))
negative=cv2.imread(str(Path(__file__).parent / 'fixtures' / 'no_event.png'))
window=NS(left=0,top=0,w=1004,h=790,hwnd=1)
ns.update(event_window=lambda *a:window,passive_window=lambda *a:window,region_visible=lambda *a:True,
          tracked_overlap=lambda *a:False,EVENT_REGION=None,publish_preview=lambda *a:None)
def pause(reason): raise AssertionError(reason)
ns['safety_pause']=pause
def wait_for(predicate,limit=2):
    started=time.monotonic()
    while not predicate() and time.monotonic()-started<limit:time.sleep(.005)
    assert predicate()
    return time.monotonic()-started

for fast in (True,False):
    frame={'img':negative.copy() if fast else positive.copy()}
    ns['grab']=lambda *a:frame['img']
    ns['SHARED'].update(want=False,holding=False,end_seq=0,handled_end_seq=0)
    ns['S']={'fast_detection':fast,'unequip_lead_seconds':0}
    def slow_read(win):
        captured=frame['img'].copy()
        time.sleep(.8)
        return bool(np.array_equal(captured,positive)),'Hallows',captured
    ns['read_event']=slow_read
    det=ns['Detector']([1]);det.start()
    if fast:time.sleep(.05);frame['img']=positive.copy()
    start_delay=wait_for(lambda:ns['SHARED']['want'])
    # Countdown/lower banner scenery can change while the title remains.
    changed=positive.copy();changed[60:]=0;frame['img']=changed
    time.sleep(.3);assert ns['SHARED']['want']
    if fast:
        ns['region_visible']=lambda *a:False
        ns['tracked_overlap']=lambda *a:True
        frame['img']=negative.copy();time.sleep(.3)
        assert ns['SHARED']['want'], 'occlusion is not an observed event end'
        ns['region_visible']=lambda *a:True
        ns['tracked_overlap']=lambda *a:False
    frame['img']=negative.copy()
    delay=wait_for(lambda:not ns['SHARED']['want'])
    assert delay<.65,delay
    assert ns['SHARED']['end_seq']==1
    time.sleep(.3);assert not ns['SHARED']['want']
    det.stop.set();det.join(3);assert not det.is_alive()
    print(f'PASS {"visual" if fast else "OCR-assisted"} start: end detected in {delay*1000:.0f} ms; countdown change ignored')

# Slow positive OCR from an event that has already vanished cannot resurrect it.
frame={'img':positive.copy()};ns['grab']=lambda *a:frame['img'];ns['S']={'fast_detection':False,'unequip_lead_seconds':0}
ns['SHARED'].update(want=False,holding=False,end_seq=0,handled_end_seq=0)
det=ns['Detector']([1]);det.start();time.sleep(.1);frame['img']=negative.copy()
time.sleep(1.1);assert not ns['SHARED']['want']
det.stop.set();det.join(3)
print('PASS stale positive OCR rejected against current banner')

# A transition during a key hold must not lose the successfully sent command.
ns['SHARED'].update(want=True,holding=True,end_seq=0,handled_end_seq=0)
ns['S']={'dracula_rotation':False,'char_key':'3','settle':0}
ns['SLOT_KEYS']='1234567890';ns['STEP_DELAY']=.35
ns['_tl'].commanded_slots={};ns['_tl'].last_character_keys={}
ns.update(focus=lambda _:True,cleanup_focus=lambda _:True,event_slot_observation=lambda *a:(0,10),
          win32gui=NS(GetForegroundWindow=lambda:1),
          sleep=lambda _:ns['check_stop']())
def tap_then_end(key):
    ns['SHARED'].update(want=False,end_seq=1,ended_at=time.monotonic())
ns['tap_key']=tap_then_end
try:
    with ns['preemptible']():ns['equip_character'](NS(hwnd=1,name='Main',slot=0))
except ns['Preempt']:pass
assert ns['_tl'].commanded_slots=={1:3}
print('PASS manual equip command is tracked even when the event ends during the keypress')

wins=[NS(hwnd=i,slot=i-1,name=f'Window {i}') for i in (1,2,3)]
ns.update(restore_main=lambda _:None)

# Actual scheduler: no retries/maintenance/rebirth during either active event.
events=[];loop={'n':0}
class Slots:
    restore_requested=threading.Event()
    def __len__(self):return 1
    def all(self):return [wins[0]]
    def win(self,i):return wins[0]
class FakeMonitor:
    def __init__(self,*a):self.stop=threading.Event();self.changed_at=time.time()
    def start(self):pass
    def join(self):pass
class FakeDetector(FakeMonitor):
    def start(self):ns['SHARED'].update(want=True,event_priority=True)
def tick():
    loop['n']+=1
    if loop['n']==3:ns['SHARED'].update(end_seq=1,want=True) # end/start before worker runs
    if loop['n']==5:ns['SHARED'].update(end_seq=2,want=False)
    if loop['n']>9:raise AssertionError('scheduler did not resume idle tasks')
def cleanup(_):
    events.append('cleanup');ns['SHARED']['handled_end_seq']=ns['SHARED']['end_seq']
    ns['SHARED']['holding']=False
def idle_maintenance(*a,**kw):
    assert not ns['SHARED']['want'] and not ns['SHARED']['holding']
    events.append('maintenance');raise ns['StopMacro']()
def idle_mutations(*a):
    assert not ns['SHARED']['want'] and not ns['SHARED']['holding']
    events.append('mutations')
ns.update(scan_windows=lambda **kw:Slots(),validate_runtime_start=lambda _:True,
          Detector=FakeDetector,SafetyMonitor=FakeMonitor,PROGRESS={},DRACULA_NOTIFIED=set(),
          check_stop=tick,finish_event=cleanup,MAINTENANCE_SECONDS=20,
          run_on_all=lambda *a:events.append('equip'),all_complete=lambda *a:False,
          retry_hidden_hotbars=lambda _:events.append('retry'),maintenance=idle_maintenance,
          refresh_mutation_progress=idle_mutations, check_idle_equipment=lambda _:None,
          S={'afk_enabled':False,'dracula_rotation':True,'rebirth':[True]*4,'rebirth_seconds':60})
try:ns['job_macro']()
except ns['StopMacro']:pass
assert events==['equip','cleanup','equip','cleanup','mutations','retry','maintenance'],events
print('PASS active events suspend all chores; cleanup precedes a back-to-back event and idle work resumes afterward')
ns['OCR_EXECUTOR'].shutdown(wait=True)
print('Windows focus and input are mocked. Measured timings are local replay results, not live Roblox guarantees.')
