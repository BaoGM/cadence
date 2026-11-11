# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from functools import lru_cache
import logging
import os
import numpy as np
from PySide6.QtGui import QImage


@lru_cache(maxsize=1)
def _library():
    try:
        from native_graphics import load_library
        library=load_library()
        library.cadence_render_abi.argtypes=[]
        library.cadence_render_abi.restype=ctypes.c_int
        if library.cadence_render_abi()!=1: raise RuntimeError('Incompatible rendering ABI')
        pointer=ctypes.c_void_p; stride=ctypes.c_ssize_t; integer=ctypes.c_int
        library.cadence_rgb_lut.argtypes=[pointer,stride,stride,pointer,stride,stride,pointer,stride,integer,integer,pointer]
        library.cadence_rgb_lut.restype=integer
        library.cadence_paint_stroke.argtypes=[pointer,pointer,ctypes.c_size_t,integer,integer,ctypes.c_double,integer,ctypes.c_double]
        library.cadence_paint_stroke.restype=integer
        library.cadence_alpha_bounds.argtypes=[pointer,ctypes.POINTER(integer)]
        library.cadence_alpha_bounds.restype=integer
        logging.info('Native pixel and stroke rendering ready')
        return library
    except (OSError,AttributeError,RuntimeError):
        logging.warning('Native rendering unavailable; using reference renderer',exc_info=True)
        return None


def available():
    return os.environ.get('CADENCE_NATIVE_RENDER','1')!='0' and _library() is not None


def alpha_bounds(image):
    from PySide6.QtCore import QRect
    if image.isNull(): return QRect()
    if available():
        from shiboken6 import getCppPointer
        bounds=(ctypes.c_int*4)()
        result=_library().cadence_alpha_bounds(getCppPointer(image)[0],bounds)
        if result: raise RuntimeError(f'Native alpha bounds failed: {result}')
        return QRect(*bounds)
    pixels=np.frombuffer(image.constBits(),dtype=np.uint32).reshape(image.height(),image.bytesPerLine()//4)[:,:image.width()]
    alpha=(pixels>>24)!=0; ys=np.flatnonzero(alpha.any(axis=1)); xs=np.flatnonzero(alpha.any(axis=0))
    return QRect(int(xs[0]),int(ys[0]),int(xs[-1]-xs[0]+1),int(ys[-1]-ys[0]+1)) if len(xs) else QRect()


@lru_cache(maxsize=16)
def _table(ev,mode,opacity,gain,swapped,reference_ev=None):
    from media import exposure_lut
    values=exposure_lut(ev) if ev else np.arange(256,dtype=np.uint8)
    if mode=='single': return values
    reference_ev=ev if reference_ev is None else reference_ev
    reference=exposure_lut(reference_ev) if reference_ev else np.arange(256,dtype=np.uint8)
    a,b=values[:,None],reference[None,:]
    if swapped: a,b=b,a
    if mode=='overlay':
        aa=a.astype(np.float32); aa*=1-opacity
        bb=b.astype(np.float32); bb*=opacity
        output=aa+bb; np.rint(output,out=output); np.clip(output,0,255,out=output)
    else:
        output=np.abs(np.subtract(a,b,dtype=np.int16))
        if gain!=1: output=np.clip(output*gain,0,255)
    return np.ascontiguousarray(output,dtype=np.uint8)


def rgb_image(a,b=None,*,ev=0.,mode='single',opacity=.5,gain=1.,swapped=False,flip_h=False,flip_v=False):
    if mode=='single' and not (ev or flip_h or flip_v): return None
    if mode not in ('single','overlay','difference') or not available(): return None
    arrays=(a,) if mode=='single' else (a,b)
    if any(not isinstance(arr,np.ndarray) or arr.dtype!=np.uint8 or arr.ndim!=3 or arr.shape[2]!=3 or not arr.size for arr in arrays): return None
    if not all(np.isfinite(v) for v in (ev,opacity,gain)): return None
    views=[]
    for arr in arrays:
        if arr.strides[2]!=1: arr=np.ascontiguousarray(arr)
        if flip_h: arr=arr[:,::-1]
        if flip_v: arr=arr[::-1]
        views.append(arr)
    a=views[0]; b=views[1] if len(views)>1 else None
    reference_ev=ev
    if b is not None and a.shape!=b.shape:
        from comparison import fit_reference
        if ev:
            exposed=_apply_table(b,None,_table(ev,'single',opacity,gain,False))
            b=np.frombuffer(exposed.constBits(),np.uint8).reshape(exposed.height(),exposed.bytesPerLine())[:,:exposed.width()*3].reshape(exposed.height(),exposed.width(),3)
        b=fit_reference(b,a.shape[1],a.shape[0]); reference_ev=0.
    return _apply_table(a,b,_table(ev,mode,opacity,gain,swapped,reference_ev))


def _apply_table(a,b,table):
    height,width=a.shape[:2]
    image=QImage(width,height,QImage.Format.Format_RGB888)
    if image.isNull(): raise MemoryError('Cannot allocate preview image')
    storage=(ctypes.c_ubyte*image.sizeInBytes()).from_buffer(image.bits())
    result=_library().cadence_rgb_lut(a.ctypes.data,*a.strides[:2],
        b.ctypes.data if b is not None else None,*(b.strides[:2] if b is not None else (0,0)),
        ctypes.addressof(storage),image.bytesPerLine(),width,height,table.ctypes.data)
    if result: raise RuntimeError(f'Native pixel rendering failed: {result}')
    return image


def paint_stroke(painter,mark,width,height):
    if not mark.points or not available(): return False
    from shiboken6 import getCppPointer
    points=np.ascontiguousarray(mark.points,dtype=np.float64)
    if points.ndim!=2 or points.shape[1]!=3: return False
    result=_library().cadence_paint_stroke(getCppPointer(painter)[0],points.ctypes.data,len(points),width,height,mark.size,mark.pressure,mark.sensitivity)
    if result==1: return False
    if result: raise RuntimeError(f'Native stroke rendering failed: {result}')
    return True
