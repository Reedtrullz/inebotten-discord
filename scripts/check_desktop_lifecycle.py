"""Native Tk/owned-process rehearsal using only synthetic state and stdlib children.

Run with the desktop profile on each target OS. This is an engineering check,
not human keyboard/accessibility acceptance or a live bot/service check.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(*,ui_only=False):
    scratch=Path(os.getenv('TMPDIR') or tempfile.gettempdir()) if getattr(sys,'frozen',False) else ROOT/'.superpowers'/'desktop-checks'
    scratch.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-',dir=scratch) as directory:
        home=Path(directory)/'home';home.mkdir()
        for name in ('HOME','USERPROFILE','HERMES_HOME','APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME'):
            os.environ[name]=str(home)
        import tkinter as tk
        from utils.launcher_runtime import LauncherController
        from utils.launcher_ui import DesktopLauncher
        from utils.launcher_entrypoints import configure_source_tk

        configure_source_tk()
        root=tk.Tk()
        main_thread=threading.get_ident()
        calls=[]
        class TkCalls:
            def __getattr__(self,name):
                value=getattr(original,name)
                if not callable(value):return value
                def call(*args,**kwargs):
                    calls.append(threading.get_ident())
                    assert calls[-1]==main_thread,'widget_write_off_main_thread'
                    return value(*args,**kwargs)
                return call
        original=root.tk;root.tk=TkCalls()
        child_script='''import os,sys,subprocess,time,signal
assert sys.stdin.readline()=='start\\n'
child=subprocess.Popen([sys.executable,'-I','-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("descendant-ready",flush=True);time.sleep(30)'])
for i in range(800):print('fixture log '+str(i),flush=True)
while True:time.sleep(.01)
'''
        owner=LauncherController(poll_interval=.01,event_capacity=1024)
        app=DesktopLauncher(root,command=lambda:[],project_root=lambda:ROOT,controller=owner)
        unrelated=None if ui_only else subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],
                                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                   env={'PATH':os.defpath,**({'SYSTEMROOT':os.environ['SYSTEMROOT']} if os.name=='nt' else {})})
        def pump(predicate,seconds=4):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                root.update()
                if predicate():return
                time.sleep(.005)
            assert predicate(),'native_check_deadline'
        try:
            # Real native widget layout, focus, scaling and timer-driven events.
            root.tk.call('tk','scaling',1.5)
            root.geometry('950x760');root.update()
            assert root.winfo_width()>=900 and root.winfo_height()>=700
            app.start_button.focus_force();root.update()
            assert root.focus_get()==app.start_button
            root.tk.call('tk','scaling',2.0);root.update()
            if ui_only:
                assert not owner.active
                assert not (home/'discord').exists()
                receipt={'passed':True,'platform':sys.platform,'frozen':bool(getattr(sys,'frozen',False)),
                         'tk_version':str(root.tk.call('info','patchlevel')),'widget_calls':len(calls),
                         'all_widget_calls_on_main_thread':True,'layout_focus_scaling_checked':True,
                         'ui_started':True,'service_started':False,
                         'private_state_initialized':False,'human_acceptance':False,
                         'owned_process_check':'not_exercised_in_ui_smoke'}
                app.close()
                serialized=json.dumps(receipt,sort_keys=True)+'\n'
                target=os.environ.get('INEBOTTEN_UI_SMOKE_RECEIPT')
                if target:Path(target).write_text(serialized,encoding='utf-8')
                else:print(serialized,end='')
                return 0
            env={'PATH':os.defpath,'HOME':str(home),'HERMES_HOME':str(home)}
            if os.name=='nt':env['SYSTEMROOT']=os.environ['SYSTEMROOT']
            assert owner.start([sys.executable,'-I','-u','-c',child_script,'--run-bot'],cwd=home,env=env)
            assert not owner.start([sys.executable,'--run-bot'])
            pump(lambda:'fixture log 799' in app.log_text.get('1.0','end'))
            assert owner.state=='connecting'  # no readiness provider for this fixture
            assert int(app.log_text.index('end-1c').split('.')[0])<=500
            assert unrelated.poll() is None
            started=time.monotonic();app.close()
            assert time.monotonic()-started<.1 and owner.active
            # Short fixture deadline, independent of the production 12-second grace.
            owner.stop(time.monotonic()+.2)
            # Avoid calling update after the timer destroys Tk.
            while owner.active:
                assert time.monotonic()-started<5,'owned_group_exit_unconfirmed'
                root.update();time.sleep(.005)
            assert unrelated.poll() is None,'unrelated_process_was_terminated'
            assert all(value==main_thread for value in calls)
            assert not (home/'discord').exists(),'private_app_state_initialized'
            print(json.dumps({'passed':True,'platform':sys.platform,'tk_version':str(root.tk.call('info','patchlevel')),
                'widget_calls':len(calls),'all_widget_calls_on_main_thread':True,'owned_group_exit_confirmed':True,
                'unrelated_process_preserved':True,'private_state_initialized':False,
                'human_acceptance':False},sort_keys=True))
        finally:
            owner.stop(time.monotonic())
            deadline=time.monotonic()+3
            while owner.active and time.monotonic()<deadline:time.sleep(.01)
            assert not owner.active,'fixture_owned_group_cleanup_unconfirmed'
            if unrelated is not None:
                unrelated.kill();unrelated.wait(timeout=3)
            try:root.destroy()
            except tk.TclError:pass
    return 0


if __name__=='__main__':raise SystemExit(main())
