"""Four-window latency/recovery replay. Focus/input delays are simulated."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
support = ast.parse((Path(__file__).parent/'test_equip_confirmation.py').read_text(encoding='utf-8'))
base = {'__file__': __file__}
for node in support.body:
    if (isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
            isinstance(node, ast.Assign) and any(getattr(t, 'id', '') in
                {'ROOT', 'TREE', 'support', 'common'} for t in node.targets) or
            isinstance(node, ast.For) and getattr(node.target, 'id', '') == 'node'):
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'support', 'exec'), base)


def scenario(smart=False, dropped=None):
    ns = base['load']()
    real_press = ns['press_char']
    _, clock, state, _, hidden, advance = base['game'](ns)
    ns['_live'][4] = True
    state[4] = 0
    slots = ns['Slots']([1,2,3,4]); ns['_tl'].run_slots = slots
    ns['S'].update(settle=10, dracula_rotation=smart)
    commands, focuses, scans = [], [], []
    dropped = dict(dropped or {})
    original_snapshot = ns['hotbar_snapshot']
    def snapshot(win, read_labels=False):
        cards, img = original_snapshot(win, read_labels)
        for card in cards:
            card.box = (card.number*50,20,40,40)
        return cards, img
    def focus(win):
        if ns['_focus']['hwnd'] != win.hwnd:
            focuses.append(win.hwnd)
            advance(.08)
            ns['_focus']['hwnd'] = win.hwnd
        return True
    def tap(key, hold=.12):
        hwnd=ns['_focus']['hwnd']; target=10 if key=='0' else int(key)
        commands.append((hwnd,target,clock.now,hold))
        advance(hold)
        if dropped.get(hwnd,0):
            dropped[hwnd]-=1
        else:
            state[hwnd]=0 if state[hwnd]==target else target
    names = {'publish_progress','cleanup_one_window','send_putaway','confirm_putaway_in_place','confirm_putaway',
             'service_putaway','finish_event','read_mutation'}
    for node in base['TREE'].body:
        if (getattr(node,'name','') in names or isinstance(node,ast.Assign) and
                any(getattr(t,'id','').startswith('CLEANUP_') for t in node.targets)):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'macro','exec'),ns)
    ns.update(cleanup_focus=focus,press_char=real_press,tap_key=tap,
              hotbar_snapshot=snapshot,restore_main=lambda _:None,
              equipment_observation=lambda w:0 if state[w.hwnd] in (0,1) else state[w.hwnd],
              repair_cleanup_popup=lambda _:None,DRACULA_NOTIFIED=set())
    if smart:
        ns['SHARED']['holding']=False
        for win in slots.all():
            ns['publish_progress'](win, snapshot(win)[0])
        ns['SHARED']['holding']=True
        def mutation(img,box,allow_ocr=True):
            assert not allow_ocr
            scans.append(box)
            return False,'no red label'
        ns['read_mutation']=mutation
        ns['stable_hotbar']=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Full scan delayed first inputs'))
    return ns,slots,clock,state,commands,focuses,advance,scans


for smart in (False,True):
    ns,slots,clock,state,commands,focuses,advance,scans=scenario(smart)
    started=clock.now; ns['SHARED']['equipping']=True
    for win in slots.all(): ns['attempt_event_equip'](win)
    ns['SHARED']['equipping']=False
    first_sweep=clock.now-started
    confirmed_at=clock.now
    assert [h for h,_,_,_ in commands]==[1,2,3,4]
    assert all(v==2 for v in state.values())
    assert first_sweep < 1.2 and commands[0][2]-started < .15
    assert all(hold==.10 for *_,hold in commands)
    assert not ns['_tl'].equip_pending, 'Two post-input frames must confirm in the original focus visit'
    before=list(focuses)
    advance(.05); ns['retry_event_equips'](slots)
    assert not ns['_tl'].equip_pending and len(commands)==4
    assert focuses==before, 'Visible hotbars should verify without another focus sweep'
    assert not ns['_tl'].event_input
    print(f'PASS {"smart" if smart else "manual"} four-window first sweep {first_sweep:.3f}s; '
          f'first input {commands[0][2]-started:.3f}s; all confirmed by {confirmed_at-started:.3f}s '
          '(simulated, with saved normal focus delay=10s)')


# All four commands go out before a dropped first input is retried.
ns,slots,clock,state,commands,focuses,advance,scans=scenario(True,dropped={1:1})
ns['SHARED']['equipping']=True
for win in slots.all(): ns['attempt_event_equip'](win)
ns['SHARED']['equipping']=False
for _ in range(40):
    advance(.1); ns['retry_event_equips'](slots)
    if not ns['_tl'].equip_pending: break
assert not ns['_tl'].equip_pending and all(v==2 for v in state.values())
assert [h for h,_,_,_ in commands]==[1,2,3,4,1]
assert commands[-1][2]-commands[0][2] >= 2
print('PASS missed first input does not block peers; only the missed window retries after the late-input guard')


# Stale smart plans must never bypass a changed layout or a new red mutation.
for changed in ('red','count','type','size'):
    ns,slots,clock,state,commands,focuses,advance,scans=scenario(True)
    win=slots.win(0); snapshot=ns['hotbar_snapshot']
    if changed=='red': ns['read_mutation']=lambda *a,**kw:(None,'needs OCR')
    elif changed=='size': ns['_tl'].prepared_equips[1]['size']=(1,1)
    else:
        def altered(win,read_labels=False):
            cards,img=snapshot(win,read_labels)
            if changed=='count': cards.pop()
            else: cards[1].kind='item'
            return cards,img
        ns['hotbar_snapshot']=altered
    ns['SHARED']['equipping']=True
    ns['attempt_event_equip'](win)
    assert not commands and set(ns['_tl'].equip_pending)=={1}
    assert 0 < ns['_tl'].equip_pending[1]['retry_at']-clock.now <= .05
print('PASS changed layout/type/size or red mutation defers full scanning without a guessed equip')


# Fast label screening never starts Tesseract on a red label.
ns,slots,clock,state,commands,focuses,advance,scans=scenario()
img=ns['np'].zeros((80,120,3),ns['np'].uint8); box=(20,35,60,40)
ns['ocr']=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Fast path invoked OCR'))
assert ns['read_mutation'](img,box,allow_ocr=False)[0] is False
ns['cv2'].putText(img,'Dracula',(20,31),ns['cv2'].FONT_HERSHEY_SIMPLEX,.3,(0,0,255),1)
assert ns['read_mutation'](img,box,allow_ocr=False)[0] is None
print('PASS actual red-label screening defers OCR; blank label is eligible')


# Cleanup confirms each responsive window before leaving it. No return sweep
# is needed, including when windows overlap.
ns,slots,clock,state,commands,focuses,advance,scans=scenario()
state.update({1:2,2:3,3:4,4:5}); ns['_tl'].commanded_slots=state.copy()
ns['_tl'].exit_keys={h:'1' for h in state}
ns['SHARED'].update(want=False,holding=True,end_seq=1,ended_at=clock.now)
started=clock.now
ns['finish_event'](slots)
first_sweep=clock.now-started; before=list(focuses)
assert not ns['_tl'].putaway_pending
confirmed_at=clock.now
assert [h for h,_,_,_ in commands]==[1,2,3,4] and first_sweep < 1.0
advance(.07); ns['service_putaway'](slots)
assert not ns['_tl'].putaway_pending and focuses==before
assert not ns['_tl'].prepared_equips if hasattr(ns['_tl'],'prepared_equips') else True
print(f'PASS four-window unequip first sweep {first_sweep:.3f}s; all confirmed by '
      f'{confirmed_at-started:.3f}s; zero extra confirmation focus switches (simulated)')


# Overlapping windows: confirmation takes two frames on the same focus visit,
# rather than requiring another complete sweep for the second frame.
ns,slots,clock,state,commands,focuses,advance,scans=scenario()
ns['region_visible']=lambda win,region: ns['_focus']['hwnd']==win.hwnd
state.update({1:2,2:3,3:4,4:5}); ns['_tl'].commanded_slots=state.copy()
ns['_tl'].exit_keys={h:'1' for h in state}
ns['SHARED'].update(want=False,holding=True,end_seq=1,ended_at=clock.now)
ns['finish_event'](slots); before=len(focuses)
assert not ns['_tl'].putaway_pending
advance(.07); ns['service_putaway'](slots)
assert not ns['_tl'].putaway_pending and len(focuses)==before
assert len(commands)==4
print('PASS overlapping cleanup confirms in the original input visit, with zero return visits')
print('Local simulated timings exclude screenshot processing, real Windows activation and Roblox rendering/network delays.')
