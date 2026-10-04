"""Advisory single-writer ownership for cooperating local processes."""
from __future__ import annotations

import os
import stat
from pathlib import Path


class StoreOwnedError(RuntimeError):
    pass


class ProcessOwnership:
    """Hold an OS lock until close; lock files are never removed or replaced."""
    def __init__(self, path: Path):
        self.path = Path(path).with_name(Path(path).name + '.lock')
        self._handle = None
        self._unlock = None

    def acquire(self):
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except OSError as error:
            raise StoreOwnedError('unsafe_lock') from error
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or self.path.is_symlink():
            os.close(descriptor)
            raise StoreOwnedError('unsafe_lock')
        handle = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    handle.write(b'\0')
                handle.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                self._unlock = lambda h, locking=msvcrt.locking, flag=msvcrt.LK_UNLCK: locking(h.fileno(), flag, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._unlock = lambda h, flock=fcntl.flock, flag=fcntl.LOCK_UN: flock(h.fileno(), flag)
        except OSError as error:
            handle.close()
            raise StoreOwnedError('store_owned') from error
        self._handle = handle

    def close(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if self._unlock is not None:
                self._unlock(handle)
        finally:
            handle.close()

    def __del__(self):
        try:
            self.close()
        except OSError:
            pass
