"""Fair, task-reentrant serialization for shared persistence roots."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from weakref import WeakValueDictionary


MutationScope = tuple[str, str]

CALENDAR_SHARED_SCOPE: MutationScope = ("calendar", "shared")
REMINDER_STORE_SCOPE: MutationScope = ("reminder", "store")
REMINDER_SENT_LOG_SCOPE: MutationScope = ("reminder", "sent_log")
POLL_STORE_SCOPE: MutationScope = ("poll", "store")
WATCHLIST_STORE_SCOPE: MutationScope = ("watchlist", "store")
QUOTE_STORE_SCOPE: MutationScope = ("quote", "store")
BIRTHDAY_STORE_SCOPE: MutationScope = ("birthday", "store")
MEMORY_STORE_SCOPE: MutationScope = ("memory", "store")


@dataclass(slots=True)
class _Ticket:
    task: asyncio.Task[object]
    ready: asyncio.Future[None]
    granted: bool = False


class _FairReentrantLock:
    __slots__ = ("_owner", "_depth", "_waiters", "__weakref__")

    def __init__(self) -> None:
        self._owner: asyncio.Task[object] | None = None
        self._depth = 0
        self._waiters: deque[_Ticket] = deque()

    @staticmethod
    def _current_task() -> asyncio.Task[object]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("mutation_scope_requires_task")
        return task

    def _grant_next(self) -> None:
        if self._owner is not None:
            return
        while self._waiters:
            ticket = self._waiters.popleft()
            if ticket.ready.cancelled():
                continue
            self._owner = ticket.task
            self._depth = 1
            ticket.granted = True
            ticket.ready.set_result(None)
            return

    async def acquire(self) -> None:
        task = self._current_task()
        if self._owner is task:
            self._depth += 1
            return

        ready = asyncio.get_running_loop().create_future()
        ticket = _Ticket(task=task, ready=ready)
        self._waiters.append(ticket)
        self._grant_next()
        try:
            await ready
        except asyncio.CancelledError:
            if ticket.granted and self._owner is task:
                self._owner = None
                self._depth = 0
                self._grant_next()
            else:
                try:
                    self._waiters.remove(ticket)
                except ValueError:
                    pass
                self._grant_next()
            raise

    def release(self) -> None:
        task = self._current_task()
        if self._owner is not task:
            raise RuntimeError("mutation_scope_not_owned")
        self._depth -= 1
        if self._depth:
            return
        self._owner = None
        self._grant_next()


class MutationCoordinator:
    def __init__(self) -> None:
        self._locks: WeakValueDictionary[MutationScope, _FairReentrantLock] = (
            WeakValueDictionary()
        )

    def _lock_for(self, scope: MutationScope) -> _FairReentrantLock:
        lock = self._locks.get(scope)
        if lock is None:
            lock = _FairReentrantLock()
            self._locks[scope] = lock
        return lock

    @asynccontextmanager
    async def hold(self, scope: MutationScope) -> AsyncIterator[None]:
        lock = self._lock_for(scope)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
