# SPDX-License-Identifier: GPL-3.0-only
from struct import pack, unpack_from

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QToolBar, QWidget, QVBoxLayout


class ViewerWorkspace(QMainWindow):
    def __init__(self, window, viewer):
        super().__init__(window)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName('viewerWorkspace')
        self.setDockNestingEnabled(True)
        self.setAnimated(False)
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(viewer)
        self.setCentralWidget(self.content)

    def createPopupMenu(self):
        return self.window().createPopupMenu()


class WorkspaceDockLayout:
    # Independent Qt dock states keep the timeline full width and the transport inside the video workspace.
    _layout_magic = b'CDW2'

    def _viewer_dock(self, dock):
        return hasattr(self, 'viewer_workspace') and dock.objectName() in ('transport_widget', 'edit_tools_panel')

    def addDockWidget(self, area, dock, *args):
        if self._viewer_dock(dock):
            return self.viewer_workspace.addDockWidget(area, dock, *args)
        return super().addDockWidget(area, dock, *args)

    def removeDockWidget(self, dock):
        if self._viewer_dock(dock):
            return self.viewer_workspace.removeDockWidget(dock)
        return super().removeDockWidget(dock)

    def dockWidgetArea(self, dock):
        if self._viewer_dock(dock):
            return self.viewer_workspace.dockWidgetArea(dock)
        return super().dockWidgetArea(dock)

    def saveState(self, version=0):
        outer = super().saveState(version)
        if not hasattr(self, 'viewer_workspace'):
            return outer
        return QByteArray(self._layout_magic + pack('>I', len(outer)) + bytes(outer)
                          + bytes(self.viewer_workspace.saveState(version)))

    def restoreState(self, state, version=0):
        raw = bytes(state)
        if not hasattr(self, 'viewer_workspace'):
            return super().restoreState(state, version)
        if raw.startswith(self._layout_magic):
            if len(raw)<8:
                return False
            boundary = 8 + unpack_from('>I', raw, 4)[0]
            if boundary>=len(raw):
                return False
            restored = super().restoreState(QByteArray(raw[8:boundary]),version)
            return self.viewer_workspace.restoreState(QByteArray(raw[boundary:]),version) and restored
        # Reparenting live docks during restore leaves Qt's Windows layout with stale
        # items when a maximized window is first shown. Split the old state on stand-ins.
        outer = self._legacy_layout_part(state, version, False)
        inner = self._legacy_layout_part(state, version, True)
        if outer.isEmpty() or inner.isEmpty():
            return False
        return super().restoreState(outer, version) and self.viewer_workspace.restoreState(inner, version)

    def _legacy_layout_part(self, state, version, inner):
        staging = QMainWindow()
        staging.setAttribute(Qt.WA_DontShowOnScreen)
        staging.resize(self.size())
        staging.setCentralWidget(QWidget())
        staging.setDockOptions(self.dockOptions())
        discarded = []
        for parent in (self, self.viewer_workspace):
            for dock in parent.findChildren(QDockWidget, options=Qt.FindDirectChildrenOnly):
                replica = QDockWidget(staging)
                replica.setObjectName(dock.objectName())
                replica.setAttribute(Qt.WA_DontShowOnScreen)
                staging.addDockWidget(QMainWindow.dockWidgetArea(parent, dock), replica)
                if (parent is self.viewer_workspace) != inner:
                    discarded.append(replica)
        bars = []
        for bar in self.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly):
            replica = QToolBar(staging)
            replica.setObjectName(bar.objectName())
            staging.addToolBar(self.toolBarArea(bar), replica)
            bars.append(replica)
        if not staging.restoreState(state, version):
            return QByteArray()
        for dock in discarded:
            dock.setObjectName('')
            staging.removeDockWidget(dock)
        if inner:
            for bar in bars:
                staging.removeToolBar(bar)
        return staging.saveState(version)
