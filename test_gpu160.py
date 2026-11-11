# SPDX-License-Identifier: GPL-3.0-only
import os
import numpy as np
import pytest
from PySide6.QtCore import Qt, QRectF, QEvent
from PySide6.QtGui import QPainter, QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtOpenGL import QOpenGLWindow
from PySide6.QtTest import QTest
import native_gpu


def test_packet_validation_and_contiguous_owners():
    source = np.arange(19 * 23 * 3, dtype=np.uint8).reshape(19, 23, 3)
    view = source[::-1, ::2]
    packet = native_gpu.prepare(view, ev=0)
    assert packet is not None and packet[-1]
    np.testing.assert_array_equal(packet[0][0], view)
    assert packet[0][0].flags.c_contiguous
    assert native_gpu.prepare(source, source[:7], mode='overlay').layout==5
    assert native_gpu.prepare(source, ev=float('nan')) is None
    assert native_gpu.prepare(source, mode='wipe') is None
    assert native_gpu.prepare(source.astype(np.float32)) is None
    assert native_gpu.prepare(source, ev=1)[-1] is False


def test_lookup_keeps_exact_reference_rounding():
    from native_render import _table
    for ev in (-10, -.7, 0, 1.5, 10):
        for mode in ('single', 'overlay', 'difference'):
            gpu = native_gpu._table(ev, mode, .37, 1.7, True)
            reference = _table(ev, mode, .37, 1.7, True)
            np.testing.assert_array_equal(gpu[..., 0], reference)
            assert np.all(gpu[..., 0] == gpu[..., 1]) and np.all(gpu[..., 3] == 255)


@pytest.fixture(scope='module')
def application():
    from video_surface import configure_graphics
    configure_graphics()
    application = QApplication.instance() or QApplication([])
    if application.platformName() in ('offscreen', 'minimal'):
        pytest.skip('A native OpenGL context is required')
    return application


class Surface(QOpenGLWindow):
    def __init__(self):
        super().__init__(QOpenGLWindow.UpdateBehavior.NoPartialUpdate)
        self.compositor = native_gpu.GpuCompositor(self)
        self.packet = None
        self.reference = None
        self.cpu = False
        self.used = False
        self.angle = 0
        self.zoom = 1
        self.host = QWidget()
        self.host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.host.setWindowFlag(Qt.WindowType.Tool)
        self.host.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.host.move(32, 32)
        self.container = QWidget.createWindowContainer(self, self.host)

    def show(self):
        self.host.resize(self.width(), self.height())
        self.container.setGeometry(0, 0, self.width(), self.height())
        self.host.show()
        super().show()

    def close(self):
        self.host.close()
        return super().close()

    def paintGL(self):
        painter = QPainter(self)
        try:
            painter.fillRect(0, 0, self.width(), self.height(), QColor('#192534'))
            if self.packet is None:
                return
            height, width = self.packet[0][0].shape[:2]
            painter.translate(self.width() / 2, self.height() / 2)
            painter.rotate(self.angle)
            painter.scale(self.zoom, self.zoom)
            rectangle = QRectF(-width / 2, -height / 2, width, height)
            self.used = False if self.cpu else self.compositor.paint(painter, self.packet, rectangle)
            if self.cpu or not self.used:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(rectangle, self.reference)
            painter.resetTransform()
            painter.fillRect(0, 0, 3, 3, QColor('#00ffff'))
        finally:
            painter.end()


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()


def rendered_pixels(window):
    # NoPartialUpdate swaps two buffers; stabilize both before reading the default framebuffer.
    for _ in range(2):
        window.update()
        QTest.qWait(30)
    return pixels(window.grabFramebuffer())


def reference(a, b, ev, mode, opacity, gain, swapped, flip_h, flip_v):
    from media import exposure_lut
    from comparison import compose
    def effect(value):
        result = exposure_lut(ev)[value] if ev else value
        if flip_h: result = result[:, ::-1]
        if flip_v: result = result[::-1]
        return result
    array = effect(a) if mode == 'single' else compose(effect(a), effect(b), mode, opacity, gain, swapped)
    array = np.ascontiguousarray(array)
    return QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format.Format_RGB888).copy()


