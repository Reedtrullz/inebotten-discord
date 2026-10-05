"""Unnamed Windows Job owned by exactly the newly spawned launcher child.

Assign before permitting the cooperative child to initialize or spawn workers.
Native Windows integration is a release gate; no process-name or PID tree search.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes


CREATE_SUSPENDED = 0x00000004
STARTUP_CLEANUP_TIMEOUT_MS = 1000


class WindowsStartCleanupUnconfirmed(RuntimeError):
    """A failed suspended start whose exact process handles remain owned."""

    def __init__(self, process, failure, cleanup_failures):
        super().__init__('windows_start_cleanup_unconfirmed')
        self.process = process
        self.failure = failure
        self.cleanup_failures = tuple(cleanup_failures)


class WindowsSuspendedPopen(subprocess.Popen):
    """Create the launcher child suspended and retain CreateProcess handles."""

    def _execute_child(self, args, executable, preexec_fn, close_fds,
                       pass_fds, cwd, env, startupinfo, creationflags, shell,
                       p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite,
                       unused_restore_signals, unused_gid, unused_gids,
                       unused_uid, unused_umask, unused_start_new_session,
                       unused_process_group):
        if os.name != 'nt' or creationflags & CREATE_SUSPENDED == 0:
            raise OSError('windows_suspended_creation_required')
        if preexec_fn is not None or pass_fds or shell:
            raise ValueError('unsupported_suspended_popen_options')
        if isinstance(args, str):
            command_line = args
        else:
            command_line = subprocess.list2cmdline(args)
        if executable is not None:
            executable = os.fsdecode(executable)
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        else:
            startupinfo = startupinfo.copy()
        if -1 in (p2cread, c2pwrite, errwrite):
            raise OSError('launcher_pipe_handles_required')
        startupinfo.dwFlags |= subprocess._winapi.STARTF_USESTDHANDLES
        startupinfo.hStdInput = p2cread
        startupinfo.hStdOutput = c2pwrite
        startupinfo.hStdError = errwrite
        attributes = startupinfo.lpAttributeList
        if attributes is None:
            attributes = startupinfo.lpAttributeList = {}
        # Only the launcher's standard streams belong in this child. Do not
        # propagate additional caller handles to an unrelated process.
        handles = [int(p2cread), int(c2pwrite), int(errwrite)]
        handles[:] = self._filter_handle_list(handles)
        if not handles:
            raise OSError('launcher_pipe_handles_required')
        attributes['handle_list'] = handles
        cwd = os.fsdecode(cwd) if cwd is not None else None
        sys.audit('subprocess.Popen', executable, command_line, cwd, env)

        process_handle = thread_handle = None
        created = False
        try:
            try:
                process_handle, thread_handle, pid, _ = subprocess._winapi.CreateProcess(
                    executable, command_line, None, None, 1, creationflags, env,
                    cwd, startupinfo)
                created = True
                self._handle = subprocess.Handle(process_handle)
                self._thread_handle = subprocess.Handle(thread_handle)
                self.pid = pid
                self._child_created = True
                process_handle = thread_handle = None
            finally:
                self._close_pipe_fds(p2cread, p2cwrite, c2pread, c2pwrite,
                                     errread, errwrite)
        except BaseException as failure:
            if not created:
                raise
            # CreateProcess succeeded but setup did not. Bound cleanup of this
            # exact process; never discard its handles without exit evidence.
            native = subprocess._winapi
            owned_process = getattr(self, '_handle', None)
            terminate_failure = None
            try:
                native.TerminateProcess(owned_process, 1)
            except OSError as error:
                terminate_failure = error
            try:
                wait_result = native.WaitForSingleObject(
                    owned_process, STARTUP_CLEANUP_TIMEOUT_MS)
            except OSError as error:
                cleanup_failures = [('wait', error)]
            else:
                if wait_result != getattr(native, 'WAIT_OBJECT_0', 0):
                    cleanup_failures = [('wait_result', wait_result)]
                else:
                    cleanup_failures = []
            if cleanup_failures and terminate_failure is not None:
                cleanup_failures.insert(0, ('terminate', terminate_failure))
            self._launcher_setup_failed = True
            if cleanup_failures:
                self._launcher_cleanup_unconfirmed = True
                raise WindowsStartCleanupUnconfirmed(
                    self, failure, cleanup_failures) from failure
            # Exit is confirmed. Close the primary thread first, retaining the
            # process handle until its final close also succeeds.
            try:
                self._thread_handle.Close()
                self._thread_handle = None
                self._handle.Close()
                self._handle = None
                self._child_created = False
            except OSError as error:
                self._launcher_cleanup_unconfirmed = True
                raise WindowsStartCleanupUnconfirmed(
                    self, failure, [('close_handle', error)]) from failure
            raise


class _IoCounters(ctypes.Structure):
    _fields_=[(name,ctypes.c_ulonglong) for name in (
        'ReadOperationCount','WriteOperationCount','OtherOperationCount',
        'ReadTransferCount','WriteTransferCount','OtherTransferCount')]


class _BasicLimits(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
              ('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),
              ('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),
              ('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_=[('BasicLimitInformation',_BasicLimits),('IoInfo',_IoCounters),
              ('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),
              ('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_=[('TotalUserTime',ctypes.c_longlong),('TotalKernelTime',ctypes.c_longlong),
              ('ThisPeriodTotalUserTime',ctypes.c_longlong),('ThisPeriodTotalKernelTime',ctypes.c_longlong),
              ('TotalPageFaultCount',wintypes.DWORD),('TotalProcesses',wintypes.DWORD),
              ('ActiveProcesses',wintypes.DWORD),('TotalTerminatedProcesses',wintypes.DWORD)]


class WindowsOwnedJob:
    def __init__(self, process):
        self.process=process
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self._thread=getattr(process,'_thread_handle',None)
        if self._thread is None:raise OSError('suspended_primary_thread_unavailable')
        signatures={
            'CreateJobObjectW':([ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
            'SetInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
            'AssignProcessToJobObject':([wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
            'QueryInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p],wintypes.BOOL),
            'TerminateJobObject':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
            'ResumeThread':([wintypes.HANDLE],wintypes.DWORD),
            'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
        }
        for name,(arguments,result) in signatures.items():
            function=getattr(self.kernel,name);function.argtypes=arguments;function.restype=result
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:
            self._close_primary_thread()
            raise OSError('job_creation_failed')
        limits=_ExtendedLimits();limits.BasicLimitInformation.LimitFlags=0x2000  # KILL_ON_JOB_CLOSE
        assigned=False
        try:
            if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise OSError('job_limits_failed')
            if not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
                raise OSError('job_assignment_failed')
            assigned=True
            # The venv redirector can start the base interpreter during its own
            # startup. Resume only after this process handle belongs to the job.
            suspend_count=self.kernel.ResumeThread(int(self._thread))
            if suspend_count==0xFFFFFFFF:
                raise OSError('process_resume_failed')
            if suspend_count!=1:
                raise OSError('unexpected_primary_thread_suspend_count')
            self._close_primary_thread()
        except BaseException:
            if assigned:self.kernel.TerminateJobObject(self.handle,1)
            try:self._close_primary_thread()
            finally:
                if self.handle is not None:
                    self.kernel.CloseHandle(self.handle);self.handle=None
            raise

    def _close_primary_thread(self):
        if self._thread is None:return
        close=getattr(self._thread,'Close',None)
        if close is not None:close()
        elif not self.kernel.CloseHandle(int(self._thread)):
            raise OSError('primary_thread_close_failed')
        self._thread=None
        self.process._thread_handle=None

    def is_alive(self):
        if self.handle is None:return False
        accounting=_Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle,1,ctypes.byref(accounting),ctypes.sizeof(accounting),None):
            raise OSError('job_accounting_failed')
        return accounting.ActiveProcesses>0

    def terminate(self):
        # The trusted child's stdin stop request is sent by the controller first.
        # A windowed executable has no guaranteed console. Job termination is
        # reserved for the deadline after the cooperative request.
        pass

    def kill(self):
        if self.handle is not None and not self.kernel.TerminateJobObject(self.handle,1):
            raise OSError('job_termination_failed')

    def close(self):
        if self.handle is not None:
            if not self.kernel.CloseHandle(self.handle):raise OSError('job_close_failed')
            self.handle=None
