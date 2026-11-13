# SPDX-License-Identifier: GPL-3.0-only
import json, logging, os, sys, time
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QOffscreenSurface, QPainter, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtOpenGL import QOpenGLWindow
from preferences import preference_path,preferred_renderer,default_renderer


def configured_renderer():
    override=os.environ.get('CADENCE_RENDERER')
    if override in ('software','opengl','direct3d'): return override
    try:
        return preferred_renderer(json.loads(preference_path().read_text(encoding='utf-8')))
    except (OSError,ValueError,AttributeError): return default_renderer()


def synchronized_format():
    fmt=QSurfaceFormat(); fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setSwapInterval(1); fmt.setDepthBufferSize(0); fmt.setStencilBufferSize(8)
    return fmt


def configure_graphics():
    QSurfaceFormat.setDefaultFormat(synchronized_format())


class SurfaceWindow(QOpenGLWindow):
    def __init__(self,viewer):
        super().__init__(QOpenGLWindow.UpdateBehavior.NoPartialUpdate); self.viewer=viewer
        self.setFormat(synchronized_format())
        self.setFlag(Qt.WindowType.WindowTransparentForInput)
        from native_gpu import GpuCompositor
        self.compositor=GpuCompositor(self)
    def initializeGL(self):
        logging.info('Video surface OpenGL initialized; swap interval=%s',self.format().swapInterval())
    def paintGL(self):
        painter=QPainter(self)
        try: self.viewer.paint_scene(painter)
        finally: painter.end()


class VideoSurface(QWidget):
    def __init__(self,viewer):
        super().__init__(viewer)
        self.gl=SurfaceWindow(viewer)
        self.compositor=self.gl.compositor
        self.container=QWidget.createWindowContainer(self.gl,self)
        self.container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(viewer.rect())
    def resizeEvent(self,event):
        self.container.setGeometry(self.rect())
        super().resizeEvent(event)
    def update(self,*args):
        super().update(*args); self.gl.update()
    def isValid(self): return self.gl.isValid()
    def format(self): return self.gl.format()
    def grabFramebuffer(self): return self.gl.grabFramebuffer()


class GraphicsWarmup(QThread):
    def __init__(self,surface,parent):
        super().__init__(parent); self.surface=surface; self.error=None; self.seconds=0.
    def run(self):
        started=time.perf_counter()
        try:
            import shiboken6
            from native_graphics import load_library
            library=load_library()
            result=library.cadence_prepare_graphics(shiboken6.getCppPointer(self.surface)[0])
            if result: raise RuntimeError(f'Native graphics preparation failed (code {result})')
            import ctypes
            phases=(ctypes.c_double*3)(); library.cadence_graphics_timings(phases)
            logging.info('Native graphics phases: create=%.3fs current=%.3fs release=%.3fs',*phases)
        except Exception as error:
            self.error=str(error)
        self.seconds=time.perf_counter()-started


class GraphicsStartup(QObject):
    ready=Signal()
    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.worker=None; self.offscreen=None
        self.started=False; self.closed=False; self.pending=False; self.finished=False
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.begin)
        self.activation=QTimer(self); self.activation.setSingleShot(True); self.activation.timeout.connect(self.activate)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
    def schedule(self):
        if not self.started and not self.closed and not self.timer.isActive(): self.timer.start(250)
    def begin(self):
        if self.closed or self.started: return
        self.started=True
        self.offscreen=QOffscreenSurface(); self.offscreen.setFormat(synchronized_format()); self.offscreen.create()
        self.worker=GraphicsWarmup(self.offscreen,self)
        self.worker.finished.connect(self.prepared); self.worker.start()
    def prepared(self):
        if self.closed: return
        self.offscreen.destroy(); self.offscreen=None
        if self.worker.error:
            logging.warning('Native graphics unavailable; keeping software presentation: %s',self.worker.error)
            self.finished=True; self.ready.emit(); return
        logging.info('Native graphics background preparation: %.3fs',self.worker.seconds)
        self.pending=True; self.activate()
    def activate(self):
        if self.closed or not self.pending: return
        if QApplication.mouseButtons()!=Qt.MouseButton.NoButton or QApplication.activeModalWidget() or not self.viewer.isVisible():
            self.activation.start(100); return
        self.pending=False; stamp=time.perf_counter()
        try:
            surface=VideoSurface(self.viewer)
            self.viewer.surface=surface
            surface.gl.frameSwapped.connect(self.presented)
            surface.show(); surface.update()
            QTimer.singleShot(2000,self,self.verify)
            logging.info('Video surface activation: %.3fs',time.perf_counter()-stamp)
        except Exception:
            logging.exception('Video surface activation failed; keeping software presentation')
            self.fallback()
    def presented(self):
        if self.closed or self.finished: return
        self.viewer.renderer='opengl'; self.finished=True
        self.viewer._effect_signature=None; self.viewer.apply_effect()
        logging.info('Video surface ready; native background preparation complete')
        self.ready.emit()
    def verify(self):
        if not self.closed and not self.finished:
            if self.viewer.surface and self.viewer.surface.isValid(): self.presented()
            else: self.fallback()
    def fallback(self):
        surface=self.viewer.surface; self.viewer.surface=None; self.viewer.renderer='software'
        if surface: surface.hide(); surface.deleteLater()
        self.finished=True; self.viewer._effect_signature=None; self.viewer.apply_effect(); self.ready.emit()
    def cancel(self):
        self.closed=True; self.timer.stop(); self.activation.stop()
    def shutdown(self):
        self.cancel()
        if self.worker and self.worker.isRunning(): self.worker.wait()
        if self.offscreen: self.offscreen.destroy(); self.offscreen=None


def attach_surface(viewer):
    viewer.surface=None; viewer.renderer='software'; viewer.graphics_startup=None
    if configured_renderer()=='software' or QApplication.platformName() in ('offscreen','minimal'): return
    if sys.platform=='win32':
        if configured_renderer()=='direct3d':
            from video_surface_d3d import D3DStartup
            viewer.graphics_startup=D3DStartup(viewer)
        else: viewer.graphics_startup=GraphicsStartup(viewer)
    elif sys.platform.startswith('linux'):
        viewer.graphics_startup=GraphicsStartup(viewer)
