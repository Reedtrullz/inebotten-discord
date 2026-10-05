"""Owned launcher lifecycle and bounded event handoff; no real bot or account."""
import io
import threading
import time

import pytest

from utils.launcher_runtime import LauncherController


def eventually(predicate, timeout=2):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.005)
    assert predicate()


class Process:
    pid=123456
    def __init__(self, output=''):
        self.stdout=io.StringIO(output)
        self.returncode=None
    def poll(self):return self.returncode
    def wait(self,timeout=None):
        if self.returncode is None:raise TimeoutError()
        return self.returncode


class Group:
    def __init__(self, process, *, ignore_terminate=False, ignore_kill=False):
        self.process=process;self.alive=True;self.actions=[]
        self.ignore_terminate=ignore_terminate;self.ignore_kill=ignore_kill
    def is_alive(self):return self.alive
    def terminate(self):
        self.actions.append('terminate')
        if not self.ignore_terminate:self.alive=False;self.process.returncode=0
    def kill(self):
        self.actions.append('kill')
        if not self.ignore_kill:self.alive=False;self.process.returncode=-9
    def close(self):self.actions.append('close')


def controller(process=None, *, probe=None, ignore_terminate=False, ignore_kill=False, popen=None):
    process=process or Process()
    group=Group(process,ignore_terminate=ignore_terminate,ignore_kill=ignore_kill)
    calls=[]
    def spawn(*args,**kwargs):
        calls.append((args,kwargs))
        return popen(*args,**kwargs) if popen else process
    owner=LauncherController(popen_factory=spawn,group_factory=lambda p:group,
                             probe=probe or (lambda nonce:{'status':'starting','readiness':'starting','launcher_instance':nonce}),
                             poll_interval=.01,event_capacity=16)
    return owner,process,group,calls


def finish(owner):
    owner.stop(time.monotonic()+.05)
    eventually(lambda:not owner.active)


def fake_windows_job_api(monkeypatch,calls,*,assignment=True,resume=1):
    import utils.launcher_windows as windows

    def api(callback):
        def invoke(*args):return callback(*args)
        return invoke

    class Kernel:
        def __init__(self):
            self.CreateJobObjectW=api(lambda *_:(calls.append('create_job') or 101))
            self.SetInformationJobObject=api(lambda *_:(calls.append('set_limits') or True))
            self.AssignProcessToJobObject=api(lambda *_:(calls.append('assign_process') or assignment))
            self.QueryInformationJobObject=api(lambda *_:True)
            self.ResumeThread=api(lambda *_:(calls.append('resume_thread') or resume))
            self.TerminateJobObject=api(lambda *_:(calls.append('terminate_job') or True))
            self.CloseHandle=api(lambda handle:(calls.append(('close_handle',int(handle))) or True))

    class ThreadHandle(int):
        def Close(self):calls.append('close_thread')

    class Process:
        _handle=17
        _thread_handle=ThreadHandle(19)

    monkeypatch.setattr(windows.ctypes,'WinDLL',lambda *a,**k:Kernel(),raising=False)
    return windows,Process


def test_double_start_is_rejected_before_spawn_and_creates_owned_session():
    owner,process,group,calls=controller()
    try:
        assert owner.start(['fixture-child']) is True
        assert owner.start(['fixture-child']) is False
        eventually(lambda:len(calls)==1)
        import os,subprocess
        if os.name=='nt':
            from utils.launcher_windows import CREATE_SUSPENDED
            assert calls[0][1]['creationflags']==subprocess.CREATE_NEW_PROCESS_GROUP|CREATE_SUSPENDED
        else:assert calls[0][1].get('start_new_session') is True
        assert calls[0][1]['env']['INEBOTTEN_LAUNCHER_INSTANCE']
    finally:finish(owner)


def test_process_alive_is_connecting_until_own_instance_and_required_health_are_ready():
    health={'status':'healthy','readiness':'ready','launcher_instance':'another-owner'}
    owner,process,group,calls=controller(probe=lambda nonce:dict(health))
    try:
        owner.start(['fixture-child']);eventually(lambda:owner.state=='connecting')
        health['launcher_instance']=calls[0][1]['env']['INEBOTTEN_LAUNCHER_INSTANCE']
        eventually(lambda:owner.state=='ready')
        health['readiness']='degraded';health['status']='degraded'
        eventually(lambda:owner.state=='degraded')
    finally:finish(owner)


def test_stop_returns_without_blocking_ui_and_escalates_only_owned_group():
    owner,process,group,calls=controller(ignore_terminate=True)
    owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
    start=time.monotonic();owner.stop(start+.05)
    assert time.monotonic()-start<.02
    eventually(lambda:not owner.active)
    assert group.actions==['terminate','kill','close']
    assert owner.state=='exited'


