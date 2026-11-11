# SPDX-License-Identifier: GPL-3.0-only
from collections import OrderedDict
from functools import lru_cache
import ctypes,threading

MIB=1024*1024

@lru_cache(maxsize=1)
def physical_memory_mb():
    class Status(ctypes.Structure):
        _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[(name,ctypes.c_uint64) for name in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
    try:
        status=Status(); status.length=ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)): return status.total//MIB
    except (AttributeError,OSError): pass
    return 4096

def maximum_cache_mb(): return max(64,physical_memory_mb()//2)
def default_cache_mb(): return min(1024,max(64,physical_memory_mb()//8))

class FrameCache:
    def __init__(self,budget=None):
        self.budget=default_cache_mb()*MIB if budget is None else max(0,int(budget))
        self.frames=OrderedDict(); self.raw=OrderedDict(); self.raw_bytes=0; self.bytes=0; self.lock=threading.Lock()
    def get(self,key):
        with self.lock:
            frame=self.frames.get(key)
            if frame is not None: self.frames.move_to_end(key)
            return frame
    def put(self,key,frame):
        with self.lock:
            old=self.frames.pop(key,None)
            if old is not None: self.bytes-=old.nbytes
            if frame.nbytes<=self.budget:
                self.frames[key]=frame; self.bytes+=frame.nbytes
            self._trim()
    def _trim(self):
        while self.raw and self.raw_bytes>self.budget//4:
            _,(_,size)=self.raw.popitem(last=False); self.raw_bytes-=size; self.bytes-=size
        while self.bytes>self.budget and self.frames:
            _,old=self.frames.popitem(last=False); self.bytes-=old.nbytes
    def get_decoded(self,key):
        with self.lock:
            item=self.raw.get(key)
            if item is not None: self.raw.move_to_end(key); return item[0]
    def put_decoded(self,key,frame):
        size=sum(plane.buffer_size for plane in frame.planes)
        with self.lock:
            old=self.raw.pop(key,None)
            if old is not None: self.raw_bytes-=old[1]; self.bytes-=old[1]
            if size<=self.budget//4:
                self.raw[key]=(frame,size); self.raw_bytes+=size; self.bytes+=size
            self._trim()
    def set_budget(self,budget):
        with self.lock:
            self.budget=max(0,int(budget)); self._trim()
    def discard_decoded_source(self,identity):
        with self.lock:
            for key in list(self.raw):
                if key[0]==identity:
                    _,size=self.raw.pop(key); self.raw_bytes-=size; self.bytes-=size
    def clear(self):
        with self.lock: self.frames.clear(); self.raw.clear(); self.raw_bytes=0; self.bytes=0
