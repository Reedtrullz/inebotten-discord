"""One owned child/group with bounded events; the Tk thread owns every widget.

A pending or unconfirmed stop retains ownership. No PID/name lookup is used to
adopt or terminate an existing service. Platform groups are created only for the
child returned by this controller's Popen call.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import json
import os
import secrets
import select
import signal
import subprocess
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from utils.logger import diagnostic_line


def _is_windows():
    return os.name == 'nt'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def loopback_probe(port, nonce):
    if type(port) is not int or not 1<=port<=65535:return None
    request=Request(f'http://127.0.0.1:{port}/health',headers={'X-Launcher-Probe':nonce})
    try:
        with build_opener(ProxyHandler({}),_NoRedirect()).open(request,timeout=.75) as response:
            raw=response.read(8193)
        if len(raw)>8192:return None
        return json.loads(raw)
    except (OSError,ValueError):return None


@dataclass(frozen=True)
class LauncherEvent:
    kind: str
    message: str


class PosixOwnedGroup:
    def __init__(self, process):
        self.process = process
        self.group_id = process.pid  # Popen(start_new_session=True) creates this session/group.
        self._sealed = process.returncode is not None
        self._gone = self._sealed
        self._exited = None
        self._queue = None
        if self._sealed:
            return
        if hasattr(os, 'waitid') and hasattr(os, 'WNOWAIT'):
            self._observer = 'waitid'
        elif hasattr(select, 'kqueue'):
            self._observer = 'kqueue'
            self._queue = select.kqueue()
            try:
                event = select.kevent(process.pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
                                     fflags=select.KQ_NOTE_EXIT)
                self._queue.control([event], 0, 0)
            except BaseException:
                self._queue.close()
                raise
        else:
            raise OSError('owned_exit_observer_unavailable')

    def peek_exit(self):
        # Reaping a leader frees its numeric PID/PGID. Retain that identity until
        # every permitted group signal is finished, then use Popen's real status.
        if self._sealed:
            return self.process.poll()
        if self.process.returncode is not None:
            self._sealed = True
            self._gone = True
            return self.process.returncode
        if self._exited is not None:
            return self._exited
        if self._observer == 'waitid':
            status = os.waitid(os.P_PID, self.group_id, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if status is not None:
                self._exited = 0  # observation only; Popen supplies the final exit code
        elif self._queue.control([], 1, 0):
            self._exited = 0  # NOTE_EXIT data is not a portable wait status
        return self._exited

    def is_alive(self):
        if self._gone:
            return False
        try:
            os.killpg(self.group_id, 0)
            return True
        except ProcessLookupError:
            self._gone = True
            return False
        except PermissionError:
            # Darwin filters zombies from group signals and returns EPERM when
            # nothing signalable remains. It can also mean a protected member;
            # neither case proves that the group is gone.
            return True

    def _signal(self, value):
        if self._sealed or self.process.returncode is not None:
            self._sealed = True
            return
        try:
            os.killpg(self.group_id, value)
        except ProcessLookupError:
            self._gone = True
        except PermissionError:
            # Seal after the final attempt, reap the owned leader, then require
            # an absent group before releasing admission. A protected survivor
            # keeps ownership pending; we never retry a recycled group number.
            if value != signal.SIGKILL:
                return
        if value == signal.SIGKILL:
            # No further group signal is allowed after this point, even if the
            # group number is later reused by an unrelated service.
            self._sealed = True

    def terminate(self):
        self._signal(signal.SIGTERM)

    def kill(self):
        self._signal(signal.SIGKILL)

    def close(self):
        if self._queue is not None:
            self._queue.close()
            self._queue = None


def owned_group(process):
    if _is_windows():
        from utils.launcher_windows import WindowsOwnedJob
        return WindowsOwnedJob(process)
    return PosixOwnedGroup(process)


class LauncherController:
    def __init__(self, *, popen_factory=None, group_factory=None, probe=None,
                 event_capacity=256, poll_interval=.1):
        self._main_thread = threading.get_ident()
        if popen_factory is not None:
            self._popen = popen_factory
        elif _is_windows():
            from utils.launcher_windows import WindowsSuspendedPopen
            self._popen = WindowsSuspendedPopen
        else:
            self._popen = subprocess.Popen
        self._requires_trusted_gate = group_factory is None
        self._group_factory = group_factory or owned_group
        self._probe = probe or (lambda nonce: None)
        self._logs = deque(maxlen=max(1,min(event_capacity,1024)))
        self._state_event = None
        self._lock = threading.RLock()
        self._active = False
        self._state = 'exited'
        self._stop = threading.Event()
        self._stop_deadline = None
        self._generation = 0
        self._poll_interval = max(.005,min(poll_interval,1))
        self._thread = None
        self._process = None

    @property
    def active(self):
        with self._lock:return self._active

    @property
    def state(self):
        with self._lock:return self._state

    def _emit(self, kind, message, generation):
        with self._lock:
            if generation != self._generation:return
            event=LauncherEvent(kind, diagnostic_line(str(message))[:2048])
            if kind=='state':
                self._state = message
                self._state_event = event
            else:self._logs.append(event)

    def drain(self, maximum=100):
        if threading.get_ident()!=self._main_thread:
            raise RuntimeError('main_thread_required')
        with self._lock:
            result=[]
            if self._state_event is not None:
                result.append(self._state_event);self._state_event=None
            for _ in range(max(0,min(maximum,1024)-len(result))):
                if not self._logs:break
                result.append(self._logs.popleft())
            return result

    def start(self, command, *, cwd=None, env=None):
        with self._lock:
            if self._active:return False
            if not command or any(not isinstance(arg,str) or '\x00' in arg for arg in command):
                raise ValueError('invalid_child_command')
            if self._requires_trusted_gate and command[-1]!='--run-bot':
                raise ValueError('trusted_bot_mode_required')
            self._active=True;self._generation+=1
            generation=self._generation
            self._logs.clear();self._stop.clear();self._stop_deadline=None
            self._emit('state','starting',generation)
            environment=dict(os.environ if env is None else env)
            nonce=secrets.token_urlsafe(24)
            environment['INEBOTTEN_LAUNCHER_INSTANCE']=nonce
            environment['INEBOTTEN_LAUNCHER_GATE']='1'
            self._thread=threading.Thread(target=self._run,args=(list(command),cwd,environment,nonce,generation),
                                          daemon=True,name='inebotten-launcher-owner')
            self._thread.start()
            return True

    def stop(self, deadline):
        with self._lock:
            if not self._active:return
            deadline=float(deadline)
            if not math.isfinite(deadline):raise ValueError('invalid_stop_deadline')
            self._stop_deadline=min(deadline,self._stop_deadline) if self._stop_deadline is not None else deadline
            self._stop.set()
            self._emit('state','stopping',self._generation)

    def _read_output(self, process, generation):
        try:
            stream=process.stdout
            if stream is None:return
            while True:
                line=stream.readline(2049)
                if not line:break
                if len(line)>2048:
                    while line and not line.endswith('\n'):line=stream.readline(2049)
                    self._emit('log','[Lang logglinje utelatt]',generation)
                    continue
                self._emit('log',line.rstrip(),generation)
        except (OSError,ValueError):
            pass

    def _run(self, command, cwd, environment, nonce, generation):
        process=group=reader=None
        terminated=killed=False
        try:
            kwargs={'stdin':subprocess.PIPE,'stdout':subprocess.PIPE,'stderr':subprocess.STDOUT,'text':True,
                    'encoding':'utf-8','errors':'replace','bufsize':1,'cwd':cwd,'env':environment}
            if _is_windows():
                from utils.launcher_windows import CREATE_SUSPENDED
                kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP|CREATE_SUSPENDED
            else:kwargs['start_new_session']=True
            process=self._popen(command,**kwargs)
            self._process=process
            group=self._group_factory(process)
            input_stream=getattr(process,'stdin',None)
            if input_stream is not None and not self._stop.is_set():
                input_stream.write('start\n');input_stream.flush()
            reader=threading.Thread(target=self._read_output,args=(process,generation),daemon=True,
                                    name='inebotten-launcher-output')
            reader.start()
            while True:
                code=group.peek_exit() if hasattr(group,'peek_exit') else process.poll()
                if code is not None and not self._stop.is_set():
                    self.stop(time.monotonic()+10)
                if self._stop.is_set():
                    if not terminated:
                        terminated=True
                        input_stream=getattr(process,'stdin',None)
                        if input_stream is not None and not input_stream.closed:
                            try:input_stream.write('stop\n');input_stream.flush()
                            except (OSError,ValueError):pass
                        try:group.terminate()
                        except OSError:self._emit('log','Avslutningssignalet kunne ikke sendes',generation)
                    with self._lock:deadline=self._stop_deadline
                    if time.monotonic()>=deadline and group.is_alive() and not killed:
                        killed=True
                        try:group.kill()
                        except OSError:self._emit('log','Tvungen avslutning kunne ikke bekreftes',generation)
                    if killed and hasattr(group,'peek_exit'):group.peek_exit()
                    if not group.is_alive() and process.poll() is not None and not reader.is_alive():
                        break
                    if killed:self._emit('state','degraded',generation)
                else:
                    try:health=self._probe(nonce)
                    except Exception:health=None
                    state='connecting'
                    if isinstance(health,dict) and health.get('launcher_instance')==nonce:
                        if health.get('status')=='healthy' and health.get('readiness')=='ready':state='ready'
                        elif health.get('status')=='degraded' or health.get('readiness')=='degraded':state='degraded'
                    if self.state!=state:self._emit('state',state,generation)
                time.sleep(self._poll_interval)
            group.close()
            if reader is not None:reader.join(timeout=.5)
            stream=getattr(process,'stdout',None)
            if stream is not None and hasattr(stream,'close'):stream.close()
            input_stream=getattr(process,'stdin',None)
            if input_stream is not None and not input_stream.closed:input_stream.close()
            self._emit('log',f'Prosessen er avsluttet (kode {process.poll()})',generation)
            self._emit('state','exited',generation)
            with self._lock:self._active=False;self._process=None
        except Exception as error:
            if process is None:
                failed_process=getattr(error,'process',None)
                if getattr(failed_process,'_launcher_setup_failed',False):
                    process=failed_process
                    self._process=process
                    self._emit('log','Oppstartens opprydding er ikke bekreftet',generation)
                    self._emit('state','degraded',generation)
                    self._recover_owned(process,None,None,generation)
                else:
                    self._emit('log','Oppstart mislyktes',generation)
                    self._finish(generation)
            else:
                self._emit('log','Prosesskontrollen krever gjennomgang',generation)
                self._emit('state','degraded',generation)
                self._recover_owned(process,group,reader,generation)

    def _finish(self, generation):
        self._emit('state','exited',generation)
        with self._lock:self._active=False;self._process=None

    def _recover_owned(self, process, group, reader, generation):
        # A Windows child is still suspended if job assignment failed; POSIX
        # children remain behind the cooperative stdin gate. Recover only through
        # the process/group handles created for this launch, and retain ownership
        # until exit and output-reader closure are both confirmed.
        if group is None:
            try:process.kill()
            except OSError:pass
        else:
            try:group.kill()
            except OSError:pass
        while True:
            try:
                alive=group.is_alive() if group is not None else process.poll() is None
                if not alive and process.poll() is not None and (reader is None or not reader.is_alive()):
                    if getattr(process,'_launcher_setup_failed',False):
                        for name in ('_thread_handle','_handle'):
                            handle=getattr(process,name,None)
                            if handle is not None:
                                handle.Close()
                                setattr(process,name,None)
                        process._launcher_setup_failed=False
                    if group is not None:group.close()
                    for name in ('stdout','stdin'):
                        stream=getattr(process,name,None)
                        if stream is not None and hasattr(stream,'close') and not getattr(stream,'closed',False):stream.close()
                    self._finish(generation)
                    return
            except OSError:pass
            time.sleep(max(.05,self._poll_interval))