def test_close_during_blocked_start_still_stops_the_late_owned_child():
    gate=threading.Event();process=Process()
    owner,process,group,calls=controller(process,popen=lambda *a,**k:(gate.wait(1),process)[1])
    owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
    owner.stop(time.monotonic()+.05)
    assert owner.active
    gate.set();eventually(lambda:not owner.active)
    assert 'terminate' in group.actions


def test_early_parent_exit_does_not_leave_owned_descendants_running():
    owner,process,group,calls=controller(ignore_terminate=True)
    owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
    process.returncode=1
    eventually(lambda:'terminate' in group.actions)
    owner.stop(time.monotonic()+.05);eventually(lambda:not owner.active)
    assert 'kill' in group.actions


def test_unconfirmed_shutdown_retains_ownership_and_rejects_restart():
    owner,process,group,calls=controller(ignore_terminate=True,ignore_kill=True)
    owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
    owner.stop(time.monotonic()+.03)
    eventually(lambda:'kill' in group.actions)
    assert owner.active
    assert owner.state!='exited'
    assert not owner.start(['second-child'])
    group.alive=False;process.returncode=-9
    eventually(lambda:not owner.active)


def test_log_saturation_is_bounded_and_state_transitions_survive():
    owner,process,group,calls=controller(Process('x'*9000+'\n'+''.join('line\n' for _ in range(10000))))
    try:
        owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
        time.sleep(.08)
        events=owner.drain(1000)
        assert len(events)<=17  # at most one latest state plus 16 bounded log events
        assert all(len(event.message)<=2048 for event in events)
    finally:finish(owner)


def test_only_main_thread_can_drain_and_widget_adapters_never_receive_worker_calls():
    owner,process,group,calls=controller(Process('fixture log\n'))
    errors=[]
    def wrong_thread():
        try:owner.drain()
        except RuntimeError as error:errors.append(str(error))
    thread=threading.Thread(target=wrong_thread);thread.start();thread.join()
    assert errors==['main_thread_required']
    try:
        owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
        assert owner.drain()  # Widget application is deliberately outside workers.
    finally:finish(owner)


def test_blocked_output_reader_does_not_mark_shutdown_complete_before_reader_finishes():
    release=threading.Event()
    class BlockedOutput:
        def readline(self,*args):release.wait(2);return ''
    process=Process();process.stdout=BlockedOutput()
    owner,process,group,calls=controller(process)
    try:
        owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
        owner.stop(time.monotonic()+.02)
        eventually(lambda:'terminate' in group.actions)
        time.sleep(.65)
        assert owner.active
        assert owner.state!='exited'
        release.set();eventually(lambda:not owner.active)
    finally:
        release.set()
        finish(owner)


def test_windows_launcher_creates_redirector_suspended_before_owned_group(monkeypatch):
    import utils.launcher_runtime as runtime
    monkeypatch.setattr(runtime,'_is_windows',lambda:True,raising=False)
    monkeypatch.setattr(runtime.subprocess,'CREATE_NEW_PROCESS_GROUP',0x200,raising=False)
    owner,process,group,calls=controller()
    try:
        owner.start(['fixture-child'])
        eventually(lambda:len(calls)==1)
        assert calls[0][1]['creationflags'] & 0x4
    finally:finish(owner)


@pytest.mark.parametrize('existing_handles',[None,[99]])
def test_windows_popen_limits_inherited_handles_to_launcher_pipes(monkeypatch,existing_handles):
    import subprocess
    import utils.launcher_windows as windows

    class StartupInfo:
        def __init__(self,lpAttributeList=None):
            self.dwFlags=0
            self.lpAttributeList=lpAttributeList
        def copy(self):return StartupInfo(self.lpAttributeList)

    class Handle(int):
        def Close(self):pass

    class Native:
        STARTF_USESTDHANDLES=0x100
        def CreateProcess(self,*args):
            self.arguments=args
            return 101,202,303,404

    class Child:
        _filter_handle_list=staticmethod(lambda handles:list(dict.fromkeys(handles)))
        _close_pipe_fds=lambda self,*handles:None

    native=Native();child=Child()
    startupinfo=StartupInfo({'handle_list':existing_handles}) if existing_handles is not None else None
    with monkeypatch.context() as patch:
        patch.setattr(windows.os,'name','nt')
        patch.setattr(subprocess,'STARTUPINFO',StartupInfo,raising=False)
        patch.setattr(subprocess,'Handle',Handle,raising=False)
        patch.setattr(subprocess,'_winapi',native,raising=False)
        windows.WindowsSuspendedPopen._execute_child(
            child,args=['python.exe','--run-bot'],executable=None,preexec_fn=None,
            close_fds=True,pass_fds=(),cwd=None,env={},startupinfo=startupinfo,
            creationflags=0x204,shell=False,p2cread=11,p2cwrite=21,
            c2pread=22,c2pwrite=12,errread=-1,errwrite=12,
            unused_restore_signals=None,unused_gid=None,unused_gids=None,
            unused_uid=None,unused_umask=None,unused_start_new_session=None,
            unused_process_group=None)

    inherit_handles=native.arguments[4]
    flags=native.arguments[5]
    startupinfo=native.arguments[8]
    assert inherit_handles==1
    assert flags & 0x4
    assert startupinfo.lpAttributeList['handle_list']==[11,12]
    assert (int(child._handle),int(child._thread_handle),child.pid)==(101,202,303)


