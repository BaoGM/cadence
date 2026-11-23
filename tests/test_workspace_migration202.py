# SPDX-License-Identifier: GPL-3.0-only
from struct import unpack_from

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QToolBar, QWidget

from test_drawing import application


def test_restore_maximized_legacy_layout_without_reparenting_live_docks(application, tmp_path, monkeypatch):
    from app import MainWindow

    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path/'prefs.json'))
    legacy = QMainWindow()
    legacy.setDockNestingEnabled(True)
    legacy.setCentralWidget(QWidget())
    for name, area in (
        ('header', Qt.TopDockWidgetArea), ('draw_over', Qt.RightDockWidgetArea),
        ('comparison', Qt.LeftDockWidgetArea), ('library', Qt.LeftDockWidgetArea),
        ('timeline_panel', Qt.BottomDockWidgetArea), ('transport_widget', Qt.BottomDockWidgetArea),
        ('edit_tools_panel', Qt.RightDockWidgetArea),
    ):
        dock = QDockWidget(legacy)
        dock.setObjectName(name)
        legacy.addDockWidget(area, dock)
    toolbar = QToolBar(legacy)
    toolbar.setObjectName('studioTopBar')
    legacy.addToolBar(Qt.TopToolBarArea, toolbar)
    legacy.showMaximized()
    application.processEvents()
    geometry, state = legacy.saveGeometry(), legacy.saveState()
    legacy.close()

    class ParentChanges(QObject):
        def __init__(self):
            super().__init__()
            self.names = []

        def eventFilter(self, obj, event):
            if event.type() == QEvent.ParentChange:
                self.names.append(obj.objectName())
            return False

    w = MainWindow()
    guard = ParentChanges()
    for dock in (w.transport_widget, w.edit_toolbar):
        dock.installEventFilter(guard)
    try:
        assert w.restoreGeometry(geometry)
        assert w.restoreState(state)
        w.show()
        application.processEvents()
        assert guard.names == []
        assert w.edit_toolbar.parentWidget() is w.viewer_workspace
        assert w.transport_widget.parentWidget() is w.viewer_workspace
        assert w.dockWidgetArea(w.edit_toolbar) == Qt.RightDockWidgetArea
        assert w.dockWidgetArea(w.transport_widget) == Qt.BottomDockWidgetArea
        assert w.dockWidgetArea(w.comparison_panel) == Qt.LeftDockWidgetArea
        assert w.toolBarArea(w.studio.bar) == Qt.TopToolBarArea
        migrated = w.saveState()
        raw = bytes(migrated)
        boundary = 8 + unpack_from('>I', raw, 4)[0]
        for dock in (w.edit_toolbar, w.transport_widget):
            name = dock.objectName().encode('utf-16be')
            assert name not in raw[8:boundary] and name in raw[boundary:]
        assert w.restoreState(migrated)
        application.processEvents()
        assert guard.names == []
    finally:
        w.close()
        application.processEvents()
