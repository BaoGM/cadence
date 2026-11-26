# SPDX-License-Identifier: GPL-3.0-only
import _winapi
import ctypes
from ctypes import wintypes as wt
from contextlib import ExitStack
from pathlib import Path
import subprocess

from maintenance_identity import install_paths
from update_store import base_executable


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ('size', wt.DWORD), ('reserved', wt.LPWSTR), ('desktop', wt.LPWSTR), ('title', wt.LPWSTR),
        ('x', wt.DWORD), ('y', wt.DWORD), ('width', wt.DWORD), ('height', wt.DWORD),
        ('columns', wt.DWORD), ('rows', wt.DWORD), ('fill', wt.DWORD), ('flags', wt.DWORD),
        ('show', wt.WORD), ('reserved_size', wt.WORD), ('reserved_data', wt.LPVOID),
        ('stdin', wt.HANDLE), ('stdout', wt.HANDLE), ('stderr', wt.HANDLE),
    ]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('process', wt.HANDLE), ('thread', wt.HANDLE), ('pid', wt.DWORD), ('tid', wt.DWORD)]


class ExtendedStartup(ctypes.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', wt.LPVOID)]


class DesktopProcess:
    def __init__(self, handle, thread):
        self.handle = subprocess.Handle(handle)
        self.thread = subprocess.Handle(thread)

    def resume(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.ResumeThread.argtypes = [wt.HANDLE]
        kernel.ResumeThread.restype = wt.DWORD
        if kernel.ResumeThread(self.thread) == 0xffffffff:
            raise ctypes.WinError(ctypes.get_last_error())
        self.thread.Close()

    def wait(self, timeout=None):
        milliseconds = _winapi.INFINITE if timeout is None else round(timeout * 1000)
        if _winapi.WaitForSingleObject(self.handle, milliseconds) == _winapi.WAIT_TIMEOUT:
            raise TimeoutError('Cadence is still running')
        return _winapi.GetExitCodeProcess(self.handle)

    def terminate(self):
        _winapi.TerminateProcess(self.handle, 1)

    def close(self):
        self.thread.Close()
        self.handle.Close()


def launch_as_desktop_user(executable, args=(), *, suspended=False):
    executable = Path(executable)
    if executable not in (base_executable(), install_paths()[1]) or not executable.is_absolute():
        raise ValueError('Unexpected Cadence update executable')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    profiles = ctypes.WinDLL('userenv', use_last_error=True)
    user.GetShellWindow.restype = wt.HWND
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    security.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    security.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    security.GetSidSubAuthority.argtypes = [wt.LPVOID, wt.DWORD]
    security.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
    security.EqualSid.argtypes = [wt.LPVOID, wt.LPVOID]
    profiles.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(wt.LPVOID), wt.HANDLE, wt.BOOL]
    profiles.DestroyEnvironmentBlock.argtypes = [wt.LPVOID]
    kernel.InitializeProcThreadAttributeList.argtypes = [wt.LPVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.UpdateProcThreadAttribute.argtypes = [wt.LPVOID, wt.DWORD, ctypes.c_size_t, wt.LPVOID, ctypes.c_size_t,
                                                 wt.LPVOID, wt.LPVOID]
    kernel.DeleteProcThreadAttributeList.argtypes = [wt.LPVOID]
    kernel.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, wt.LPVOID, wt.LPVOID, wt.BOOL, wt.DWORD,
                                      wt.LPVOID, wt.LPCWSTR, ctypes.POINTER(ExtendedStartup), ctypes.POINTER(ProcessInfo)]
    pid = wt.DWORD()
    window = user.GetShellWindow()
    if not window or not user.GetWindowThreadProcessId(window, ctypes.byref(pid)):
        raise OSError('Interactive Windows desktop unavailable')

    with ExitStack() as handles:
        shell = kernel.OpenProcess(0x1000 | 0x0080, False, pid)
        if not shell:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.callback(_winapi.CloseHandle, shell)
        def process_token(process, access):
            token = wt.HANDLE()
            if not security.OpenProcessToken(process, access, ctypes.byref(token)):
                raise ctypes.WinError(ctypes.get_last_error())
            handles.callback(_winapi.CloseHandle, token.value)
            return token

        def token_info(token, kind, value):
            size = wt.DWORD()
            if not security.GetTokenInformation(token, kind, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            return value

        def standard_identity(token):
            label = token_info(token, 25, ctypes.create_string_buffer(128))
            integrity = security.GetSidSubAuthority(ctypes.c_void_p.from_buffer(label), 0)
            if (token_info(token, 20, wt.DWORD()).value or token_info(token, 26, wt.DWORD()).value or
                    not integrity or integrity.contents.value != 0x2000):
                raise PermissionError('A standard Windows desktop session is required')
            return (token_info(token, 1, ctypes.create_string_buffer(128)),
                    token_info(token, 12, wt.DWORD()).value)

        token = process_token(shell, 0x0008 | 0x0002)
        desktop_user, desktop_session = standard_identity(token)
        environment = wt.LPVOID()
        if not profiles.CreateEnvironmentBlock(ctypes.byref(environment), token, False):
            raise ctypes.WinError(ctypes.get_last_error())
        handles.callback(profiles.DestroyEnvironmentBlock, environment)

        # Windows starts the child as the interactive desktop user, even for over-the-shoulder UAC.
        size = ctypes.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        if not size.value: raise ctypes.WinError(ctypes.get_last_error())
        attributes = ctypes.create_string_buffer(size.value)
        if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        handles.callback(kernel.DeleteProcThreadAttributeList, attributes)
        desktop = wt.HANDLE(shell)
        if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020000, ctypes.byref(desktop),
                                                ctypes.sizeof(desktop), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = ExtendedStartup(StartupInfo(size=ctypes.sizeof(ExtendedStartup)), ctypes.cast(attributes, wt.LPVOID))
        info = ProcessInfo()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable), *args]))
        extended_startup_info = 0x00080000
        unicode_environment = 0x00000400
        create_suspended = 0x00000004
        flags = extended_startup_info | unicode_environment | create_suspended
        if not kernel.CreateProcessW(str(executable), command, None, None, False, flags, environment,
                                     str(executable.parent), ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        child = DesktopProcess(info.process, info.thread)
        try:
            child_user, session = standard_identity(process_token(info.process, 0x0008))
            if session != desktop_session or not security.EqualSid(ctypes.c_void_p.from_buffer(child_user),
                                                                   ctypes.c_void_p.from_buffer(desktop_user)):
                raise PermissionError('Cadence restart did not inherit the interactive desktop identity')
            if not suspended: child.resume()
        except BaseException:
            try: child.terminate()
            finally: child.close()
            raise
        return child
