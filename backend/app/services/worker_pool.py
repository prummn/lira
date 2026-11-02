"""Bounded daemon workers. Persisted queues, not executor futures, own the work."""
import logging
import threading
import time


class WorkerPool:
    def __init__(self, name, tick, limit, *, maximum=16):
        self.name, self.tick, self.limit = name, tick, limit
        self.maximum = maximum
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.threads = []

    def can_start(self):
        alive = any(thread.is_alive() for thread in self.threads)
        if alive and self.stop_event.is_set():
            raise RuntimeError('Worker pool is still draining its previous requests')
        return not alive

    def start(self):
        if not self.can_start():
            return
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self._loop, args=(slot,),
            name=f'{self.name}-{slot + 1}', daemon=True) for slot in range(self.maximum)]
        for thread in self.threads:
            thread.start()

    def _loop(self, slot):
        while not self.stop_event.is_set():
            progressed = False
            try:
                if slot < max(1, min(self.maximum, self.limit())):
                    progressed = bool(self.tick())
            except Exception:
                # Exceptions can contain source text or credentials.
                logging.getLogger(__name__).error('%s step failed; durable checkpoint retained', self.name)
            if not progressed:
                self.wake_event.wait(.5)
                self.wake_event.clear()

    def wake(self):
        self.wake_event.set()

    def stop(self, timeout=5):
        self.stop_event.set()
        self.wake()
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
