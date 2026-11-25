# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes as wt
from pathlib import Path
import sys
import uuid


SERVICE_SID='S-1-5-80-1353630254-3083678044-3037903310-3717458875-4092248727'
_identified=False


def install_paths():
    memory=ctypes.c_void_p()
    folder=ctypes.create_string_buffer(uuid.UUID('6D809377-6AF0-444b-8957-A3773F02200E').bytes_le)
    if ctypes.windll.shell32.SHGetKnownFolderPath(folder,0,None,ctypes.byref(memory)): raise OSError('Program Files unavailable')
    try: root=Path(ctypes.wstring_at(memory))
    finally: ctypes.windll.ole32.CoTaskMemFree(memory)
    return root/'Cadence 2.0'/'Cadence.exe',root/'Cadence Studio Maintenance'/'CadenceRestart.exe'


class Trustee(ctypes.Structure):
    _fields_=[('multiple',ctypes.c_void_p),('operation',ctypes.c_int),('form',ctypes.c_int),
              ('kind',ctypes.c_int),('sid',ctypes.c_void_p)]


class Access(ctypes.Structure):
    _fields_=[('rights',wt.DWORD),('mode',ctypes.c_int),('inherit',wt.DWORD),('trustee',Trustee)]


def grant_service_query():
    security=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    ptr=ctypes.c_void_p; pptr=ctypes.POINTER(ptr)
    kernel.GetCurrentProcess.restype=wt.HANDLE
    kernel.LocalFree.argtypes=[wt.HLOCAL]
    security.GetSecurityInfo.argtypes=[wt.HANDLE,ctypes.c_int,wt.DWORD,pptr,pptr,pptr,pptr,pptr]
    security.SetSecurityInfo.argtypes=[wt.HANDLE,ctypes.c_int,wt.DWORD,ptr,ptr,ptr,ptr]
    security.ConvertStringSidToSidW.argtypes=[wt.LPCWSTR,pptr]
    security.SetEntriesInAclW.argtypes=[wt.DWORD,ctypes.POINTER(Access),ptr,pptr]
    process=kernel.GetCurrentProcess()
    descriptor,current,sid,updated=ptr(),ptr(),ptr(),ptr()
    try:
        result=security.GetSecurityInfo(process,6,4,None,None,ctypes.byref(current),None,ctypes.byref(descriptor))
        if result: raise ctypes.WinError(result)
        if not current: return
        if not security.ConvertStringSidToSidW(SERVICE_SID,ctypes.byref(sid)): raise ctypes.WinError(ctypes.get_last_error())
        # GRANT_ACCESS preserves other entries. LocalService receives no process-memory or termination rights.
        entry=Access(0x1000,1,0,Trustee(None,0,0,0,sid))
        result=security.SetEntriesInAclW(1,ctypes.byref(entry),current,ctypes.byref(updated))
        if result: raise ctypes.WinError(result)
        result=security.SetSecurityInfo(process,6,4,None,None,updated,None)
        if result: raise ctypes.WinError(result)
    finally:
        for allocated in (updated,sid,descriptor):
            if allocated: kernel.LocalFree(allocated)


def identify_installed_process():
    global _identified
    if _identified: return True
    if not getattr(sys,'frozen',False) or Path(sys.executable)!=install_paths()[0]: return False
    grant_service_query()
    _identified=True
    return True
