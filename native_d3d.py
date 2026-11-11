# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from comparison_gpu import FramePacket,LAYOUTS
from functools import lru_cache
import logging
import os
import numpy as np
from PySide6.QtGui import QImage


class DrawLayer(ctypes.Structure):
    _fields_=[('pixels',ctypes.c_void_p),('width',ctypes.c_int),('height',ctypes.c_int),('stride',ctypes.c_size_t),('revision',ctypes.c_uint64),('quad',ctypes.c_double*8),('opacity',ctypes.c_float),('clip',ctypes.c_float*4)]


@lru_cache(maxsize=1)
def _library():
    try:
        from native_graphics import load_library
        library = load_library()
        pointer, integer, revision = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64
        library.cadence_d3d_abi.argtypes = []
        library.cadence_d3d_abi.restype = integer
        if library.cadence_d3d_abi() != 3:
            raise RuntimeError('Incompatible Direct3D rendering ABI')
        library.cadence_d3d_create.argtypes = [pointer, integer]
        library.cadence_d3d_create.restype = pointer
        library.cadence_d3d_destroy.argtypes = [pointer]
        library.cadence_d3d_destroy.restype = None
        library.cadence_d3d_error.argtypes = []
        library.cadence_d3d_error.restype = ctypes.c_char_p
        library.cadence_d3d_info.argtypes = [pointer]
        library.cadence_d3d_info.restype = ctypes.c_char_p
        library.cadence_d3d_paint.argtypes = [pointer, pointer, pointer, integer, integer,
            pointer, integer, revision, revision, revision, pointer, integer, integer,
            integer, pointer, ctypes.c_size_t, revision, integer, integer, integer, integer, integer, integer, ctypes.c_float,pointer,integer,ctypes.c_float,ctypes.c_float]
        library.cadence_d3d_paint.restype = integer
        library.cadence_d3d_readback.argtypes = [pointer, pointer, ctypes.c_size_t, integer, integer]
        library.cadence_d3d_readback.restype = integer
        library.cadence_d3d_timings.argtypes = [pointer, ctypes.POINTER(ctypes.c_double)]
        library.cadence_d3d_timings.restype = None
        return library
    except (OSError, AttributeError, RuntimeError):
        logging.warning('Direct3D composition unavailable', exc_info=True)
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
            flip_h=False, flip_v=False, force=False, wipe=.5):
    if not force and os.environ.get('CADENCE_D3D_COMPOSITION', '1') == '0':
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


class D3DCompositor:
    def __init__(self, hwnd, *, readback=False):
        self.library = _library()
        self.handle = None
        self.failed = False
        self.sources = None
        self.size = (0, 0)
        self.capture = bool(readback)
        if self.library is not None:
            self.handle = self.library.cadence_d3d_create(int(hwnd), self.capture)
        if not self.handle:
            self.failed = True
            logging.warning('Direct3D renderer creation failed: %s', self.error())
        else:
            logging.info('Direct3D compositor: %s', self.library.cadence_d3d_info(self.handle).decode('utf-8', 'replace'))

    def error(self):
        message = self.library.cadence_d3d_error() if self.library else None
        return message.decode('utf-8', 'replace') if message else 'Direct3D module unavailable'

    def close(self):
        if self.handle:
            self.library.cadence_d3d_destroy(self.handle)
            self.handle = None
        self.sources = None
        self.size = (0, 0)

    def paint(self, packet, quad, overlay, width_px, height_px, *, layers=()):
        if self.failed or not self.handle or width_px <= 0 or height_px <= 0:
            return False
        a = b = table = None
        flip_h = flip_v = False
        passthrough = True
        image_width = image_height = 0
        coordinates = None
        if packet is not None:
            arrays, table, flip_h, flip_v, passthrough = packet
            a = arrays[0]
            b = arrays[1] if len(arrays) > 1 else None
            image_height, image_width = a.shape[:2]
            if quad is None or len(quad) != 8 or not all(np.isfinite(value) for value in quad):
                return False
            coordinates = (ctypes.c_double * 8)(*quad)
        storage = None
        overlay_pointer = None
        overlay_stride = overlay_revision = 0
        if overlay is not None and not overlay.isNull():
            if overlay.width() != width_px or overlay.height() != height_px:
                return False
            if overlay.format() != QImage.Format.Format_RGBA8888_Premultiplied:
                overlay = overlay.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
            storage = (ctypes.c_uint8 * overlay.sizeInBytes()).from_buffer(overlay.bits())
            overlay_pointer = ctypes.addressof(storage)
            overlay_stride = overlay.bytesPerLine()
            overlay_revision = overlay.cacheKey()
        drawing_storage=[]; drawing_images=[]; native_layers=(DrawLayer*len(layers))()
        for i,(image,points,alpha,clip) in enumerate(layers):
            if image.format()!=QImage.Format.Format_ARGB32_Premultiplied: image=image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            pixels=np.frombuffer(image.constBits(),np.uint8); drawing_storage.append(pixels); drawing_images.append(image)
            native_layers[i]=DrawLayer(pixels.ctypes.data,image.width(),image.height(),image.bytesPerLine(),image.cacheKey(),(ctypes.c_double*8)(*points),alpha,(ctypes.c_float*4)(*clip))
        code = self.library.cadence_d3d_paint(self.handle,
            a.ctypes.data if a is not None else None, b.ctypes.data if b is not None else None,
            image_width, image_height, table.ctypes.data if table is not None else None,
            (256 if table is not None and table.ndim==3 else 1), id(a), id(b), id(table),
            ctypes.addressof(coordinates) if coordinates is not None else None,
            flip_h, flip_v, passthrough, overlay_pointer, overlay_stride, overlay_revision,
            width_px, height_px, b.shape[1] if b is not None else 0, b.shape[0] if b is not None else 0, packet.layout if packet is not None else 0, packet.swapped if packet is not None else False, round(packet.wipe*a.shape[1])/a.shape[1] if packet is not None else .5,ctypes.addressof(native_layers),len(layers),packet.opacity if packet is not None else .5,packet.gain if packet is not None else 1.)
        if code:
            if code >= 2:
                logging.warning('Direct3D painting failed: %s', self.error())
                self.failed = True
            return False
        self.sources = (a, b, table, overlay)
        self.size = (width_px, height_px)
        return True

    def timings(self):
        if not self.handle:
            return {}
        values = (ctypes.c_double * 5)()
        self.library.cadence_d3d_timings(self.handle, values)
        return dict(zip(('resize', 'upload_video', 'upload_overlay', 'draw', 'present'), values))

    def drawing_stats(self):
        values=(ctypes.c_uint64*3)()
        if self.handle:
            self.library.cadence_d3d_drawing_stats.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint64)]
            self.library.cadence_d3d_drawing_stats.restype=None
            self.library.cadence_d3d_drawing_stats(self.handle,values)
        return dict(zip(('bytes','textures','uploads'),values))

    def readback(self):
        if not self.handle or not self.capture or not all(self.size):
            raise RuntimeError('Readback requires a renderer created with readback=True and a rendered frame')
        width, height = self.size
        image = np.empty((height, width, 4), np.uint8)
        code = self.library.cadence_d3d_readback(self.handle, image.ctypes.data, image.strides[0], width, height)
        if code:
            raise RuntimeError(self.error())
        return image
