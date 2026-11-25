"""Small Python 3.8 compatibility helpers used by the runtime."""
from concurrent.futures import ThreadPoolExecutor
import threading


class CancellableThreadPoolExecutor(ThreadPoolExecutor):
    """Cancel queued work on shutdown without relying on Python 3.9 arguments."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_lock = threading.RLock()
        self._pending_futures = set()
        self._accepting_work = True

    def submit(self, fn, *args, **kwargs):
        with self._pending_lock:
            if not self._accepting_work:
                raise RuntimeError('Executor is shutting down')
            future = super().submit(fn, *args, **kwargs)
            self._pending_futures.add(future)
            future.add_done_callback(self._finished)
            return future

    def _finished(self, future):
        with self._pending_lock:
            self._pending_futures.discard(future)

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._pending_lock:
            self._accepting_work = False
            pending = list(self._pending_futures) if cancel_futures else []
        for future in pending:
            future.cancel()
        return super().shutdown(wait=wait)


def boolean_option(parser, name, *, default=False, help=None):
    """Equivalent positive/negative CLI switches on Python 3.8."""
    group = parser.add_mutually_exclusive_group()
    dest = name.replace('-', '_')
    group.add_argument('--'+name, dest=dest, action='store_true', help=help)
    group.add_argument('--no-'+name, dest=dest, action='store_false')
    parser.set_defaults(**{dest: default})
