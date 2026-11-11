# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject, QEvent, Qt, QTimer


class CompactTransport(QObject):
    def __init__(self, strip, left, center, right, window):
        super().__init__(strip)
        self.strip = strip
        self.parts = (left, center, right)
        self.window = window
        self.compact = False
        strip.installEventFilter(self)
        window.installEventFilter(self)
        self.relayout = QTimer(self)
        self.relayout.setSingleShot(True)
        self.relayout.timeout.connect(self.update_geometry)

    def update_geometry(self):
        self.strip.updateGeometry()
        parent = self.strip.parentWidget()
        if parent: parent.updateGeometry()
        self.window.layout().invalidate()
        self.window.layout().activate()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            left, center, right = self.parts
            required = center.minimumSizeHint().width() + 2 * max(left.minimumSizeHint().width(), right.minimumSizeHint().width()) + 48
            parent = self.strip.parentWidget()
            floating = parent and parent.inherits('QDockWidget') and parent.isFloating()
            available = self.strip.width() if floating else self.window.width() - 24
            compact = available < required
            if compact != self.compact:
                self.compact = compact
                layout = self.strip.layout()
                for part in self.parts: layout.removeWidget(part)
                for column in (0, 2): layout.setColumnMinimumWidth(column, 0 if compact else 140)
                if compact:
                    layout.addWidget(center, 0, 0, 1, 3, Qt.AlignmentFlag.AlignCenter)
                    layout.addWidget(left, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
                    layout.addWidget(right, 1, 2, Qt.AlignmentFlag.AlignRight)
                else:
                    for column, part in enumerate(self.parts): layout.addWidget(part, 0, column, Qt.AlignmentFlag.AlignVCenter)
                self.strip.setFixedHeight(76 if compact else 42)
                parent = self.strip.parentWidget()
                if parent and parent.inherits('QDockWidget'):
                    parent.setMinimumHeight(0); parent.setMaximumHeight(16777215)
                    parent.setFixedHeight(parent.sizeHint().height())
                self.relayout.start(0)
        return False
