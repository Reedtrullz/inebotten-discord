"""Explicit owned cleanup; deadlines retain unfinished work and honest receipts."""
from __future__ import annotations

import asyncio
import inspect
import math
import time


class OwnedResources:
    def __init__(self):
        self._entries = []
        self._driver = None
        self._closing = False

    def add(self, name, closer):
        if self._closing or any(entry['name'] == name for entry in self._entries):
            raise RuntimeError('resource_registration_closed_or_duplicate')
        self._entries.append({'name': name, 'closer': closer, 'task': None,
                              'closed': False, 'error': None})

    async def close(self, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('invalid_shutdown_deadline')
        self._closing = True
        if self._driver is None or self._driver.done():
            self._driver = asyncio.create_task(self._drain(deadline), name='owned-resource-cleanup')
        # Caller cancellation cannot erase the one owned cleanup driver.
        await asyncio.shield(self._driver)
        return self.receipt()

    @staticmethod
    async def _invoke(closer):
        if inspect.iscoroutinefunction(closer):
            await closer()
        else:
            result = await asyncio.to_thread(closer)
            if inspect.isawaitable(result):
                await result

    async def _drain(self, deadline):
        for entry in reversed(self._entries):
            if entry['closed']:
                continue
            if time.monotonic() >= deadline:
                return
            task = entry['task']
            if task is None or (task.done() and entry['error']):
                entry['error'] = None
                task = entry['task'] = asyncio.create_task(self._invoke(entry['closer']), name='close-' + entry['name'])
                # Retain and consume failures even after the deadline expires.
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - time.monotonic()))
            if not done:
                return
            if task.cancelled():
                entry['error'] = 'cancelled'
            else:
                error = task.exception()
                entry['error'] = type(error).__name__ if error else None
                entry['closed'] = error is None
            if entry['error']:
                # Later entries may depend on a writer that has not quiesced.
                return

    def receipt(self):
        pending = [entry['name'] for entry in self._entries
                   if entry['task'] is not None and not entry['task'].done()]
        errors = {entry['name']: entry['error'] for entry in self._entries if entry['error']}
        unclosed = [entry['name'] for entry in self._entries if not entry['closed']]
        return {'status': 'closed' if not unclosed else 'incomplete', 'pending': pending,
                'unclosed': unclosed, 'errors': errors}
