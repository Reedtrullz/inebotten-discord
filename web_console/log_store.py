"""Private, bounded diagnostic tails; never read audit or account stores."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import diagnostic_line
from utils.store_ownership import ProcessOwnership


class DiagnosticLogs:
    def __init__(self, path: Path, max_bytes: int, retention_days: int):
        if type(max_bytes) is not int or not 16384 <= max_bytes <= 128 * 1024 * 1024:
            raise ValueError('invalid_log_budget')
        if type(retention_days) is not int or not 1 <= retention_days <= 90:
            raise ValueError('invalid_log_retention')
        self.path, self.max_bytes, self.days = path, max_bytes, retention_days
        self.segment_bytes = max_bytes // 4
        self.paths = [path] + [path.with_name(f'logs.{n}.jsonl') for n in range(1, 4)]
        self.owner = ProcessOwnership(path)
        self.key = secrets.token_bytes(32)
        # Cursor keys are process-local. Keep a bounded generation for each
        # live segment too: filesystems can immediately recycle deleted inodes.
        self._generations = {}
        self._last_maintenance = None

    def _identity(self, info):
        inode = (info.st_dev, info.st_ino)
        if inode not in self._generations:
            self._generations[inode] = secrets.token_hex(16)
        return f'{info.st_dev}:{info.st_ino}:{self._generations[inode]}'

    def _forget(self, info):
        self._generations.pop((info.st_dev, info.st_ino), None)

    def _discard(self, path):
        if path.exists() or path.is_symlink():
            info = self._info(path)
            path.unlink()
            self._forget(info)

    def _open(self, path, flags):
        fd = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
            os.close(fd)
            raise ValueError('unsafe_log_file')
        return os.fdopen(fd, 'rb' if flags == os.O_RDONLY else 'ab')

    def _info(self, path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('unsafe_log_file')
        return info

    @staticmethod
    def _private(handle, path):
        if hasattr(os, 'fchmod'):
            os.fchmod(handle.fileno(), 0o600)
        else:
            os.chmod(path, 0o600)

    @staticmethod
    def _label(value, default):
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value) else default

    def append(self, *, line, level='INFO', component='runtime', outcome='observed', request_id=None):
        self.owner.acquire()
        row = {'ts': datetime.now(timezone.utc).isoformat(), 'line': diagnostic_line(line)[:700],
               'level': level if level in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL') else 'INFO',
               'component': self._label(component, 'runtime'), 'outcome': self._label(outcome, 'observed'),
               'request_id': self._label(request_id, None)}
        raw = (json.dumps(row, ensure_ascii=False) + '\n').encode()
        cutoff = time.time() - self.days * 86400
        maintain = (self._last_maintenance is None
                    or time.monotonic() - self._last_maintenance >= 60)
        for path in self.paths:
            if path.exists() or path.is_symlink():
                info = self._info(path)
                if info.st_mtime < cutoff:
                    self._discard(path)
                elif maintain or info.st_size > self.segment_bytes:
                    self._maintain(path, info.st_size, cutoff)
        if maintain:
            self._last_maintenance = time.monotonic()
        size = self._info(self.path).st_size if self.path.exists() else 0
        if size + len(raw) > self.segment_bytes:
            self._discard(self.paths[-1])
            for index in range(2, -1, -1):
                if self.paths[index].exists():
                    self.paths[index].replace(self.paths[index + 1])
        with self._open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND) as handle:
            self._private(handle, self.path)
            handle.write(raw)

    def _maintain(self, path, size, cutoff):
        """Age cleanup on writes reads at most one segment from each fixed file."""
        with self._open(path, os.O_RDONLY) as handle:
            start = max(0, size - self.segment_bytes)
            handle.seek(start)
            raw = handle.read(self.segment_bytes)
        tail = raw[raw.find(b'\n') + 1:] if start else raw
        kept = []
        for chunk in tail.splitlines():
            try:
                row = json.loads(chunk)
                timestamp = datetime.fromisoformat(row['ts'])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if timestamp.timestamp() < cutoff:
                    continue
                if not isinstance(row.get('line'), str):
                    continue
                row['line'] = diagnostic_line(row['line'])[:700]
                # Strip unknown fields; legacy records can carry arbitrary private metadata.
                row = {'ts': timestamp.isoformat(), 'line': row['line'],
                       'level': self._label(row.get('level'), 'INFO'),
                       'component': self._label(row.get('component'), 'runtime'),
                       'outcome': self._label(row.get('outcome'), 'observed'),
                       'request_id': self._label(row.get('request_id'), None)}
                kept.append((json.dumps(row, ensure_ascii=False) + '\n').encode())
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
        replacement = b''.join(kept)
        while len(replacement) > self.segment_bytes and kept:
            kept.pop(0)
            replacement = b''.join(kept)
        if replacement == raw and not start:
            with self._open(path, os.O_RDONLY) as handle:
                self._private(handle, path)
            return
        fd, name = tempfile.mkstemp(prefix='.log-retention-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(replacement)
            previous = self._info(path)
            os.replace(name, path)
            self._forget(previous)
        finally:
            Path(name).unlink(missing_ok=True)

    def _encode(self, state):
        raw = json.dumps(state, separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(raw + hmac.digest(self.key, raw, 'sha256')).decode()

    def _decode(self, cursor, filters):
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise ValueError()
            data = base64.b64decode(cursor, altchars=b'-_', validate=True)
            raw, signature = data[:-32], data[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, raw, 'sha256')):
                raise ValueError()
            state = json.loads(raw)
            if state['filters'] != filters:
                raise ValueError()
            return state
        except (ValueError, KeyError, TypeError):
            raise ValueError('invalid_cursor') from None

    def read(self, cursor, max_bytes, filters):
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 262144:
            raise ValueError('invalid_read_budget')
        if not isinstance(filters, dict) or set(filters) - {'level', 'component', 'outcome', 'request_id'}:
            raise ValueError('invalid_filters')
        if any(self._label(v, None) is None for v in filters.values()):
            raise ValueError('invalid_filters')
        available = {}
        snapshot = []
        live_inodes = set()
        for path in self.paths:
            if path.exists() or path.is_symlink():
                info = self._info(path)
                live_inodes.add((info.st_dev, info.st_ino))
                identity = self._identity(info)
                available[identity] = (path, info.st_size)
                snapshot.append([identity, info.st_size])
        self._generations = {inode: generation for inode, generation in self._generations.items()
                             if inode in live_inodes}
        state = self._decode(cursor, filters) if cursor else {'files': snapshot, 'filters': filters}
        files = state['files']
        if any(identity not in available or offset > available[identity][1] for identity, offset in files):
            raise ValueError('stale_cursor')
        records, bytes_read = [], 0
        cutoff = time.time() - self.days * 86400
        while files and bytes_read < max_bytes:
            identity, end = files[0]
            if end == 0:
                files.pop(0)
                continue
            start = max(0, end - (max_bytes - bytes_read))
            with self._open(available[identity][0], os.O_RDONLY) as handle:
                if self._identity(os.fstat(handle.fileno())) != identity:
                    raise ValueError('stale_cursor')
                handle.seek(start)
                raw = handle.read(end - start)
            bytes_read += len(raw)
            boundary = raw.find(b'\n') + 1 if start else 0
            if start and not boundary:
                files[0][1] = start  # bounded progress through an oversized legacy row
                break
            files[0][1] = start + boundary
            for chunk in reversed(raw[boundary:].splitlines()):
                if len(chunk) > 4096:
                    continue
                try:
                    row = json.loads(chunk)
                    ts = datetime.fromisoformat(row['ts'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts.timestamp() < cutoff or ts.timestamp() > time.time() + 60:
                        continue
                    row = {'ts': ts.isoformat(), 'line': diagnostic_line(row['line'])[:700],
                           'level': self._label(row.get('level'), 'INFO'),
                           'component': self._label(row.get('component'), 'runtime'),
                           'outcome': self._label(row.get('outcome'), 'observed'),
                           'request_id': self._label(row.get('request_id'), None)}
                    if all(row[k] == value for k, value in filters.items()):
                        records.append(row)
                except (ValueError, KeyError, TypeError, OverflowError):
                    continue
            if not start:
                files.pop(0)
        return {'records': records, 'next_cursor': self._encode(state) if files else None,
                'truncated': bool(files), 'bytes_read': bytes_read}

    def close(self):
        self.owner.close()
