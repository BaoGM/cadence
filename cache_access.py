# SPDX-License-Identifier: GPL-3.0-only
import os

from media import cache_root


def file_lock(file, exclusive=False, release=False):
    if os.name!='nt':
        import fcntl
        mode=fcntl.LOCK_UN if release else fcntl.LOCK_EX|fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH
        fcntl.flock(file,mode)
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class Overlapped(ctypes.Structure):
        _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                  ('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    handle=wintypes.HANDLE(msvcrt.get_osfhandle(file.fileno()))
    overlapped=Overlapped()
    if release:
        ok=kernel.UnlockFileEx(handle,0,1,0,ctypes.byref(overlapped))
    else:
        # Readers wait for an ongoing cleanup. Cleaners never wait for readers.
        flags=0x02|0x01 if exclusive else 0
        ok=kernel.LockFileEx(handle,flags,0,1,0,ctypes.byref(overlapped))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


class CacheAccess:
    def __init__(self):
        self.file=None
        try:
            self.file=(cache_root()/'.cadence-active').open('a+b')
            file_lock(self.file)
        except OSError:
            self.close()

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file=None

    def clean(self,protected=(),*,closing=False):
        from cache_tools import clear_cache
        if self.file is None:
            return 0,0,1,0
        try:
            file_lock(self.file,release=True)
            try:
                file_lock(self.file,exclusive=True)
            except OSError:
                return 0,0,1,0
            try:
                return clear_cache(protected) if protected else clear_cache()
            finally:
                file_lock(self.file,release=True)
        finally:
            if closing:
                self.close()
            else:
                try:
                    file_lock(self.file)
                except OSError:
                    self.close()
