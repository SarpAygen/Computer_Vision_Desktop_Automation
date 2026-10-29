"""Platform-independent infrastructure; no capture, Windows input or UI imports."""
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import queue
import tempfile
import threading


class UiMailbox:
    """Nonblocking bounded delivery. Latest per-window state replaces stale state.

    Control messages retain FIFO order. Logs have their own ring, so a noisy
    worker cannot bury stop/recovery/window state behind thousands of log lines.
    Overflow is reported explicitly; this mailbox never blocks input workers.
    """
    def __init__(self, log_limit=2000, control_limit=256):
        self.logs = deque(maxlen=log_limit)
        self.controls = deque(maxlen=control_limit)
        self.latest = OrderedDict()
        self.lock = threading.Lock()
        self.dropped = 0

    def put(self, message, *args, **kwargs):
        kind = message[0]
        with self.lock:
            if kind in {'state', 'rotation', 'progress', 'setup_check', 'cleanup', 'windows_found'}:
                key = (kind, message[1] if kind in {'state','rotation','progress','setup_check'} else None)
                self.latest[key] = message
                # Move updated state behind earlier distinct state messages.
                self.latest.move_to_end(key)
                if len(self.latest) > 64:
                    self.latest.popitem(last=False)
                    self.dropped += 1
            else:
                target = self.logs if kind == 'log' else self.controls
                if len(target) == target.maxlen:
                    self.dropped += 1
                target.append(message)

    put_nowait = put

    def get_nowait(self):
        with self.lock:
            if self.controls:
                return self.controls.popleft()
            if self.latest:
                return self.latest.popitem(last=False)[1]
            if self.dropped:
                count, self.dropped = self.dropped, 0
                return ('log', f'Warning: UI backlog discarded {count} older messages; latest states retained.')
            if self.logs:
                return self.logs.popleft()
        raise queue.Empty

    def qsize(self):
        with self.lock:
            return len(self.logs)+len(self.controls)+len(self.latest)

    def empty(self):
        return self.qsize() == 0


class BoundedExecutor:
    """At most capacity outstanding jobs, including running jobs; no backlog."""
    def __init__(self, capacity=2, name='MacroScan'):
        self.executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=name)
        self.permits = threading.BoundedSemaphore(capacity)

    def submit(self, fn, *args, **kwargs):
        if not self.permits.acquire(blocking=False):
            return None
        try:
            future = self.executor.submit(fn, *args, **kwargs)
        except BaseException:
            self.permits.release()
            raise
        future.add_done_callback(lambda _: self.permits.release())
        return future

    def shutdown(self, **kwargs):
        self.executor.shutdown(**kwargs)


def atomic_settings(path, values):
    """Preserve the previous settings if serialization or writing is interrupted."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(values, out, indent=2, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validated_settings(raw, defaults):
    """Keep compatible saved values; reject malformed types and unsafe keys."""
    values = {k: list(v) if isinstance(v, list) else v for k,v in defaults.items()}
    if not isinstance(raw, dict):
        return values
    bounds = {'settle': (0,10), 'afk_minutes': (.5,10), 'rebirth_seconds': (10,3600),
              'test_seconds': (3,300), 'unequip_lead_seconds': (0,10)}
    for key, default in defaults.items():
        value = raw.get(key, default)
        if isinstance(default, bool):
            if isinstance(value, bool): values[key] = value
        elif key in ('start_vk','stop_vk'):
            if type(value) is int and 8 <= value <= 254: values[key] = value
        elif key in bounds:
            if type(value) in (int,float) and math.isfinite(value):
                low, high = bounds[key]
                values[key] = type(default)(max(low,min(high,value)))
        elif key == 'rebirth':
            if isinstance(value,list) and len(value)==4 and all(type(x) is bool for x in value):
                values[key] = value[:]
        elif isinstance(default,str) and isinstance(value,str):
            values[key] = value
    if values['char_key'] not in '1234567890' or len(values['char_key']) != 1:
        values['char_key'] = defaults['char_key']
    if values['start_vk'] == values['stop_vk']:
        values['start_vk'], values['stop_vk'] = defaults['start_vk'], defaults['stop_vk']
    return values
