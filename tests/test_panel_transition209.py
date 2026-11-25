# SPDX-License-Identifier: GPL-3.0-only
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from test_drawing import application, window
from video_surface_d3d import D3DSurface


def test_raster_paints_current_video_when_native_surface_hides(window, application):
    viewer = window.viewer
    backing = window.backingStore()

    class Surface(QWidget):
        begin_panel_slide = D3DSurface.begin_panel_slide

    previous = viewer.surface
    renderer = viewer.renderer
    surface = Surface(viewer)
    surface.viewer = viewer
    try:
        surface.setGeometry(viewer.rect())
        surface.show()
        application.processEvents()
        viewer.surface = None
        viewer.set_frame(np.full((90, 160, 3), [223, 82, 65], dtype=np.uint8))
        viewer.surface = surface
        viewer.renderer = 'direct3d'
        surface.begin_panel_slide()
        application.processEvents()
        assert not surface.isVisible() and viewer.panel_raster
        image = backing.paintDevice()
        assert isinstance(image, QImage)
        point = viewer.mapTo(window, viewer.rect().center()) * image.devicePixelRatio()
        assert image.pixelColor(point).getRgb()[:3] == (223, 82, 65)
    finally:
        viewer.panel_raster = False
        viewer.renderer = renderer
        viewer.surface = previous
        surface.deleteLater()


def test_panel_reversal_presents_native_surface_only_at_rest(window, application):
    viewer = window.viewer

    class Surface(QWidget):
        begin_panel_slide = D3DSurface.begin_panel_slide
        end_panel_slide = D3DSurface.end_panel_slide

        def render_frame(self):
            presentations.append((self.isVisible(), self.geometry(), viewer.rect()))

    presentations = []
    original = viewer.surface
    surface = Surface(viewer)
    surface.viewer = viewer
    viewer.surface = surface
    surface.setGeometry(viewer.rect())
    surface.show()
    button = window.studio.dock_button
    motion = window.studio.side_motion
    try:
        initial = surface.geometry()
        button.click()
        motion.pause()
        motion.setCurrentTime(motion.duration() // 2)
        assert viewer.panel_raster and not surface.isVisible()
        assert surface.geometry() == initial and viewer.rect() != initial
        button.click()
        motion.pause()
        assert viewer.panel_raster and not presentations
        motion.setCurrentTime(motion.duration())
        assert presentations == [(False, viewer.rect(), viewer.rect())]
        assert not viewer.panel_raster and surface.isVisible()
    finally:
        motion.settle()
        viewer.surface = original
        surface.hide()
        surface.deleteLater()
