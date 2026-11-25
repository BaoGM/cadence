# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEasingCurve, QElapsedTimer, QRect, Qt, QVariantAnimation
from PySide6.QtWidgets import QLabel


class SidePanelMotion(QVariantAnimation):
    def __init__(self, chrome):
        super().__init__(chrome)
        self.chrome = chrome
        self.window = chrome.w
        self.paths = {}
        self.previews = {}
        self.measuring = False
        self.setDuration(240)
        self.setEasingCurve(QEasingCurve.InOutSine)
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.valueChanged.connect(self.advance)
        self.finished.connect(self.settle)
        for dock in (self.window.library,self.window.comparison_panel,self.window.drawing.panel):
            dock.visibilityChanged.connect(self.settle)
            dock.topLevelChanged.connect(self.settle)

    def visible_geometry(self, widget):
        if widget.isVisible() and self.window.rect().intersects(widget.geometry()):
            return widget.geometry()
        return None

    def outside(self, rect, side):
        target = QRect(rect)
        if side == 'left':
            target.moveRight(-1)
        else:
            target.moveLeft(self.window.width())
        return target

    def toggle(self, docks, opening):
        w = self.window
        if not docks:
            return
        elapsed = QElapsedTimer()
        elapsed.start()
        continuing = bool(self.paths)
        self.stop()
        lateral = {dock:edge for edge in ('left','right') for dock in self.chrome.side_docks(edge).values()}
        moving = [w.viewer_workspace, *lateral]
        starts = {widget:rect for widget in moving if (rect := self.visible_geometry(widget)) is not None}
        for dock, preview in self.previews.items():
            starts[dock] = preview.geometry()
        if not opening:
            for dock in docks:
                if dock not in starts or dock in self.previews:
                    continue
                # A closing dock must immediately release its focus and workspace state.
                preview = QLabel(w)
                preview.setAttribute(Qt.WA_TransparentForMouseEvents)
                preview.setPixmap(dock.grab())
                self.previews[dock] = preview
        self.paths.clear()
        self.measuring = True
        outer = w.layout()
        outer.setEnabled(True)
        inner = w.viewer_workspace.layout()
        stage = self.chrome.stage_layout
        stage.setEnabled(False)
        surface = w.viewer.surface
        if hasattr(surface, 'begin_panel_slide'):
            surface.begin_panel_slide()
        try:
            for dock in docks:
                dock.setVisible(opening)
            outer.invalidate()
            outer.activate()
            inner.activate()
            headers = self.chrome.headers
            if headers.read and headers.top.isVisible():
                headers.reserve_top(self.chrome.top.height() if headers.narrow_header() else 0)
                inner.activate()
            for widget in moving:
                end = self.visible_geometry(widget)
                start = starts.get(widget)
                preview = self.previews.get(widget)
                if end is None:
                    if start is None or preview is None:
                        continue
                    end = self.outside(start, lateral[widget])
                    view = preview
                    preview.show()
                else:
                    if preview is not None:
                        preview.hide()
                        preview.deleteLater()
                        del self.previews[widget]
                    if start is None:
                        start = self.outside(end, lateral[widget])
                    view = widget
                if start != end:
                    self.paths[view] = (start, end)
            # Let Qt measure the user's actual dock layout once. During the slide the
            # nested video layout stays live, including its tool rail and transport.
            if self.paths:
                outer.setEnabled(False)
                self.advance(0.0)
        finally:
            self.measuring = False
            inner.activate()
            stage.setEnabled(True)
            stage.invalidate()
            stage.activate()
        if self.paths:
            self.start()
            if w.viewer.panel_raster and not continuing:
                # Include layout measurement in the first visible step, capped
                # at one animation tick even for a slow, thumbnail-heavy dock.
                self.setCurrentTime(min(elapsed.elapsed(), 16))
        else:
            self.settle()
            if hasattr(surface, 'end_panel_slide'):
                surface.end_panel_slide()

    def advance(self, amount):
        for widget, (start, end) in self.paths.items():
            geometry = QRect(*(round(a+(b-a)*amount) for a,b in zip(start.getRect(),end.getRect())))
            if geometry != widget.geometry():
                widget.setGeometry(geometry)

    def settle(self):
        if self.measuring or not (self.paths or self.previews):
            return
        self.stop()
        self.paths.clear()
        for preview in self.previews.values():
            preview.hide()
            preview.deleteLater()
        self.previews.clear()
        layout = self.window.layout()
        layout.setEnabled(True)
        layout.invalidate()
        layout.activate()
        surface = self.window.viewer.surface
        if hasattr(surface, 'end_panel_slide'):
            surface.end_panel_slide()
        self.window.viewer.update()
