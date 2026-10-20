"""In-process change notifications per batch, for the review screen's live updates (SSE).

The pipeline writes from worker threads (`asyncio.to_thread`) and from the event loop; `bump` is safe from both.
Only a version number travels: the client re-fetches the batch, so no field value ever passes through here.
"""
import asyncio
import threading
from typing import Dict, Optional, Set, Tuple

_lock = threading.Lock()
_versions: Dict[int, int] = {}
# each listener remembers the loop it waits on, so a bump from any thread wakes it on that loop
_waiters: Dict[int, Set[Tuple[asyncio.Event, asyncio.AbstractEventLoop]]] = {}


def version(batch_id: int) -> int:
    with _lock:
        return _versions.get(batch_id, 0)


def bump(batch_id: Optional[int]) -> None:
    """Something in this batch changed. Never raises: notifications are best-effort."""
    if batch_id is None:
        return
    with _lock:
        _versions[batch_id] = _versions.get(batch_id, 0) + 1
        waiters = list(_waiters.get(batch_id, ()))
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    for ev, loop in waiters:
        if loop is running:
            ev.set()
        elif not loop.is_closed():
            loop.call_soon_threadsafe(ev.set)


async def wait_change(batch_id: int, seen: int, timeout: float) -> int:
    """Wait until the batch version passes `seen` (or the timeout); returns the current version."""
    entry = (asyncio.Event(), asyncio.get_running_loop())
    with _lock:
        _waiters.setdefault(batch_id, set()).add(entry)
        current = _versions.get(batch_id, 0)
    try:
        if current == seen:
            try:
                await asyncio.wait_for(entry[0].wait(), timeout)
            except asyncio.TimeoutError:
                pass
        return version(batch_id)
    finally:
        with _lock:
            group = _waiters.get(batch_id)
            if group is not None:
                group.discard(entry)
                if not group:
                    _waiters.pop(batch_id, None)
