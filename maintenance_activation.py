# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes as wt
from contextlib import ExitStack,contextmanager
from pathlib import Path
import sys

from update_machine import install_paths,service_pid
from updates import version_tuple


TRUSTED={'S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'}
WRITABLE=0x500d0156


def service_exists():
    try: service_pid(); return True
    except OSError as error:
        if error.winerror==1060: return False
        raise


def secure_permissions(handle):
    security=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[wt.HLOCAL]
    ptr=ctypes.c_void_p
    pptr=ctypes.POINTER(ptr)
    security.GetSecurityInfo.argtypes=[wt.HANDLE,ctypes.c_int,wt.DWORD,pptr,pptr,pptr,pptr,pptr]
    security.GetAce.argtypes=[ptr,wt.DWORD,pptr]
    security.ConvertSidToStringSidW.argtypes=[ptr,ctypes.POINTER(wt.LPWSTR)]
    def sid(address):
        text=wt.LPWSTR()
        if not security.ConvertSidToStringSidW(address,ctypes.byref(text)): raise ctypes.WinError(ctypes.get_last_error())
        try: return text.value
        finally: kernel.LocalFree(ctypes.cast(text,ptr))
    owner,acl,descriptor=ptr(),ptr(),ptr()
    code=security.GetSecurityInfo(handle,1,5,ctypes.byref(owner),None,ctypes.byref(acl),None,ctypes.byref(descriptor))
    if code: raise ctypes.WinError(code)
    try:
        if not acl or sid(owner) not in TRUSTED: return False
        count=ctypes.c_ushort.from_address(acl.value+4).value
        for i in range(count):
            ace=ptr()
            if not security.GetAce(acl,i,ctypes.byref(ace)): raise ctypes.WinError(ctypes.get_last_error())
            kind,flags=(ctypes.c_ubyte*2).from_address(ace.value)
            if flags&8 or kind==1: continue
            if kind!=0: return False
            rights=wt.DWORD.from_address(ace.value+4).value
            if rights&WRITABLE and sid(ace.value+8) not in TRUSTED|{'S-1-3-4'}: return False
        return True
    finally: kernel.LocalFree(descriptor)


@contextmanager
def protected_handle(path,directory):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,wt.LPVOID,wt.DWORD,wt.DWORD,wt.HANDLE]
    api.CreateFileW.restype=wt.HANDLE
    api.GetFileInformationByHandleEx.argtypes=[wt.HANDLE,ctypes.c_int,wt.LPVOID,wt.DWORD]
    api.CloseHandle.argtypes=[wt.HANDLE]
    # Keep the object open through ShellExecute. In particular, deny rename/delete while UAC is pending.
    handle=api.CreateFileW(str(path),0x20080,3 if directory else 1,None,3,0x02200000,None)
    if handle==wt.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    try:
        tags=(wt.DWORD*2)()
        if not api.GetFileInformationByHandleEx(handle,9,tags,ctypes.sizeof(tags)):
            raise ctypes.WinError(ctypes.get_last_error())
        if tags[0]&0x400 or bool(tags[0]&0x10)!=directory or not secure_permissions(handle):
            raise PermissionError('Untrusted maintenance setup path')
        yield
    finally: api.CloseHandle(handle)


@contextmanager
def setup_executable(base,version):
    version_tuple(version)
    app,_=install_paths()
    runtime=app.parent/('_internal-'+version)
    folder=runtime/'maintenance'
    setup=folder/'CadenceMaintenanceSetup.exe'
    if (not getattr(sys,'frozen',False) or Path(base)!=app or
            Path(sys.executable)!=app or Path(getattr(sys,'_MEIPASS',''))!=runtime or service_exists()):
        raise PermissionError('Maintenance activation is not available')
    with ExitStack() as opened:
        for directory in (app.parents[1],app.parent,runtime,folder):
            opened.enter_context(protected_handle(directory,True))
        opened.enter_context(protected_handle(app,False))
        opened.enter_context(protected_handle(setup,False))
        # The bootstrap is self-contained. A sidecar CLR configuration or DLL cannot accompany it.
        if set(folder.iterdir())!={setup}: raise PermissionError('Unexpected maintenance setup contents')
        yield setup


def available(base,version):
    try:
        with setup_executable(base,version): return True
    except (ValueError,OSError): return False


def activate(base,version,window_handle):
    with setup_executable(base,version) as executable:
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteW.argtypes=[wt.HWND,wt.LPCWSTR,wt.LPCWSTR,wt.LPCWSTR,wt.LPCWSTR,ctypes.c_int]
        shell.ShellExecuteW.restype=wt.HINSTANCE
        code=shell.ShellExecuteW(int(window_handle),'runas',str(executable),None,str(executable.parent),1) or 0
        if code>32: return True
        error=ctypes.get_last_error()
        if error==1223: return False
        raise ctypes.WinError(error or code)