@pytest.mark.parametrize(('terminate_fails','wait_result','unconfirmed'),[
    (True,258,True),(False,258,True),(True,0,False)])
def test_windows_startup_cleanup_wait_is_bounded_and_retains_unconfirmed_handles(
        monkeypatch,terminate_fails,wait_result,unconfirmed):
    import subprocess
    import utils.launcher_windows as windows
    closed=[]

    class StartupInfo:
        def __init__(self):
            self.dwFlags=0
            self.lpAttributeList=None

    class Native:
        STARTF_USESTDHANDLES=0x100
        WAIT_OBJECT_0=0
        WAIT_TIMEOUT=258
        def __init__(self):self.wait_timeouts=[]
        def CreateProcess(self,*args):return 101,202,303,404
        def TerminateProcess(self,*args):
            if terminate_fails:raise OSError('terminate_failed')
        def WaitForSingleObject(self,handle,timeout):
            self.wait_timeouts.append(timeout)
            return wait_result
        def CloseHandle(self,handle):closed.append(int(handle))

    native=Native()

    class Handle(int):
        def Close(self):closed.append(int(self))

    class Child:
        _filter_handle_list=staticmethod(lambda handles:list(dict.fromkeys(handles)))
        def _close_pipe_fds(self,*handles):raise OSError('parent_pipe_close_failed')

    child=Child()
    with monkeypatch.context() as patch:
        patch.setattr(windows.os,'name','nt')
        patch.setattr(subprocess,'STARTUPINFO',StartupInfo,raising=False)
        patch.setattr(subprocess,'Handle',Handle,raising=False)
        patch.setattr(subprocess,'_winapi',native,raising=False)
        if unconfirmed:
            with pytest.raises(RuntimeError,match='windows_start_cleanup_unconfirmed') as caught:
                windows.WindowsSuspendedPopen._execute_child(
                    child,args=['python.exe','--run-bot'],executable=None,preexec_fn=None,
                    close_fds=True,pass_fds=(),cwd=None,env={},startupinfo=None,
                    creationflags=0x204,shell=False,p2cread=11,p2cwrite=21,
                    c2pread=22,c2pwrite=12,errread=-1,errwrite=12,
                    unused_restore_signals=None,unused_gid=None,unused_gids=None,
                    unused_uid=None,unused_umask=None,unused_start_new_session=None,
                    unused_process_group=None)
        else:
            with pytest.raises(OSError,match='parent_pipe_close_failed'):
                windows.WindowsSuspendedPopen._execute_child(
                    child,args=['python.exe','--run-bot'],executable=None,preexec_fn=None,
                    close_fds=True,pass_fds=(),cwd=None,env={},startupinfo=None,
                    creationflags=0x204,shell=False,p2cread=11,p2cwrite=21,
                    c2pread=22,c2pwrite=12,errread=-1,errwrite=12,
                    unused_restore_signals=None,unused_gid=None,unused_gids=None,
                    unused_uid=None,unused_umask=None,unused_start_new_session=None,
                    unused_process_group=None)

    assert native.wait_timeouts==[1000]
    if unconfirmed:
        assert caught.value.process is child
        assert caught.value.failure.args==('parent_pipe_close_failed',)
        assert child._launcher_cleanup_unconfirmed is True
        assert (int(child._handle),int(child._thread_handle))==(101,202)
        assert len(caught.value.cleanup_failures)==(2 if terminate_fails else 1)
        assert closed==[]
    else:
        assert child._handle is child._thread_handle is None
        assert child._child_created is False
        assert closed==[202,101]


def test_windows_owned_job_assigns_before_resuming_primary_thread(monkeypatch):
    calls=[]
    windows,Process=fake_windows_job_api(monkeypatch,calls)
    job=windows.WindowsOwnedJob(Process())
    assert calls==['create_job','set_limits','assign_process','resume_thread','close_thread']
    job.close()


