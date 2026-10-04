"""Advisory single-writer ownership for cooperating local processes."""
from __future__ import annotations

import os
from pathlib import Path


class StoreOwnedError(RuntimeError):
    pass


class ProcessOwnership:
    """Hold an OS lock until close; lock files are never removed or replaced."""
    def __init__(self, path: Path):
        self.path = Path(path).with_name(Path(path).name + '.lock')
        self._handle = None

    def acquire(self):
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    handle.write(b'\0')
                handle.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise StoreOwnedError('store_owned') from error
        self._handle = handle

    def close(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __del__(self):
        self.close()
