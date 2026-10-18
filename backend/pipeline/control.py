"""Pause / cancel for a running batch. In-memory: a restart drops running work anyway.

Stages call `checkpoint` between steps, so a pause or cancel takes effect before the next
stage starts; a Claude call already in flight is allowed to finish.
"""
import asyncio
from typing import Dict, Set

_paused: Set[int] = set()
_cancelled: Set[int] = set()
_resume: Dict[int, asyncio.Event] = {}


class BatchCancelled(Exception):
    pass


def is_paused(batch_id: int) -> bool:
    return batch_id in _paused


def is_cancelled(batch_id: int) -> bool:
    return batch_id in _cancelled


def pause(batch_id: int) -> None:
    _paused.add(batch_id)
    _resume.setdefault(batch_id, asyncio.Event()).clear()


def resume(batch_id: int) -> None:
    _paused.discard(batch_id)
    if batch_id in _resume:
        _resume[batch_id].set()


def cancel(batch_id: int) -> None:
    _cancelled.add(batch_id)
    resume(batch_id)  # wake paused workers so they can stop


def clear(batch_id: int) -> None:
    _paused.discard(batch_id)
    _cancelled.discard(batch_id)
    _resume.pop(batch_id, None)


async def checkpoint(batch_id: int) -> None:
    """Block while paused; raise BatchCancelled if the batch was cancelled."""
    while batch_id in _paused and batch_id not in _cancelled:
        await _resume.setdefault(batch_id, asyncio.Event()).wait()
    if batch_id in _cancelled:
        raise BatchCancelled()
