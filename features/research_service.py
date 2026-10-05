"""Bounded SDK work and inert source cards; no application credentials in workers."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


@dataclass(frozen=True)
class ResearchCard:
    url: str
    title: str
    content_kind: str
    published_at: str | None
    fetched_at: datetime
    source: str
    text: str | None

    def document(self):
        value = asdict(self)
        value['fetched_at'] = self.fetched_at.isoformat()
        return value


def run_sdk_worker(provider, query, max_results, region, timeout, key, *, script=None):
    offline = os.getenv('INEBOTTEN_OFFLINE_TESTS') == '1' or os.getenv('INEBOTTEN_OFFLINE') == '1'
    if script is None and offline:
        raise RuntimeError('offline_provider_disabled')
    frozen = bool(getattr(sys, 'frozen', False))
    if frozen and script is not None:
        raise ValueError('frozen_worker_override_refused')
    if provider not in ('tavily', 'google', 'duckduckgo'):
        raise ValueError('unsupported_search_provider')
    path = script or Path(__file__).resolve().parents[1] / 'scripts' / 'search_worker.py'
    command = [sys.executable,'--run-research-worker'] if frozen else [sys.executable,'-I','-X','utf8',str(path)]
    payload = {'provider': provider, 'query': query, 'max_results': max_results,
               'region': region, 'timeout': timeout, 'key': key if provider == 'tavily' else None}
    with tempfile.TemporaryDirectory(prefix='inebotten-search-') as home:
        environment = {'HOME': home, 'USERPROFILE': home, 'APPDATA': home,
                       'LOCALAPPDATA': home, 'XDG_CONFIG_HOME': home,
                       'HERMES_HOME': home, 'PATH': os.path.dirname(sys.executable) + os.pathsep + os.defpath}
        if offline:
            environment['INEBOTTEN_OFFLINE'] = '1'
            environment['INEBOTTEN_OFFLINE_TESTS'] = '1'
        if os.name == 'nt' and 'SYSTEMROOT' in os.environ:
            environment['SYSTEMROOT'] = os.environ['SYSTEMROOT']
        try:
            result = subprocess.run(command,
                input=json.dumps(payload).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=home, env=environment, timeout=max(.01, timeout), check=False)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and joins the child, including SDK threads.
            raise TimeoutError('provider_process_deadline') from None
    if result.returncode or len(result.stdout) > 262144:
        raise RuntimeError('provider_worker_failed')
    reply = json.loads(result.stdout)
    if not isinstance(reply, dict):
        raise RuntimeError('invalid_provider_reply')
    if reply.get('status') != 'ok' or not isinstance(reply.get('results'), list):
        raise RuntimeError(str(reply.get('reason', 'provider_unavailable'))[:64])
    return reply['results'][:max_results]


class ResearchWorkers:
    """Two admitted tasks, zero waiter queue; native work owns its slot to completion."""
    def __init__(self, worker=None):
        self.worker = worker or run_sdk_worker
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='inebotten-research')
        self.pending = set()
        self.lock = threading.Lock()
        self.closed = False

    @property
    def count(self):
        with self.lock:
            return len(self.pending)

    def _finished(self, future):
        with self.lock:
            self.pending.discard(future)

    async def run(self, *args, deadline):
        with self.lock:
            if self.closed or len(self.pending) >= 2:
                raise RuntimeError('provider_busy')
            if deadline <= time.monotonic():
                raise TimeoutError('research_deadline')
            future = self.executor.submit(self.worker, *args)
            self.pending.add(future)
        # A fast task may already be done: register outside the lock.
        future.add_done_callback(self._finished)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        done, _ = await asyncio.wait({wrapped}, timeout=max(0, deadline - time.monotonic()))
        if not done or time.monotonic() >= deadline:
            raise TimeoutError('research_deadline')
        return wrapped.result()

    async def close(self):
        with self.lock:
            self.closed = True
            pending = list(self.pending)
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(future) for future in pending), return_exceptions=True)
        await asyncio.to_thread(self.executor.shutdown, wait=True)
