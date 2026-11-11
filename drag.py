# SPDX-License-Identifier: GPL-3.0-only
"""Relative drags with edge recentering; widget values never see cursor warp jumps."""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QCursor,QGuiApplication

class ContinuousDrag:
    def __init__(self,origin,axes='x',warp=None,screen_rect=None):
        self.origin=QPointF(origin); self.last=QPointF(origin); self.total=QPointF(); self.axes=axes
        self.warp=warp or QCursor.setPos; self.screen_rect=screen_rect; self.pending=None; self.wrapped=False
        self.enabled=warp is not None or QGuiApplication.platformName() not in ('offscreen','minimal')
    def move(self,point):
        point=QPointF(point)
        if self.pending:
            target,rect,xwrap,ywrap=self.pending
            # Discard queued pre-warp events at the old edge; accept the warp or first real move after it.
            if (xwrap and abs(point.x()-target.x())>rect.width()/3) or (ywrap and abs(point.y()-target.y())>rect.height()/3): return QPointF(self.total)
            self.last=QPointF(target); self.pending=None
        delta=point-self.last; self.last=point; self.total+=delta
        if not self.enabled: return QPointF(self.total)
        screen=QGuiApplication.screenAt(point.toPoint()) if self.screen_rect is None else None
        rect=self.screen_rect or (screen.geometry() if screen else None)
        if rect is None: return QPointF(self.total)
        def outside(dx,dy):
            return self.screen_rect is not None or QGuiApplication.screenAt((point+QPointF(dx,dy)).toPoint()) is None
        xwrap='x' in self.axes and ((point.x()>=rect.right()-4 and delta.x()>0 and outside(12,0)) or (point.x()<=rect.left()+4 and delta.x()<0 and outside(-12,0)))
        ywrap='y' in self.axes and ((point.y()>=rect.bottom()-4 and delta.y()>0 and outside(0,12)) or (point.y()<=rect.top()+4 and delta.y()<0 and outside(0,-12)))
        if xwrap or ywrap:
            target=QPointF(rect.center().x() if xwrap else point.x(),rect.center().y() if ywrap else point.y())
            self.pending=(target,rect,xwrap,ywrap); self.wrapped=True; self.warp(target.toPoint())
        return QPointF(self.total)
    def finish(self,restore=True):
        self.pending=None
        if self.wrapped and restore: self.warp(self.origin.toPoint())
        self.wrapped=False
