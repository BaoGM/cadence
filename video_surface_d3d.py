# SPDX-License-Identifier: GPL-3.0-only
import logging
import math
import os
import time
import numpy as np
from PySide6.QtCore import QObject,QTimer,Qt,Signal
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication,QWidget


class D3DSurface(QWidget):
    frameSwapped=Signal()
    def __init__(self,viewer):
        super().__init__(viewer)
        self.viewer=viewer; self.overlay=None; self._fallback_key=None; self._fallback_packet=None
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(viewer.rect())
        from native_d3d import D3DCompositor
        self.compositor=D3DCompositor(int(self.winId()),readback=os.environ.get('CADENCE_RENDER_READBACK')=='1')
        self.destroyed.connect(self.compositor.close)
    def paintEngine(self): return None
    def isValid(self): return bool(self.compositor.handle) and not self.compositor.failed
    def format(self):
        from PySide6.QtGui import QSurfaceFormat
        value=QSurfaceFormat(); value.setSwapInterval(1); return value
    def grabFramebuffer(self):
        pixels=self.compositor.readback()
        image=QImage(pixels.data,pixels.shape[1],pixels.shape[0],pixels.strides[0],QImage.Format.Format_RGBA8888).copy()
        image.setDevicePixelRatio(self.devicePixelRatioF()); return image
    def paintEvent(self,event):
        if not self.isValid(): return
        ratio=self.devicePixelRatioF(); width=max(1,math.ceil(self.width()*ratio)); height=max(1,math.ceil(self.height()*ratio))
        if self.overlay is None or self.overlay.width()!=width or self.overlay.height()!=height:
            self.overlay=QImage(width,height,QImage.Format.Format_RGBA8888_Premultiplied)
        self.overlay.setDevicePixelRatio(ratio); self.overlay.fill(Qt.GlobalColor.transparent)
        packet=None; quad=None; layers=[]
        def drawing(painter,rectangle,image,opacity):
            from drawing_gpu import collect_layer
            layer=collect_layer(painter,rectangle,image,opacity)
            if layer is not None: layers.append(layer)
        def video(painter,rectangle):
            nonlocal packet,quad
            packet=self.viewer.gpu_packet
            if packet is None:
                image=self.viewer.cpu_preview()
                key=image.cacheKey()
                if key!=self._fallback_key:
                    from native_d3d import prepare
                    image=image.convertToFormat(QImage.Format.Format_RGB888)
                    data=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()
                    self._fallback_packet=prepare(data,force=True); self._fallback_key=key
                packet=self._fallback_packet
            transform=painter.deviceTransform()
            corners=[transform.map(point) for point in (rectangle.topLeft(),rectangle.topRight(),rectangle.bottomLeft(),rectangle.bottomRight())]
            quad=tuple(value for point in corners for value in (point.x(),point.y()))
            return True
        painter=QPainter(self.overlay)
        try: self.viewer.paint_scene(painter,video_draw=video,drawing_draw=drawing)
        finally: painter.end()
        if self.compositor.paint(packet,quad,self.overlay,width,height,layers=layers): self.frameSwapped.emit()
        elif not getattr(self,'_fallback_scheduled',False):
            self._fallback_scheduled=True
            QTimer.singleShot(0,self,self.fallback)
    def fallback(self):
        from video_surface import GraphicsStartup
        logging.warning('Direct3D presentation failed; trying OpenGL')
        viewer=self.viewer; self.compositor.close(); self.hide()
        viewer.surface=None; viewer.renderer='software'; viewer._effect_signature=None; viewer.apply_effect()
        self.deleteLater(); viewer.graphics_startup=GraphicsStartup(viewer); viewer.graphics_startup.schedule()


class D3DStartup(QObject):
    ready=Signal()
    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.started=False; self.finished=False; self.closed=False
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.activate)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
    def schedule(self):
        if not self.started and not self.closed and not self.timer.isActive(): self.timer.start(250)
    def activate(self):
        if self.closed or self.started: return
        if QApplication.mouseButtons()!=Qt.MouseButton.NoButton or QApplication.activeModalWidget() or not self.viewer.isVisible(): self.timer.start(100); return
        self.started=True; surface=None; started=time.perf_counter()
        try:
            surface=D3DSurface(self.viewer)
            if not surface.isValid(): raise RuntimeError('Direct3D initialization failed')
            self.viewer.surface=surface; self.viewer.renderer='direct3d'
            self.viewer._effect_signature=None; self.viewer.apply_effect(); surface.show(); surface.update()
            self.finished=True; self.ready.emit()
            logging.info('Direct3D video surface ready: %.3fs',time.perf_counter()-started)
        except Exception:
            logging.exception('Direct3D unavailable; trying OpenGL')
            if surface: surface.compositor.close(); surface.deleteLater()
            from video_surface import GraphicsStartup
            self.finished=True; self.viewer.surface=None; self.viewer.renderer='software'
            self.viewer.graphics_startup=GraphicsStartup(self.viewer); self.viewer.graphics_startup.schedule()
            self.ready.emit()
    def cancel(self): self.closed=True; self.timer.stop()
    def shutdown(self): self.cancel()
