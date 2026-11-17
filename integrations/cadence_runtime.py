# SPDX-License-Identifier: GPL-3.0-only
import io
import hashlib
import json
import math
import os
import sys
import re
import time
from timeit import default_timer
from types import ModuleType

try:
    text_type = unicode
    string_types = (basestring,)
    integer_types = (int, long)
except NameError:
    text_type = str
    string_types = (str,)
    integer_types = (int,)

monotonic = getattr(time, 'monotonic', default_timer)


class TransferCancelled(Exception):
    cancelled = True


def fs_path(value):
    if hasattr(value, '__fspath__'):
        value = value.__fspath__()
    if isinstance(value, bytes) and not isinstance(value, text_type):
        return value.decode(sys.getfilesystemencoding() or 'utf-8')
    return value


def endpoint_path():
    value = os.environ.get('CADENCE_SYNC_ENDPOINT')
    if not value:
        root = fs_path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
        value = os.path.join(root, 'CadenceStudio', 'sync_endpoint.json')
    value = fs_path(value)
    if sys.version_info[0] >= 3:
        from pathlib import Path
        return Path(value)
    return value


def read_json(path):
    with io.open(fs_path(path), 'r', encoding='utf-8') as stream:
        return json.load(stream)


def finite(value):
    return not (math.isnan(value) or math.isinf(value))


def fullmatch(pattern, value):
    return isinstance(value, string_types) and re.match('(?:' + pattern + r')\Z', value)


def hash_file(path):
    digest = hashlib.sha256()
    with io.open(fs_path(path), 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def real_path(path):
    path = os.path.abspath(fs_path(path))
    if os.name != 'nt':
        if not os.path.exists(path):
            raise IOError('Path does not exist')
        return os.path.realpath(path)
    # Python 2 and older Python 3 do not resolve Windows junctions in os.path.realpath.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(path, 0, 7, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        count = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not count or count >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        result = buffer.value
        if result.startswith('\\\\?\\UNC\\'):
            return '\\\\' + result[8:]
        return result[4:] if result.startswith('\\\\?\\') else result
    finally:
        kernel.CloseHandle(handle)


def load_source(name, path):
    previous = sys.modules.get(name)
    try:
        module = ModuleType(name)
        module.__file__ = fs_path(path)
        module.__package__ = name.rpartition('.')[0]
        sys.modules[name] = module
        # Python 2 bytecode caches use second-resolution timestamps and can survive an update.
        with io.open(module.__file__, 'rb') as stream:
            code = compile(stream.read(), module.__file__, 'exec')
        exec(code, module.__dict__)
        return module
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise


def maya_timer():
    import maya.cmds as cmds
    if cmds.about(qtVersion=True).startswith('6.'):
        from PySide6.QtCore import QTimer
    else:
        from PySide2.QtCore import QTimer
    return QTimer()
