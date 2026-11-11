# SPDX-License-Identifier: GPL-3.0-only
import ctypes
import numpy as np
import pytest
from PySide6.QtCore import Qt, QEvent, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
import native_d3d


@pytest.fixture(scope='module')
def application():
    application = QApplication.instance() or QApplication([])
    if application.platformName() != 'windows':
        pytest.skip('Windows native surface required')
    return application


class NativeWindow(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEngine(self):
        return None

    def paintEvent(self, event):
        pass


@pytest.fixture
def surface(application):
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    host.setWindowFlag(Qt.WindowType.Tool)
    host.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    host.move(32, 32); host.resize(256, 256)
    child = NativeWindow(host); child.setGeometry(0, 0, 256, 256)
    host.show(); QTest.qWait(60)
    renderer = native_d3d.D3DCompositor(int(child.winId()), readback=True)
    assert renderer.handle, renderer.error()
    try:
        yield renderer, host, child
    finally:
        renderer.close(); host.close(); host.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete); application.processEvents()


def image_pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()


def reference(a, b=None, *, ev=0, mode='single', opacity=.5, gain=1, swapped=False, flip_h=False, flip_v=False):
    from media import exposure_lut
    from comparison import compose
    left = exposure_lut(ev)[a] if ev else a
    if b is not None:
        right = exposure_lut(ev)[b] if ev else b
        left = compose(left, right, mode, opacity, gain, swapped)
    if flip_h:
        left = left[:, ::-1]
    if flip_v:
        left = left[::-1]
    left = np.ascontiguousarray(left)
    return QImage(left.data, left.shape[1], left.shape[0], left.strides[0], QImage.Format.Format_RGB888).copy()


def test_d3d_native_pixels_and_lookups(surface):
    renderer, _, _ = surface
    a = np.repeat(np.broadcast_to(np.arange(256, dtype=np.uint8)[:, None, None], (256, 256, 1)), 3, axis=2).copy()
    b = np.transpose(a, (1, 0, 2)).copy()
    quad = [0, 0, 256, 0, 0, 256, 256, 256]
    for mode in ('single', 'overlay', 'difference'):
        for ev in (0, -.7, 1.5):
            for flipped in (False, True):
                settings = dict(ev=ev, mode=mode, opacity=.37, gain=1.7, swapped=True, flip_h=flipped)
                packet = native_d3d.prepare(a, b, **settings)
                assert renderer.paint(packet, quad, None, 256, 256), renderer.error()
                expected = reference(a, b if mode != 'single' else None, **settings)
                np.testing.assert_array_equal(renderer.readback(), image_pixels(expected))


def test_d3d_premultiplied_overlay_and_background(surface):
    renderer, _, _ = surface
    source = np.full((63, 79, 3), [23, 57, 144], np.uint8)
    overlay = QImage(79, 63, QImage.Format.Format_RGBA8888_Premultiplied)
    overlay.fill(Qt.GlobalColor.transparent)
    painter = QPainter(overlay)
    painter.fillRect(7, 11, 51, 37, QColor(213, 85, 32, 127)); painter.end()
    quad = [0, 0, 79, 0, 0, 63, 79, 63]
    assert renderer.paint(native_d3d.prepare(source), quad, overlay, 79, 63), renderer.error()
    expected = reference(source).convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    painter = QPainter(expected); painter.drawImage(0, 0, overlay); painter.end()
    delta = np.abs(renderer.readback().astype(np.int16) - image_pixels(expected).astype(np.int16))
    assert delta.max() <= 1
    assert renderer.paint(None, None, None, 37, 29), renderer.error()
    np.testing.assert_array_equal(renderer.readback(), np.broadcast_to(np.array([12, 15, 20, 255], np.uint8), (29, 37, 4)))
    assert not renderer.paint(None, None, overlay, 37, 29)
    assert not renderer.failed


