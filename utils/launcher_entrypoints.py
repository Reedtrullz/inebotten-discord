"""Explicit frozen/source worker modes, dispatched before Tk or app configuration."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading


MODES = frozenset({'--run-bot','--run-bridge','--run-research-worker','--smoke-ui'})


def worker_command(mode, source_path):
    if mode not in MODES:raise ValueError('unsupported_worker_mode')
    if getattr(sys,'frozen',False):return [sys.executable,mode]
    return [sys.executable,'-u',str(source_path),mode]


def _stream_from_handle(descriptor, mode):
    """Recover inherited pipe handles in a windowed frozen executable."""
    try:
        handle=os.dup(descriptor)
    except OSError:
        if os.name!='nt':raise
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetStdHandle.argtypes=[wintypes.DWORD];kernel.GetStdHandle.restype=wintypes.HANDLE
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        kernel.DuplicateHandle.argtypes=[wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,
                                        ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.DuplicateHandle.restype=wintypes.BOOL
        source=kernel.GetStdHandle({0:-10,1:-11,2:-12}[descriptor])
        if not source or source==wintypes.HANDLE(-1).value:raise OSError('worker_pipe_unavailable')
        duplicate=wintypes.HANDLE();process=kernel.GetCurrentProcess()
        if not kernel.DuplicateHandle(process,source,process,ctypes.byref(duplicate),0,False,2):
            raise OSError('worker_pipe_duplication_failed')
        handle=msvcrt.open_osfhandle(duplicate.value,os.O_RDONLY if mode=='r' else os.O_WRONLY)
    return os.fdopen(handle,mode,encoding='utf-8',errors='replace',buffering=1)


def ensure_worker_stdio():
    for descriptor,name,mode in ((0,'stdin','r'),(1,'stdout','w'),(2,'stderr','w')):
        if getattr(sys,name) is None:setattr(sys,name,_stream_from_handle(descriptor,mode))


def _cooperative_gate():
    if os.environ.pop('INEBOTTEN_LAUNCHER_GATE','')!='1':return
    if sys.stdin.readline(16)!='start\n':raise SystemExit(3)
    def control():
        try:
            if sys.stdin.readline(16)=='stop\n':
                if os.name=='nt':signal.raise_signal(signal.SIGTERM)
                else:os.kill(os.getpid(),signal.SIGTERM)
        except (OSError,ValueError):pass
    threading.Thread(target=control,daemon=True,name='inebotten-launcher-control').start()


def dispatch_worker(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if not args:return False
    if len(args)!=1 or args[0] not in MODES:raise SystemExit('unsupported_launcher_mode')
    configure_frozen_tls()
    ensure_worker_stdio()
    mode=args[0]
    if mode=='--smoke-ui':
        from scripts.check_desktop_lifecycle import main
        raise SystemExit(main(ui_only=True))
    if mode=='--run-research-worker':
        from scripts.search_worker import main
        raise SystemExit(main() or 0)
    _cooperative_gate()
    if mode=='--run-bridge':
        import asyncio
        from ai.hermes_bridge_server import main
        raise SystemExit(asyncio.run(main()) or 0)
    from scripts.run_both import main
    raise SystemExit(main())


def configure_frozen_tls():
    """Use the shipped CA bundle before clients cache their SSL contexts.

    Preserve explicitly configured trust; never disable TLS verification.
    """
    if not getattr(sys, 'frozen', False):return
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())


def bundle_root():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))


def configure_source_tk():
    """Use the matching bundled Tcl/Tk libraries in a relocated source Python.

    Frozen hooks own their library paths. This changes only this process; it does
    not install or modify a user's Python or override explicit Tcl/Tk settings.
    """
    if getattr(sys,'frozen',False):return
    import _tkinter
    root=Path(sys.base_prefix)/'lib'
    for variable,directory,marker in (('TCL_LIBRARY','tcl'+_tkinter.TCL_VERSION,'init.tcl'),
                                      ('TK_LIBRARY','tk'+_tkinter.TK_VERSION,'tk.tcl')):
        path=root/directory
        if (path/marker).is_file():os.environ.setdefault(variable,str(path))