def test_gpu_native_size_exact_and_painter_state(application):
    window = Surface()
    a = np.repeat(np.broadcast_to(np.arange(256, dtype=np.uint8)[:, None, None], (256, 256, 1)), 3, axis=2).copy()
    b = np.transpose(a, (1, 0, 2)).copy()
    window.resize(256, 256); window.show(); QTest.qWait(100)
    try:
        for mode in ('single', 'overlay', 'difference'):
            for ev in (0, -.7, 1.5):
                for flip in (False, True):
                    window.packet = native_gpu.prepare(a, b, ev=ev, mode=mode, opacity=.37, gain=1.7, swapped=True, flip_h=flip)
                    window.reference = reference(a, b, ev, mode, .37, 1.7, True, flip, False)
                    window.cpu = False
                    gpu = rendered_pixels(window); assert window.used
                    window.cpu = True
                    cpu = rendered_pixels(window)
                    np.testing.assert_array_equal(gpu, cpu)
        window.compositor.close(); assert window.compositor.handle is None
        window.cpu = False; window.update(); QTest.qWait(20)
        assert window.used and window.compositor.handle
    finally:
        window.compositor.close(); window.host.close(); window.host.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete); application.processEvents()


def test_gpu_scaled_rotated_odd_rows_and_array_replacement(application):
    window = Surface(); window.resize(251, 193); window.show(); QTest.qWait(80)
    rng = np.random.default_rng(160)
    try:
        for mode in ('single', 'overlay', 'difference'):
            for angle, zoom in ((0, 1), (0, 2.1), (27, 1.3)):
                a = rng.integers(0, 256, (71, 111, 3), np.uint8)
                b = rng.integers(0, 256, a.shape, np.uint8)
                window.packet = native_gpu.prepare(a, b, ev=.7, mode=mode, flip_h=True, flip_v=True)
                window.reference = reference(a, b, .7, mode, .5, 1., False, True, True)
                window.angle = angle; window.zoom = zoom
                window.cpu = False
                gpu = rendered_pixels(window); assert window.used
                window.cpu = True
                cpu = rendered_pixels(window)
                # Edge coverage belongs to the rasterizer; compare the interior shared by both renders.
                background = np.array([25, 37, 52, 255], dtype=np.uint8)
                mask = np.any(cpu[:, :, :3] != background[:3], axis=2) & np.any(gpu[:, :, :3] != background[:3], axis=2)
                for shift in (-2, -1, 1, 2):
                    mask &= np.roll(mask, shift, axis=0) & np.roll(mask, shift, axis=1)
                assert np.count_nonzero(mask) > 1000
                delta = np.abs(cpu.astype(np.int16) - gpu.astype(np.int16))
                assert np.percentile(delta[mask], 99) <= 2
    finally:
        window.compositor.close(); window.host.close(); window.host.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete); application.processEvents()


def test_gpu_reference_revision_reused_after_single(application, monkeypatch):
    library = native_gpu._library()
    native_paint = library.cadence_gpu_paint
    def fixed_reference_revision(*arguments):
        arguments = list(arguments)
        arguments[9] = 42 if arguments[3] else 0
        return native_paint(*arguments)
    monkeypatch.setattr(library, 'cadence_gpu_paint', fixed_reference_revision)
    window = Surface(); window.resize(64, 64); window.show(); QTest.qWait(80)
    a = np.zeros((64, 64, 3), np.uint8)
    first = np.full_like(a, [192, 16, 32])
    second = np.full_like(a, [8, 48, 224])
    try:
        for mode, b in (('overlay', first), ('single', None), ('overlay', second)):
            window.packet = native_gpu.prepare(a, b, mode=mode, opacity=1)
            window.reference = reference(a, b, 0, mode, 1, 1, False, False, False)
            window.cpu = False
            gpu = rendered_pixels(window); assert window.used
            window.cpu = True
            cpu = rendered_pixels(window)
            np.testing.assert_array_equal(gpu, cpu)
    finally:
        window.compositor.close(); window.host.close(); window.host.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete); application.processEvents()