def test_d3d_transformed_odd_stride_and_resize(surface):
    renderer, _, _ = surface
    rng = np.random.default_rng(161)
    for width, height, zoom, angle in ((251, 193, 1, 0), (307, 211, 1.7, 27)):
        a = rng.integers(0, 256, (71, 111, 3), np.uint8)
        b = rng.integers(0, 256, a.shape, np.uint8)
        transform = QTransform().translate(width/2, height/2).rotate(angle).scale(zoom, zoom)
        rectangle = QRectF(-55.5, -35.5, 111, 71)
        quad = [value for point in (rectangle.topLeft(), rectangle.topRight(), rectangle.bottomLeft(), rectangle.bottomRight())
                for value in (transform.map(point).x(), transform.map(point).y())]
        for mode in ('single', 'overlay', 'difference'):
            settings = dict(ev=.7, mode=mode, flip_h=True, flip_v=True)
            assert renderer.paint(native_d3d.prepare(a, b, **settings), quad, None, width, height), renderer.error()
            expected = QImage(width, height, QImage.Format.Format_RGBA8888)
            expected.fill(QColor('#0c0f14'))
            painter = QPainter(expected); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setTransform(transform)
            painter.drawImage(rectangle, reference(a, b if mode != 'single' else None, **settings)); painter.end()
            cpu = image_pixels(expected); gpu = renderer.readback()
            mask = np.any(cpu[:, :, :3] != [12, 15, 20], axis=2) & np.any(gpu[:, :, :3] != [12, 15, 20], axis=2)
            for shift in (-2, -1, 1, 2):
                mask &= np.roll(mask, shift, axis=0) & np.roll(mask, shift, axis=1)
            assert np.count_nonzero(mask) > 1000
            delta = np.abs(cpu.astype(np.int16) - gpu.astype(np.int16))
            assert np.percentile(delta[mask], 99) <= 3


def test_d3d_reused_reference_revision_and_recreate(surface, monkeypatch):
    renderer, _, child = surface
    function = renderer.library.cadence_d3d_paint
    def fixed_revision(*arguments):
        arguments = list(arguments); arguments[8] = 42 if arguments[2] else 0
        return function(*arguments)
    monkeypatch.setattr(renderer.library, 'cadence_d3d_paint', fixed_revision)
    a = np.zeros((17, 23, 3), np.uint8)
    quad = [0, 0, 23, 0, 0, 17, 23, 17]
    for color in ([233, 27, 49], None, [31, 55, 219]):
        b = np.full_like(a, color) if color is not None else None
        mode = 'overlay' if b is not None else 'single'
        assert renderer.paint(native_d3d.prepare(a, b, mode=mode, opacity=1), quad, None, 23, 17)
        np.testing.assert_array_equal(renderer.readback(), image_pixels(reference(a, b, mode=mode, opacity=1)))
    renderer.close(); renderer.close()
    replacement = native_d3d.D3DCompositor(int(child.winId()), readback=True)
    try:
        assert replacement.handle, replacement.error()
        assert replacement.paint(None, None, None, 23, 17)
        assert replacement.readback().shape == (17, 23, 4)
    finally:
        replacement.close()


def test_d3d_invalid_input_and_explicit_readback(application):
    library = native_d3d._library()
    assert library is not None
    assert library.cadence_d3d_create(None, 0) is None
    library.cadence_d3d_destroy(None)
    source = np.zeros((3, 5, 3), np.uint8)
    assert native_d3d.prepare(source, ev=float('nan')) is None
    assert native_d3d.prepare(source, source[:1], mode='overlay').layout==5
    packet = native_d3d.prepare(source[:, ::-1])
    assert packet[0][0].flags.c_contiguous


def test_d3d_adapter_override(surface, monkeypatch):
    renderer, _, child = surface
    information = renderer.library.cadence_d3d_info(renderer.handle).decode()
    adapter_name = information.split('adapter=', 1)[1].split(';', 1)[0]
    renderer.close()
    monkeypatch.setenv('CADENCE_D3D_ADAPTER', '__cadence_missing_adapter_160__')
    missing = native_d3d.D3DCompositor(int(child.winId()))
    assert missing.failed and missing.handle is None
    assert 'No hardware Direct3D adapter matches' in missing.error()
    missing.close()
    monkeypatch.setenv('CADENCE_D3D_ADAPTER', adapter_name.swapcase())
    selected = native_d3d.D3DCompositor(int(child.winId()))
    try:
        assert selected.handle, selected.error()
        information = selected.library.cadence_d3d_info(selected.handle).decode()
        assert f'adapter={adapter_name};' in information
        assert 'selection=forced;' in information
        assert selected.paint(None, None, None, 23, 17)
    finally:
        selected.close()
