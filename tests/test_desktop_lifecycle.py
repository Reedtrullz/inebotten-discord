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


def test_double_start_is_rejected_before_spawn_and_creates_owned_session():
    owner,process,group,calls=controller()
    try:
        assert owner.start(['fixture-child']) is True
        assert owner.start(['fixture-child']) is False
        eventually(lambda:len(calls)==1)
        import os,subprocess
        if os.name=='nt':assert calls[0][1]['creationflags']==subprocess.CREATE_NEW_PROCESS_GROUP
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
