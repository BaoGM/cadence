# SPDX-License-Identifier: GPL-3.0-only
from collections import OrderedDict
from contextlib import contextmanager


class DrawingRasterCache:
    def __init__(self,budget=256*1024*1024):
        self.budget=max(0,int(budget)); self.bytes=0; self.entries=OrderedDict(); self.admitted=None
        self.origins={}; self.priority={}; self.source=None

    @contextmanager
    def batch(self,marks,width,height):
        previous=self.admitted; previous_priority=self.priority
        capacity=self.budget//max(1,width*height*4)
        identities=list(dict.fromkeys((id(value),width,height) for value in marks if value))
        self.priority={identity+(True,):rank for rank,identity in enumerate(identities)}
        self.admitted=set(identities[:capacity])
        for identity in identities[:capacity]:
            if identity in self.entries: self.entries.move_to_end(identity)
        try: yield
        finally: self.admitted=previous; self.priority=previous_priority

    def clear(self):
        self.entries.clear(); self.origins.clear(); self.bytes=0; self.source=None

    def retain(self,keys):
        if keys is self.source: return
        self.source=keys
        retained={id(key.marks) for key in keys}
        for identity in list(self.entries):
            if identity[0] not in retained:
                self._remove(identity)

    def _remove(self,identity):
        _,image=self.entries.pop(identity); self.bytes-=image.sizeInBytes(); self.origins.pop(identity,None)

    def bounds(self,marks,width,height):
        from PySide6.QtCore import QRect
        identity=(id(marks),width,height,True); found=self.entries.get(identity)
        if found is not None: return QRect(*self.origins[identity],found[1].width(),found[1].height())
        from drawing import ink_bounds
        area=QRect()
        for mark in marks: area=area.united(ink_bounds(mark,width,height))
        return area

    def render_region(self,marks,width,height):
        identity=(id(marks),width,height,True)
        found=self.entries.get(identity)
        if found is not None:
            self.entries.move_to_end(identity)
            return self.origins[identity],found[1]
        from drawing import render_marks_region
        from native_render import alpha_bounds
        from PySide6.QtGui import QImage
        origin,image=render_marks_region(marks,width,height); area=alpha_bounds(image)
        if not area.isEmpty(): area=area.adjusted(-2,-2,2,2).intersected(image.rect())
        origin=(origin[0]+area.x(),origin[1]+area.y()); image=image.copy(area) if not area.isEmpty() else QImage()
        size=image.sizeInBytes()
        if marks and size<=self.budget:
            victims=sorted(self.entries,key=lambda key:self.priority.get(key,float('inf')),reverse=True)
            needed=self.bytes+size-self.budget; removed=0; chosen=[]
            for victim in victims:
                if removed>=needed and len(self.entries)-len(chosen)<4096: break
                if self.priority.get(victim,float('inf'))<self.priority.get(identity,float('inf')): break
                chosen.append(victim); removed+=self.entries[victim][1].sizeInBytes()
            if removed>=needed and len(self.entries)-len(chosen)<4096:
                for victim in chosen: self._remove(victim)
                self.entries[identity]=(marks,image); self.origins[identity]=origin; self.bytes+=size
        return origin,image

    def render(self,marks,width,height):
        identity=(id(marks),width,height)
        found=self.entries.get(identity)
        if found is not None:
            if self.admitted is None or identity in self.admitted: self.entries.move_to_end(identity)
            return found[1]
        from drawing import render_marks
        image=render_marks(marks,width,height); size=image.sizeInBytes()
        if marks and size<=self.budget and (self.admitted is None or identity in self.admitted):
            while self.entries and self.bytes+size>self.budget:
                self._remove(next(iter(self.entries)))
            # Retaining the immutable marks prevents reuse of their identity.
            self.entries[identity]=(marks,image); self.bytes+=size
        return image
