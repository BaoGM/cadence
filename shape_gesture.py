# SPDX-License-Identifier: GPL-3.0-only
import math


def add(a,b): return a[0]+b[0],a[1]+b[1]
def sub(a,b): return a[0]-b[0],a[1]-b[1]
def mul(a,n): return a[0]*n,a[1]*n
def rotate(point,angle):
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    return point[0]*c-point[1]*s,point[0]*s+point[1]*c


class ShapeGesture:
    def __init__(self,tool,start,end=None,pointer=None):
        self.tool=tool; self.a=start; self.b=end or start; self.angle=0.
        self.last=pointer or self.b; self.modifiers=None

    def update(self,point,shift=False,ctrl=False,alt=False):
        modifiers=(shift,ctrl,alt)
        if modifiers!=self.modifiers:
            self.base_a,self.base_b,self.base_angle=self.a,self.b,self.angle
            self.origin=self.last; self.modifiers=modifiers
        a,b,angle=self.base_a,self.base_b,self.base_angle
        delta=sub(point,self.origin); extent=sub(b,a)
        if alt and ctrl:
            first,last=sub(self.origin,a),sub(point,a)
            if math.hypot(*first)>.001 and math.hypot(*last)>.001:
                turn=math.degrees(math.atan2(first[0]*last[1]-first[1]*last[0],first[0]*last[0]+first[1]*last[1]))
                angle+=turn
            if shift:
                if self.tool=='arrow': angle=round(angle/15)*15
                else:
                    side=max(abs(extent[0]),abs(extent[1]))
                    extent=(math.copysign(side,extent[0]),math.copysign(side,extent[1]))
            b=add(a,extent)
        elif alt:
            a,b=add(a,delta),add(b,delta)
        else:
            local=rotate(delta,-angle); extent=add(extent,mul(local,2 if ctrl else 1))
            if shift:
                if self.tool=='arrow':
                    direction=round(math.degrees(math.atan2(extent[1],extent[0]))/15)*15
                    extent=rotate((math.hypot(*extent),0),direction)
                else:
                    side=(abs(extent[0]) if abs(local[0])>abs(local[1]) else abs(extent[1])) if math.hypot(*local)>.001 else max(abs(extent[0]),abs(extent[1]))
                    extent=(math.copysign(side,extent[0]),math.copysign(side,extent[1]))
            if ctrl:
                center=add(a,rotate(mul(sub(b,a),.5),angle))
                a=sub(center,rotate(mul(extent,.5),angle))
            b=add(a,extent)
        self.a,self.b,self.angle,self.last=a,b,(angle+180)%360-180,point
        return self

    def normalized(self,width,height):
        return tuple((max(-4,min(5,p[0]/width)),max(-4,min(5,p[1]/height)),1.) for p in (self.a,self.b))
