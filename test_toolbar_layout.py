# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar
from test_drawing import application,window
from workspace_modes import encoded


def assert_full_width_playback(w,application):
    application.processEvents()
    tools=w.edit_toolbar.geometry()
    for panel in (w.transport_widget,w.timeline_panel):
        assert panel.x()==0
        assert panel.width()==w.width()
        if w.edit_toolbar.isVisible(): assert tools.bottom()<panel.y()


def test_tools_leave_bottom_panels_full_width(window,application):
    w=window
    for editable in (False,True,False):
        w.set_layout_editable(editable)
        for width,height in ((1360,890),(1600,1000),(1100,760)):
            w.resize(width,height)
            assert_full_width_playback(w,application)
    w.toolbar_action.trigger()
    assert_full_width_playback(w,application)
    w.toolbar_action.trigger()
    assert_full_width_playback(w,application)
    w.workspaces.switch('read')
    w.toolbar_action.trigger()
    assert_full_width_playback(w,application)
    w.workspaces.switch('edit')
    assert_full_width_playback(w,application)


def test_old_toolbar_layout_migrates_once(window,application):
    w=window; modes=w.workspaces; tools=w.edit_toolbar
    w.removeDockWidget(tools); tools.hide()
    legacy=QToolBar(w); legacy.setObjectName('edit_toolbar')
    w.addToolBar(Qt.ToolBarArea.LeftToolBarArea,legacy)
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,w.library)
    w.splitDockWidget(w.library,w.comparison_panel,Qt.Orientation.Vertical)
    application.processEvents()
    modes.layouts['edit']=encoded(w.saveState()); modes.layout_versions.pop('edit',None)
    w.removeToolBar(legacy); legacy.setObjectName('discarded_toolbar'); legacy.deleteLater()
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,tools)
    modes.apply('edit')
    assert_full_width_playback(w,application)
    assert w.library.x()>tools.x() and w.comparison_panel.x()==w.library.x()
    assert w.library.y()<w.comparison_panel.y()
    assert modes.layout_versions['edit']==2
    modes.capture(); state=modes.layouts['edit']
    modes.switch('read'); modes.switch('edit')
    assert modes.layouts['edit']==state
    assert_full_width_playback(w,application)


def test_tool_panel_position_restores_and_resets(window,application):
    w=window; modes=w.workspaces
    w.set_layout_editable(True)
    w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,w.edit_toolbar)
    modes.capture(); modes.switch('read'); modes.switch('edit')
    assert w.dockWidgetArea(w.edit_toolbar)==Qt.DockWidgetArea.RightDockWidgetArea
    assert_full_width_playback(w,application)
    modes.reset()
    assert w.dockWidgetArea(w.edit_toolbar)==Qt.DockWidgetArea.LeftDockWidgetArea
    assert_full_width_playback(w,application)
