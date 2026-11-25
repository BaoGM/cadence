# SPDX-License-Identifier: GPL-3.0-only
import os
import tempfile
from pathlib import Path


def open_shared(path):
    if os.name != 'nt':
        return open(path, 'rb')
    import _winapi
    import msvcrt
    # The CRT's ordinary open can prevent renaming or deleting a file on Windows.
    def open_descriptor(name, _flags):
        handle = _winapi.CreateFile(name, _winapi.GENERIC_READ, 0x7, 0, _winapi.OPEN_EXISTING, 0, 0)
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except OSError:
            _winapi.CloseHandle(handle)
            raise
    return open(path, 'rb', opener=open_descriptor)


def identity(info):
    return info['path'], info.get('size'), info.get('mtime_ns')


class SessionVideoSources:
    def __init__(self):
        self.files = {}

    def retain(self, media):
        wanted = {identity(info) for info in media if info.get('has_video', True) and info.get('path')}
        for key in self.files.keys() - wanted:
            self.files.pop(key).close()
        for key in wanted - self.files.keys():
            path, size, modified = key
            try:
                stream = open_shared(path)
            except OSError:
                continue
            try:
                stat = os.fstat(stream.fileno())
            except OSError:
                stream.close()
                continue
            if (stat.st_size, stat.st_mtime_ns) == (size, modified):
                self.files[key] = stream
            else:
                stream.close()

    def copy_missing(self, info, directory, cancel):
        from media import Cancelled
        stream = self.files.get(identity(info))
        if stream is None:
            return None
        def check_unchanged():
            stat = os.fstat(stream.fileno())
            if (stat.st_size, stat.st_mtime_ns) != (info['size'], info['mtime_ns']):
                raise ValueError(f"Le média source a changé depuis l’import : {Path(info['path']).name}. Réimportez-le dans un nouveau projet.")
        check_unchanged()
        stream.seek(0)
        with tempfile.NamedTemporaryFile(dir=directory, suffix=Path(info['path']).suffix, delete=False) as output:
            while chunk := stream.read(1024 * 1024):
                if cancel and cancel.is_set():
                    raise Cancelled()
                output.write(chunk)
        check_unchanged()
        return output.name

    def close(self):
        for stream in self.files.values():
            stream.close()
        self.files.clear()
