"""Cooperative cancellation of optional work; foreground owns the account."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time

from .base import ProviderError

_background: ContextVar[threading.Event | None] = ContextVar('optional_research', default=None)
_scheduled: ContextVar[tuple | None] = ContextVar('scheduled_model_work', default=None)


def check_background():
    scheduled = _scheduled.get()
    if scheduled is not None and scheduled[1] is not None:
        scheduled[1]()
    signal = _background.get()
    if signal is not None and signal.is_set():
        raise ProviderError('后台研究已让出通道，完成的步骤已保存', 409, code='background_preempted')


def is_background():
    return _background.get() is not None or _scheduled.get() is not None


def request_priority():
    scheduled = _scheduled.get()
    return scheduled[0] if scheduled else 4 if _background.get() is not None else 0


def check_admission():
    scheduled = _scheduled.get()
    if scheduled is not None and scheduled[2] is not None:
        scheduled[2]()


@contextmanager
def scheduled_work(rank, check=None, admission=None):
    """Yield at request admission, preserving an already running generation.

    Rank may be a cheap callable so a waiting paragraph can be promoted live.
    Unlike optional research cancellation, foreground activity never invalidates
    a response in flight. Explicit task cancellation is checked independently.
    """
    token = _scheduled.set((rank, check, admission))
    try:
        yield
    finally:
        _scheduled.reset(token)


class ResearchPriority:
    def __init__(self):
        self._lock = threading.Lock()
        self._signal = None
        self._work_id = None
        self._yield_to_reading = True
        self._last_activity = time.monotonic()
        self._readers: dict[str, float] = {}
        self._foreground = 0

    def foreground(self):
        with self._lock:
            self._last_activity = time.monotonic()
            active = self._signal is not None
            if active:
                self._signal.set()
            return active

    def presence(self, client_id: str, reading: bool):
        with self._lock:
            if reading:
                self._readers[client_id] = time.monotonic()
                self._last_activity = time.monotonic()
                if self._signal is not None and self._yield_to_reading:
                    self._signal.set()
            else:
                self._readers.pop(client_id, None)

    def idle(self, seconds: float):
        with self._lock:
            now = time.monotonic()
            self._readers = {key: seen for key, seen in self._readers.items() if now - seen < 45}
            return not self._readers and not self._foreground and now - self._last_activity >= seconds

    def foreground_busy(self):
        with self._lock:
            return self._foreground > 0

    def prefer(self, work_id: str):
        """Yield other optional work, keeping this same in-flight source alive."""
        with self._lock:
            if self._signal is not None and self._work_id != work_id:
                self._signal.set()

    @contextmanager
    def foreground_work(self):
        with self._lock:
            self._foreground += 1
            self._last_activity = time.monotonic()
            interrupted = self._signal is not None
            if interrupted:
                self._signal.set()
        try:
            yield interrupted
        finally:
            with self._lock:
                self._foreground -= 1
                self._last_activity = time.monotonic()

    def cancel(self):
        with self._lock:
            if self._signal is not None:
                self._signal.set()


@contextmanager
def background_call(priority: ResearchPriority, *, yield_to_reading=True, work_id=None):
    signal = threading.Event()
    with priority._lock:
        priority._signal = signal
        priority._work_id = work_id
        priority._yield_to_reading = yield_to_reading
        if priority._foreground:
            signal.set()
    token = _background.set(signal)
    try:
        yield signal
    finally:
        _background.reset(token)
        with priority._lock:
            if priority._signal is signal:
                priority._signal = None
                priority._work_id = None
