"""Unnamed Windows Job owned by exactly the newly spawned launcher child.

Assign before permitting the cooperative child to initialize or spawn workers.
Native Windows integration is a release gate; no process-name or PID tree search.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


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
        signatures={
            'CreateJobObjectW':([ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
            'SetInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
            'AssignProcessToJobObject':([wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
            'QueryInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p],wintypes.BOOL),
            'TerminateJobObject':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
            'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
        }
        for name,(arguments,result) in signatures.items():
            function=getattr(self.kernel,name);function.argtypes=arguments;function.restype=result
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:raise OSError('job_creation_failed')
        limits=_ExtendedLimits();limits.BasicLimitInformation.LimitFlags=0x2000  # KILL_ON_JOB_CLOSE
        try:
            if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise OSError('job_limits_failed')
            # CPython 3.12 Popen owns this process HANDLE; it cannot refer to a recycled PID.
            if not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
                raise OSError('job_assignment_failed')
        except BaseException:
            self.kernel.CloseHandle(self.handle);self.handle=None
            raise

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
