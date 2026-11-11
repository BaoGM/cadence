# SPDX-License-Identifier: GPL-3.0-only
import ctypes
import os
from pathlib import Path
import PySide6
from PySide6.QtCore import qVersion


def load_library():
    path=Path(__file__).resolve().parent/'native'/'bin'/'cadence_native.dll'
    qt_directory=Path(PySide6.__file__).resolve().parent
    with os.add_dll_directory(str(qt_directory)):
        library=ctypes.CDLL(str(path))
    library.cadence_native_abi.argtypes=[]
    library.cadence_native_abi.restype=ctypes.c_int
    library.cadence_native_qt.argtypes=[]
    library.cadence_native_qt.restype=ctypes.c_char_p
    if library.cadence_native_abi()!=1 or library.cadence_native_qt().decode('ascii')!=qVersion():
        raise RuntimeError('Native graphics module does not match the Qt runtime')
    library.cadence_prepare_graphics.argtypes=[ctypes.c_void_p]
    library.cadence_prepare_graphics.restype=ctypes.c_int
    library.cadence_graphics_timings.argtypes=[ctypes.POINTER(ctypes.c_double)]
    library.cadence_graphics_timings.restype=None
    return library
