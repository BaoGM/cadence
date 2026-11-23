# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject, QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QFrame, QScrollArea

from drag import ContinuousDrag


class CompactTransport(QObject):
    def __init__(self, strip, left, center, right, window):
        super().__init__(strip)
        self.strip, self.left, self.center, self.right = strip, left, center, right
        self.window = window
        self.scrub_owner = None
        self.scrubbing = False
        self.parts = (left,center,right)
        for part in self.parts:
            strip.layout().removeWidget(part)
            part.installEventFilter(self)
        strip.layout().setContentsMargins(0,0,0,0)
        self.controls = QScrollArea(strip)
        self.controls.setFrameShape(QFrame.NoFrame)
        self.controls.setWidget(center)
        self.controls.setFocusPolicy(Qt.NoFocus)
        self.controls.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.controls.setStyleSheet('QScrollArea {background:transparent;border:0;} QScrollBar:horizontal {height:5px;}')
        self.compact = False
        self.relayout = QTimer(self)
        self.relayout.setSingleShot(True)
        self.relayout.timeout.connect(self.update_geometry)
        for part in (strip,window,self.controls.viewport()): part.installEventFilter(self)

    def schedule(self):
        if not self.relayout.isActive(): self.relayout.start(0)

    def update_geometry(self):
        strip = self.strip
        width = strip.width()
        center = self.center.sizeHint()
        right = self.right.sizeHint()
        left = self.left.sizeHint()
        padding = 8 if width<550 else 15
        usable = max(1,width-2*padding)
        self.compact = center.width()+right.width()+left.width()+10>usable
        clipped = center.width()>usable
        height = (68 if self.compact else 39 if self.window.height()<=620 else 48)+(5 if clipped else 0)
        if strip.minimumHeight()!=height:
            strip.setFixedHeight(height)
            dock=strip.parentWidget()
            if dock and dock.inherits('QDockWidget'):
                dock.setMinimumHeight(0)
                dock.setMaximumHeight(16777215)
                dock.setFixedHeight(dock.sizeHint().height())
        row = 32 if self.compact else height
        center_width=min(center.width(),usable)
        target=strip.mapFromGlobal(self.window.mapToGlobal(QPoint(self.window.width()//2,0))).x()
        if self.window.transport_widget.isFloating(): target=width//2
        lo=padding if self.compact else padding+left.width()
        hi=width-padding-center_width-(0 if self.compact else right.width())
        x=max(lo,min(hi,target-center_width//2))
        self.center.resize(center.width(),row)
        self.controls.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if clipped else Qt.ScrollBarAlwaysOff)
        self.controls.setGeometry(x,0,center_width,row+(5 if clipped else 0))
        bottom=height-32 if self.compact else (height-32)//2
        self.left.setGeometry(padding,bottom,min(left.width(),usable),32)
        self.right.setGeometry(max(padding,width-padding-right.width()),bottom,min(right.width(),usable),32)
        self.controls.show()

    def eventFilter(self, obj, event):
        kind = event.type()
        if hasattr(self,'relayout') and kind in (QEvent.Resize,QEvent.LayoutRequest,QEvent.Move,QEvent.Show,QEvent.Hide):
            self.schedule()
        owner = self.scrub_owner
        if owner is not None:
            if ((kind in (QEvent.Hide, QEvent.UngrabMouse) and obj in (owner, self.strip))
                    or (kind == QEvent.WindowDeactivate and obj in (owner, self.strip, self.window))):
                self.finish_scrub(False)
            elif obj is owner and (kind == QEvent.MouseMove or
                    (kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton)):
                w = self.window
                if self.scrub_doc is w.doc and not w.job:
                    divisor = w.viewer.scrub_pixels * (3 if event.modifiers() & Qt.ShiftModifier else 1)
                    offset = int(self.drag.move(event.globalPosition()).x() / divisor)
                    target = max(0, min(w.doc.state.length, self.scrub_start + offset))
                    if offset != self.last_offset and target != w.doc.state.position:
                        if not self.scrubbing:
                            w.begin_scrub()
                            w.timeline.set_external_scrubbing(True)
                            self.scrubbing = True
                        w.seek(target, audition=True)
                    self.last_offset = offset
                    if kind == QEvent.MouseButtonRelease:
                        self.finish_scrub(True)
                else:
                    self.finish_scrub(False)
                event.accept()
                return True
        elif (kind == QEvent.MouseButtonPress and obj is not self.window and event.button() == Qt.LeftButton
                and not event.modifiers() & ~Qt.ShiftModifier):
            w = self.window
            if w.job or not w.doc.state.length:
                return False
            child = self.strip.childAt(self.strip.mapFromGlobal(event.globalPosition()).toPoint())
            while child is not None and child is not self.strip:
                if child is w.volume or isinstance(child, (QAbstractButton, QAbstractSlider)):
                    return False
                child = child.parentWidget()
            self.scrub_owner, self.scrub_doc = obj, w.doc
            self.scrub_start = w.doc.state.position
            self.last_offset = 0
            self.drag = ContinuousDrag(event.globalPosition())
            event.accept()
            return True
        return False

    def finish_scrub(self, restore_cursor):
        self.scrub_owner = self.scrub_doc = None
        self.drag.finish(restore=restore_cursor)
        if self.scrubbing:
            self.scrubbing = False
            self.window.timeline.set_external_scrubbing(False)
            self.window.end_scrub()
