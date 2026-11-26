# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget,QToolBar
from test_drawing import application,window
from workspace_modes import encoded


def assert_full_width_playback(w,application):
    application.processEvents()
    assert w.timeline_panel.x()==0 and w.timeline_panel.width()==w.width()
    transport=w.transport_widget
    assert transport.x()==0 and transport.width()==w.viewer_workspace.width()
    if w.edit_toolbar.isVisible(): assert w.edit_toolbar.geometry().bottom()<transport.y()
    assert w.viewer_workspace.geometry().bottom()<w.timeline_panel.y()


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
    comparison=QDockWidget(w); comparison.setObjectName('comparison')
    w.addDockWidget(Qt.LeftDockWidgetArea,comparison)
    w.removeDockWidget(tools); tools.hide()
    legacy=QToolBar(w); legacy.setObjectName('edit_toolbar')
    w.addToolBar(Qt.ToolBarArea.LeftToolBarArea,legacy)
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,w.library)
    w.splitDockWidget(w.library,comparison,Qt.Orientation.Vertical)
    application.processEvents()
    modes.layouts['edit']=encoded(w.saveState()); modes.layout_versions.pop('edit',None)
    w.removeDockWidget(comparison); comparison.setObjectName(''); comparison.deleteLater()
    w.removeToolBar(legacy); legacy.setObjectName('discarded_toolbar'); legacy.deleteLater()
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,tools)
    modes.apply('edit')
    assert_full_width_playback(w,application)
    assert w.library.geometry().right()<tools.mapTo(w,tools.rect().topLeft()).x()
    assert w.dockWidgetArea(w.library)==Qt.LeftDockWidgetArea
    assert 'comparison' not in modes.panels
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


def test_resize_both_studio_sidebars_with_layout_locked(window,application):
    w=window
    w.drawing.panel.show()
    for width,height in ((1440,840),(1000,620)):
        w.resize(width,height)
        QTest.qWait(60)
        for panel,side in ((w.library,1),(w.drawing.panel,-1)):
            before=panel.width()
            workspace=w.viewer_workspace.geometry()
            x=(panel.geometry().right()+workspace.left())//2 if side==1 else (panel.x()+workspace.right())//2
            handle=QPoint(x,panel.geometry().center().y())
            target=handle+QPoint(side*40,0)
            QTest.mousePress(w,Qt.LeftButton,pos=handle)
            QTest.mouseMove(w,target,15)
            QTest.qWait(40)
            QTest.mouseRelease(w,Qt.LeftButton,pos=target)
            application.processEvents()
            assert panel.width()>=before+30
            assert not w.layout_editable
