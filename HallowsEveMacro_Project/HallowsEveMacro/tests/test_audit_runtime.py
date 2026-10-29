"""3.5 audit regressions: background planning, freshness, receipts and bounded work."""
import ast
import json
from concurrent.futures import Future
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_runtime import UiMailbox, BoundedExecutor, atomic_settings, validated_settings

source=ast.parse((Path(__file__).parent/'test_fast_events.py').read_text(encoding='utf-8'))
support={'__file__':__file__}
for node in source.body:
    if (isinstance(node,(ast.Import,ast.ImportFrom,ast.FunctionDef)) or
            isinstance(node,ast.Assign) and any(getattr(t,'id','') in {'ROOT','support','base'} for t in node.targets) or
            isinstance(node,ast.For) and getattr(node.target,'id','')=='node'):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'support','exec'),support)
TREE=ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))


class ControlledPool:
    def __init__(self):self.jobs=[]
    def submit(self,fn,*args):
        future=Future();self.jobs.append((future,fn,args));return future
    def complete(self,index=0):
        future,fn,args=self.jobs[index]
        future.set_result(fn(*args))


def scenario():
    ns,slots,clock,state,commands,focuses,advance,_=support['scenario']()
    for node in TREE.body:
        if getattr(node,'name','') in {'activate_manual_fallback','event_rotation_scan','scan_mutations_offscreen','clear_event_scans',
                'refresh_mutation_progress','read_event','x_glyph_present','verified_close_marker',
                'close_welcome_popup','close_robux_popup'}:
            exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
    pool=ControlledPool();ns['ROTATION_EXECUTOR']=pool
    ns['_tl'].rotation_scans={};ns['_tl'].hotbar_waits={}
    ns['S']['dracula_rotation']=True
    original=ns['hotbar_snapshot']
    version={'value':b'original'}
    def snapshot(win,read_labels=False):
        cards,_=original(win,read_labels)
        for c in cards:
            c.fingerprint=version['value']+bytes([c.number]);c.text='' 
        return cards,ns['np'].zeros((80,600,3),ns['np'].uint8)
    ns['hotbar_snapshot']=snapshot
    ns['read_mutation']=lambda *a,**kw:(False,'no red label')
    return ns,slots,clock,state,commands,focuses,advance,pool,version


# Slow OCR owns no foreground; ready peers may equip before it finishes.
ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
assert ns['event_rotation_scan'](slots.win(0))=='scanning'
before=list(focuses)
ns['_focus']['hwnd']=2
for _ in range(100):
    assert ns['event_rotation_scan'](slots.win(0))=='scanning'
assert focuses==before and not commands and len(pool.jobs)==1
ns['event_equip_slot'](slots.win(1),2)
assert state[2]==2 and state[1]==0
pool.complete()
assert ns['event_rotation_scan'](slots.win(0))=='fixed'
assert state[1]==2 and [c[0] for c in commands]==[2,1]
print('PASS pending background OCR performs no focus changes; another window equips first; fresh matching result equips once')


for change in ('inventory','resize','end','unknown'):
    ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
    win=slots.win(0)
    assert ns['event_rotation_scan'](win)=='scanning'
    if change=='unknown':ns['read_mutation']=lambda *a,**kw:(None,'unreadable')
    pool.complete()
    if change=='inventory':version['value']=b'reordered'
    if change=='resize':win=NS(**vars(win));win.w=1000;win.h=790
    if change=='end':ns['SHARED'].update(want=False,end_seq=1)
    assert ns['event_rotation_scan'](win) in ('needs_scan','scanning','skipped')
    assert not commands and state[1]==0
print('PASS inventory changes, resized windows, ended events and unknown labels reject stale scan results')


ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
ns['event_rotation_scan'](slots.win(0))
scan=ns['_tl'].rotation_scans[1]
ns['clear_event_scans']()
assert scan['cancel'].is_set() and scan['future'].cancelled() and not ns['_tl'].rotation_scans
print('PASS cleanup cancels outstanding scan work and discards its event-specific state')


# Bounded pool exercises real threads rather than an instant fake executor.
executor=BoundedExecutor(2,'AuditTest');gate=threading.Event()
try:
    first=executor.submit(gate.wait,2);second=executor.submit(gate.wait,2)
    assert first is not None and second is not None
    assert all(executor.submit(lambda:1) is None for _ in range(1000))
    gate.set();first.result(timeout=3);second.result(timeout=3)
    assert executor.submit(lambda:7).result(timeout=1)==7
finally:
    gate.set();executor.shutdown(wait=True)
print('PASS two-worker scan pool rejects 1000 excess submissions without growing a queue; capacity is reusable')


# Latest status wins and critical controls bypass a noisy log producer.
mail=UiMailbox(log_limit=100,control_limit=10)
for i in range(100000):
    mail.put(('log',str(i)));mail.put(('state',i%4,bool(i%2)))
mail.put(('event_end',100,False))
assert mail.qsize()<=115 and mail.get_nowait()[0]=='event_end'
messages=[]
while not mail.empty():messages.append(mail.get_nowait())
assert len([m for m in messages if m[0]=='state'])==4
assert any('discarded' in m[1] for m in messages if m[0]=='log')
print('PASS 100000-message stress keeps mailbox bounded and event control responsive; overflow is reported')


# Invalid persisted values do not corrupt startup or overwrite prior good files.
defaults=next(n.value for n in TREE.body if isinstance(n,ast.Assign) and
              any(getattr(t,'id','')=='DEFAULTS' for t in n.targets))
