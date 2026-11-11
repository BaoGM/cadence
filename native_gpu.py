# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from comparison_gpu import FramePacket,LAYOUTS
from functools import lru_cache
import logging
import os
import weakref
import numpy as np
from PySide6.QtGui import QOpenGLContext
from shiboken6 import getCppPointer, isValid


@lru_cache(maxsize=1)
def _library():
    try:
        from native_graphics import load_library
        library = load_library()
        library.cadence_gpu_abi.argtypes = []
        library.cadence_gpu_abi.restype = ctypes.c_int
        if library.cadence_gpu_abi() != 3:
            raise RuntimeError('Incompatible GPU rendering ABI')
        pointer, integer = ctypes.c_void_p, ctypes.c_int
        library.cadence_gpu_create.argtypes = []
        library.cadence_gpu_create.restype = pointer
        library.cadence_gpu_destroy.argtypes = [pointer]
        library.cadence_gpu_destroy.restype = integer
        library.cadence_gpu_error.argtypes = []
        library.cadence_gpu_error.restype = ctypes.c_char_p
        library.cadence_gpu_paint.argtypes = [pointer, pointer, pointer, pointer, integer, integer,
            pointer, integer, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, pointer, integer, integer, integer, integer, integer, integer, integer, ctypes.c_float,ctypes.c_float,ctypes.c_float]
        library.cadence_gpu_paint.restype = integer
        library.cadence_gpu_timings.argtypes = [ctypes.POINTER(ctypes.c_double)]
        library.cadence_gpu_timings.restype = None
        library.cadence_gpu_info.argtypes = []
        library.cadence_gpu_info.restype = ctypes.c_char_p
        return library
    except (OSError, AttributeError, RuntimeError):
        logging.warning('GPU composition unavailable; keeping CPU composition', exc_info=True)
        return None


@lru_cache(maxsize=16)
def _table(ev, mode, opacity, gain, swapped):
    from native_render import _table as reference_table
    values = reference_table(ev, mode, opacity, gain, swapped)
    rgba = np.empty((*values.shape, 4), np.uint8)
    rgba[..., :3] = values[..., None]
    rgba[..., 3] = 255
    return rgba


def prepare(a, b=None, *, ev=0., mode='single', opacity=.5, gain=1., swapped=False,
            flip_h=False, flip_v=False, wipe=.5):
    if os.environ.get('CADENCE_GPU_COMPOSITION', '1') == '0':
        return None
    if mode not in ('single', 'overlay', 'difference', *LAYOUTS) or not all(np.isfinite(x) for x in (ev, opacity, gain)):
        return None
    arrays = (a,) if mode == 'single' else (a, b)
    if any(not isinstance(value, np.ndarray) or value.dtype != np.uint8 or value.ndim != 3
           or value.shape[2] != 3 or not value.size for value in arrays):
        return None
    fitted=len(arrays)==2 and a.shape!=b.shape and mode in ('overlay','difference')
    arrays = tuple(np.ascontiguousarray(value) for value in arrays)
    packet=FramePacket((arrays, _table(ev, 'single' if mode in LAYOUTS or fitted else mode, opacity, gain, swapped if mode not in LAYOUTS and not fitted else False), bool(flip_h), bool(flip_v), (mode == 'single' or mode in LAYOUTS or fitted) and not ev), mode, swapped, wipe)
    if fitted: packet.layout=5 if mode=='overlay' else 6
    packet.opacity=float(max(0,min(1,opacity))); packet.gain=float(max(0,gain))
    return packet


class GpuCompositor:
    def __init__(self, surface):
        self.surface = weakref.ref(surface)
        self.library = None
        self.context = None
        self.handle = None
        self.failed = False
        self.sources = None

    def timings(self):
        if self.library is None:
            return {}
        values = (ctypes.c_double * 7)()
        self.library.cadence_gpu_timings(values)
        return dict(zip(('preparation', 'initialization', 'upload_a', 'upload_b_lut', 'shader'), values))

    def close(self):
        if not self.handle:
            return
        surface = self.surface()
        if surface is not None and isValid(surface):
            surface.makeCurrent()
        result = self.library.cadence_gpu_destroy(self.handle)
        if result:
            logging.warning('GPU compositor cleanup deferred until its context is current')
            return
        self.handle = None
        self.sources = None
        if self.context is not None and isValid(self.context):
            try:
                self.context.aboutToBeDestroyed.disconnect(self.close)
            except RuntimeError:
                pass
        self.context = None

    def paint(self, painter, packet, rectangle):
        if packet is None or self.failed:
            return False
        context = QOpenGLContext.currentContext()
        if context is None:
            return False
        if self.context is not None and self.context != context:
            self.close()
            if self.handle:
                return False
        if self.library is None:
            self.library = _library()
            if self.library is None:
                self.failed = True
                return False
        if self.handle is None:
            self.handle = self.library.cadence_gpu_create()
            if not self.handle:
                self.failed = True
                return False
            self.context = context
            logging.info('GPU compositor: %s', self.library.cadence_gpu_info().decode('utf-8', 'replace'))
            context.aboutToBeDestroyed.connect(self.close)
        arrays, table, flip_h, flip_v, passthrough = packet
        a = arrays[0]
        b = arrays[1] if len(arrays) > 1 else None
        rect = (ctypes.c_double * 4)(rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height())
        code = self.library.cadence_gpu_paint(self.handle, getCppPointer(painter)[0], a.ctypes.data,
            b.ctypes.data if b is not None else None, a.shape[1], a.shape[0], table.ctypes.data,
            (256 if table is not None and table.ndim==3 else 1), id(a), id(b) if b is not None else 0, id(table),
            ctypes.addressof(rect), flip_h, flip_v, passthrough, b.shape[1] if b is not None else 0, b.shape[0] if b is not None else 0, packet.layout, packet.swapped, round(packet.wipe*a.shape[1])/a.shape[1],packet.opacity,packet.gain)
        if code:
            if code >= 3:
                detail = self.library.cadence_gpu_error()
                logging.warning('GPU composition failed; using CPU composition: %s', detail.decode('utf-8', 'replace') if detail else code)
                self.failed = True
            return False
        # The native upload revisions use identities, so keep owners alive until the next successful upload.
        self.sources = arrays, table
        return True