def test_windows_assignment_failure_closes_suspended_thread_without_resuming(monkeypatch):
    calls=[]
    windows,Process=fake_windows_job_api(monkeypatch,calls,assignment=False)
    with pytest.raises(OSError,match='job_assignment_failed'):
        windows.WindowsOwnedJob(Process())
    assert calls==['create_job','set_limits','assign_process','close_thread',('close_handle',101)]


def test_windows_resume_failure_terminates_assigned_job_before_returning(monkeypatch):
    calls=[]
    windows,Process=fake_windows_job_api(monkeypatch,calls,resume=0xFFFFFFFF)
    with pytest.raises(OSError,match='process_resume_failed'):
        windows.WindowsOwnedJob(Process())
    assert calls==['create_job','set_limits','assign_process','resume_thread','terminate_job',
                   'close_thread',('close_handle',101)]


def test_group_setup_failure_stops_only_gated_owned_child_and_releases_after_exit():
    class Input(io.StringIO):
        def close(self):self.written=self.getvalue();super().close()
    class OwnedProcess(Process):
        def __init__(self):super().__init__();self.stdin=Input();self.kills=0
        def kill(self):self.kills+=1;self.returncode=-9
    process=OwnedProcess()
    def fail_group(p):raise OSError('fixture job assignment failed')
    owner=LauncherController(popen_factory=lambda *a,**k:process,group_factory=fail_group,poll_interval=.01)
    owner.start(['fixture-child','--run-bot'])
    eventually(lambda:process.kills==1)
    eventually(lambda:not owner.active)
    assert process.stdin.closed and 'start' not in process.stdin.written


def test_unconfirmed_windows_startup_cleanup_retains_launcher_ownership():
    process=Process();process.kills=0
    def kill():process.kills+=1
    process.kill=kill
    class OwnedHandle:
        def __init__(self,name):self.name=name;self.closed=False
        def Close(self):self.closed=True
    process._handle=OwnedHandle('process')
    process._thread_handle=OwnedHandle('thread')
    process._launcher_setup_failed=True
    failure=RuntimeError('windows_start_cleanup_unconfirmed')
    failure.process=process
    owner=LauncherController(popen_factory=lambda *a,**k:(_ for _ in ()).throw(failure),
                             poll_interval=.01)
    owner.start(['fixture-child','--run-bot'])
    try:
        eventually(lambda:process.kills==1)
        assert owner.active
        assert owner.state=='degraded'
        assert owner._process is process
        assert not process._handle.closed and not process._thread_handle.closed
    finally:
        process.returncode=-9
        eventually(lambda:not owner.active)
    assert process._handle is None and process._thread_handle is None


def test_secret_and_private_debug_log_lines_are_redacted_before_ui_handoff():
    owner,process,group,calls=controller(Process('OPENROUTER_API_KEY=fixture-secret\nmessage content: fixture-private\n'))
    try:
        owner.start(['fixture-child']);eventually(lambda:len(calls)==1)
        time.sleep(.03)
        events=owner.drain()
        assert any('[REDACTED]' in event.message for event in events)
        assert all('fixture-secret' not in event.message and 'fixture-private' not in event.message for event in events)
    finally:finish(owner)


def test_posix_group_does_not_signal_a_group_number_after_leader_was_reaped(monkeypatch):
    import os
    if os.name=='nt':pytest.skip('POSIX signal ownership')
    from utils.launcher_runtime import PosixOwnedGroup
    process=Process();process.returncode=0
    calls=[]
    monkeypatch.setattr(os,'killpg',lambda pid,sig:calls.append((pid,sig)))
    group=PosixOwnedGroup(process)
    group.terminate();group.kill();group.close()
    assert calls==[]


def test_posix_exit_observation_does_not_reap_leader_until_signals_are_sealed():
    import os,subprocess,sys
    if os.name=='nt':pytest.skip('POSIX event observer')
    from utils.launcher_runtime import PosixOwnedGroup
    process=subprocess.Popen([sys.executable,'-I','-c','import sys;sys.stdin.readline();sys.exit(7)'],
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,start_new_session=True,env={'PATH':os.defpath})
    group=None
    try:
        group=PosixOwnedGroup(process)
        process.stdin.write('start\n');process.stdin.flush()
        eventually(lambda:group.peek_exit() is not None)
        assert process.returncode is None  # retain the owned leader identity during group signals
        group.kill()
        eventually(lambda:group.peek_exit()==7)
        eventually(lambda:not group.is_alive())
    finally:
        if group is not None:group.kill();group.close()
        if process.poll() is None:process.kill();process.wait(timeout=2)
        process.stdin.close();process.stdout.close()
