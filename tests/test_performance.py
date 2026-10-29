"""Performance invariants that retain fresh event frames and truthful preview state."""
import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT/'hallows_eve_macro.py').read_text(encoding='utf-8'))
clock = NS(now=100.)
ns = dict(cv2=cv2, np=np, DATA_LOCK=threading.Lock(), PREVIEW={},
          time=NS(monotonic=lambda: clock.now))
for node in tree.body:
    if (getattr(node, 'name', '') in {'publish_preview', 'title_mask', 'BannerMatcher'} or
            isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'EVENT_TEMPLATE_PNG' for t in node.targets)):
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'macro', 'exec'), ns)

frame = np.zeros((80, 400, 3), np.uint8)
sample_times = set()
for i in range(25):
    clock.now = 100 + i*.04
    frame.fill(i)
    ns['publish_preview']('banner', frame, f'Frame {i}')
    sample_times.add(ns['PREVIEW']['banner'][2])
assert 4 <= len(sample_times) <= 5
saved = ns['PREVIEW']['banner'][0].copy()
frame.fill(255)
assert np.array_equal(ns['PREVIEW']['banner'][0], saved), 'captures must remain immutable to readers'
clock.now += .01
ns['publish_preview']('banner', None, 'Covered')
assert ns['PREVIEW']['banner'] == (None, 'Covered', clock.now)
clock.now += .01
ns['publish_preview']('banner', frame, 'Visible again')
assert ns['PREVIEW']['banner'][2] == clock.now
ns['publish_preview']('hotbar_0', frame, 'Window 1')
assert 'hotbar_0' in ns['PREVIEW']
print(f'PASS 25 diagnostic frames publish {len(sample_times)} image copies; covered/recovered states are immediate and keys remain independent')

a, b = ns['BannerMatcher'](), ns['BannerMatcher']()
assert a.templates is b.templates and not a.templates[0].flags.writeable
positive = cv2.imread(str(Path(__file__).parent/'fixtures/event.png'))
negative = cv2.imread(str(Path(__file__).parent/'fixtures/no_event.png'))
assert a.score(positive) >= .78
assert a.last_match is not None and b.last_match is None
assert a.score(negative) < .58
assert a.score(positive) >= .78
assert a.score(np.zeros_like(positive)) == 0
started = time.perf_counter()
for _ in range(500):
    ns['BannerMatcher']()
print(f'PASS cached immutable template bank with independent per-matcher state; 500 warm initializations in {(time.perf_counter()-started)*1000:.1f} ms')
print('PASS real positive/negative/banner-return sequence; no game verdicts or hotbar readings are cached')