defaults=eval(compile(ast.Expression(defaults),'defaults','eval'),{'DEFAULT_TESSERACT':''})
raw=dict(defaults,char_key='22',settle='bad',afk_minutes=float('nan'),rebirth=[True],start_vk=119,stop_vk=119)
valid=validated_settings(raw,defaults)
assert valid['char_key']=='2' and valid['settle']==defaults['settle']
assert valid['rebirth']==[False]*4 and valid['start_vk']!=valid['stop_vk']
assert validated_settings(dict(defaults,char_key='0',webhook_url='https://example.invalid/secret'),defaults)['char_key']=='0'
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'settings.json';atomic_settings(path,valid)
    previous=path.read_bytes()
    try:atomic_settings(path,{'bad':float('nan')})
    except ValueError:pass
    else:raise AssertionError('Invalid serialization must fail')
    assert path.read_bytes()==previous and len(list(Path(folder).iterdir()))==1
print('PASS settings validation preserves supported values; failed atomic save keeps the previous settings intact')


# A key-down accepted by Windows remains tracked when key-up fails.
ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
def release_error(win,label,key=None):
    ns['_tl'].on_key_down()
    raise RuntimeError('simulated release failure')
ns['press_char']=release_error
ns['attempt_event_equip'](slots.win(0))  # no plan: async; directly exercise slot below
try:ns['event_equip_slot'](slots.win(0),2)
except RuntimeError:pass
else:raise AssertionError('Release error should reach recovery')
assert ns['_tl'].commanded_slots[1]==2 and ns['_tl'].event_equips[1]['attempts']==1
assert ns['_tl'].on_key_down is None
print('PASS accepted key-down is retained for cleanup even when release fails; receipt hook is restored')


# Failed post-event scans must be retried while idle, not forgotten until start.
ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
ns.update(reveal_for_scan=lambda s,i:s.win(i),stable_hotbar=lambda *a,**kw:None)
ns['refresh_mutation_progress'](slots)
assert set(ns['_tl'].hotbar_waits)=={1,2,3,4}
print('PASS failed post-event scans schedule independent idle retries for every window')


# The crop is not accepted if the window moved since its coordinates were read.
ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
win=slots.win(0);ns['_frame_rect']=lambda h:(10,20,1014,810)
try:ns['guard_window'](win)
except ns['FrameUnavailable']:pass
else:raise AssertionError('Stale coordinates accepted')
assert not slots.is_invalid(0)
print('PASS stale window geometry is rejected without misclassifying a valid window as disconnected')


# A single fuzzy title word is no longer sufficient for OCR fallback start.
ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
ns['grab']=lambda *a:ns['np'].zeros((60,240,3),ns['np'].uint8)
ns['EVENT_REGION']=None
for text,expected in [('Hallows Eve',True),('HallowsEve',True),('Hallows shop',False),('Shallows wave',False)]:
    ns['ocr']=lambda *a,**kw:text
    assert ns['read_event'](slots.win(0))[0] is expected
print('PASS OCR fallback requires the complete Hallows Eve title and rejects partial/similar words')


# Close controls: both diagonals required; solid buttons and plus signs rejected.
cv2,np=ns['cv2'],ns['np']
for colour,background in [(255,30),(10,240)]:
    img=np.full((40,40,3),background,np.uint8)
    cv2.line(img,(12,12),(27,27),(colour,)*3,3)
    cv2.line(img,(27,12),(12,27),(colour,)*3,3)
    assert ns['x_glyph_present'](img)
for symbol in ('solid','plus','empty'):
    img=np.zeros((40,40,3),np.uint8)
    if symbol=='solid':cv2.rectangle(img,(10,10),(30,30),(255,)*3,-1)
    elif symbol=='plus':
        cv2.line(img,(10,20),(30,20),(255,)*3,3);cv2.line(img,(20,10),(20,30),(255,)*3,3)
    assert not ns['x_glyph_present'](img)
ns.update(popup_state=lambda w:{'robux'},robux_close_point=lambda w:None,
          click_abs=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Unverified click')))
assert ns['close_robux_popup'](slots.win(0)) is False
print('PASS X verification accepts light/dark crosses, rejects solid/plus/empty controls, and blocks unverified purchase-dialog clicks')


for target in (4,0):
    ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
    ns['read_mutation']=lambda img,box,**kw:(box[0]//50 < target if target else True,'read label')
    ns['event_rotation_scan'](slots.win(0));pool.complete()
    assert ns['event_rotation_scan'](slots.win(0)) in ('fixed','ok')
    assert state[1]==target and len(commands)==bool(target)
print('PASS background planning skips earlier Dracula slots; all-Dracula windows receive no equip input')


ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
ns['_tl'].hotbar_waits[1]={'slot':0,'since':clock.now-41,'attempts':3}
assert ns['event_rotation_scan'](slots.win(0))=='fixed'
assert 1 in ns['_tl'].manual_fallback and state[1]==2
print('PASS exhausted uncertain scans transition only that window to confirmed manual fallback')


ns,slots,clock,state,commands,focuses,advance,pool,version=scenario()
ns.update(reveal_for_scan=lambda *a:None)
assert ns['validate_visible_windows'](slots)
assert not slots.invalid and not ns['STOP'].is_set()
print('PASS temporary startup focus refusal preserves all valid windows for later recovery')


# Test event is no longer an unrelated legacy toggle path.
for node in TREE.body:
    if getattr(node,'name','')=='job_test_event' or isinstance(node,ast.Assign) and any(
            getattr(t,'id','')=='IDLE_FOCUS_AUDIT_SECONDS' for t in node.targets):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
ns['S']['dracula_rotation']=False
ns.update(scan_windows=lambda **kw:slots,validate_runtime_start=lambda _:True)
ns['job_test_event'](.1)
assert len(commands)==8 and all(v==0 for v in state.values())
assert not ns['_tl'].putaway_pending and not ns['_tl'].automation
print('PASS diagnostic event uses production equip/cleanup paths and confirms all four windows')
