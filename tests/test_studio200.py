# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QSignalSpy, QTest

from test_drawing import application, window


def test_native_menus_modes_timeline_and_clock(window, application):
    w = window
    chrome = w.studio
    assert w.windowTitle().removeprefix('● ').startswith('Cadence 2.0 - ')
    assert chrome.menu.actions() == w.menuBar().actions()
    w.comparison_panel.show()
    chrome.dock_button.click()
    assert w.library.isHidden() and w.comparison_panel.isHidden()
    chrome.dock_button.click()
    assert w.library.isVisible() and w.comparison_panel.isVisible()
    w.drawing.panel.hide()
    chrome.right_button.click()
    assert w.drawing.panel.isVisible()
    chrome.mode_buttons['read'].click()
    assert w.workspaces.mode == 'read' and chrome.mode_buttons['read'].isChecked()
    chrome.views[1].click()
    assert not w.timeline.simple and w.workspaces.mode == 'read'
    chrome.units[1].click()
    assert w.timeline.units == 'frames' and chrome.units[1].isChecked()
    w.seek(12)
    assert '12' in w.timecode_overlay.frame
    assert not hasattr(chrome,'clock')
    chrome.headers.update_hover(QPoint(-100,-100))
    assert not chrome.top.isVisible() and not chrome.view.isVisible()
    first,_=chrome.headers.geometries()
    chrome.headers.update_hover(QPoint(first.center().x(),first.top()+3))
    assert chrome.top.isVisible() and chrome.view.isVisible()
    assert abs(chrome.mode_group.mapToGlobal(chrome.mode_group.rect().center()).x()-w.mapToGlobal(w.rect().center()).x())<=2
    w.toggle_fullscreen()
    assert not chrome.top.isVisible() and not chrome.view.isVisible()
    w.toggle_fullscreen()
    chrome.headers.show_reader()
    assert chrome.top.isVisible() and chrome.view.isVisible()


def test_menu_key_respects_custom_action(window, application):
    w = window
    w.activateWindow()
    w.viewer.setFocus()
    application.processEvents()
    QTest.keyClick(w.viewer, Qt.Key.Key_F10)
    assert w.studio.menu.isVisible()
    w.studio.menu.close()
    key = 'Lecture/Image suivante'
    prefs = {**w.preferences, 'shortcuts':{**w.preferences['shortcuts'], key:'F10'}}
    w.apply_preferences(prefs)
    assert not w.studio.menu_key.isEnabled()
    spy = QSignalSpy(w.action_registry[key][0].triggered)
    w.activateWindow()
    w.viewer.setFocus()
    application.processEvents()
    QTest.keyClick(w.viewer, Qt.Key.Key_F10)
    assert spy.count() == 1 and not w.studio.menu.isVisible()


def test_comparison_buttons_close_panel_when_disabled(window, application):
    w=window
    w.request_frame=lambda:None
    w.studio.compare_button.click()
    assert w.comparison_panel.isVisible() and w.compare_enabled.isChecked()
    w.comparison_panel.hide()
    w.compare_offset.setValue(3)
    assert w.comparison_panel.isHidden()
    w.ref_compare_button.click()
    assert not w.compare_enabled.isChecked()
    w.ref_compare_button.click()
    assert w.compare_enabled.isChecked() and w.comparison_panel.isVisible()
    w.set_reference_sequence([w.doc.media['a']])
    w.studio.compare_button.click()
    assert not w.compare_enabled.isChecked() and w.comparison_panel.isHidden()
    w.ref_compare_button.click()
    assert w.compare_enabled.isChecked() and w.comparison_panel.isHidden()
    w.use_track_reference(w.doc.active_track_id)
    w.comparison_panel.hide()
    w.compare_offset.setValue(4)
    w.studio.compare_button.click()
    w.studio.compare_button.click()
    assert w.viewer.comparing and w.comparison_panel.isHidden()
    w.comparison_panel.setFloating(True)
    w.comparison_panel.show()
    w.comparison_panel.close()
    assert w.viewer.comparing
    w.comparison_panel.show()
    w.compare_action.trigger()
    assert not w.viewer.comparing and w.comparison_panel.isHidden()
    w.compare_action.trigger()
    assert w.viewer.comparing and w.comparison_panel.isHidden()
    w.comparison_panel.show()
    w.toggle_fullscreen()
    w.compare_action.trigger()
    w.compare_action.trigger()
    assert w.video_fullscreen and w.viewer.comparing
    w.toggle_fullscreen()
    assert w.comparison_panel.isHidden()
    w.set_reference_sequence([])
    w.toggle_fullscreen()
    w.compare_action.trigger()
    assert not w.video_fullscreen and w.comparison_panel.isVisible()


def test_sync_button_opens_existing_settings_action(window):
    w=window
    button=w.studio.sync_button
    action=w.action_registry['Synchronisation 3D/Réglages de synchronisation…'][0]
    assert button.defaultAction() is action and not button.icon().isNull()
    button.click()
    assert w.sync3d.dialog.isVisible()
    w.sync3d.dialog.close()


def test_compact_read_headers_preserve_tools_and_timeline(window, application):
    from PySide6.QtCore import QRect
    w=window
    w.workspaces.switch('read')
    w.resize(640,440)
    for dock in (w.library,w.edit_toolbar,w.drawing.panel): dock.show()
    application.processEvents()
    headers=w.studio.headers
    def bounds(widget):
        local=widget.mask().boundingRect() if not widget.mask().isEmpty() else widget.rect()
        return QRect(widget.mapToGlobal(local.topLeft()),local.size())
    headers.update_hover(w.viewer_workspace.content.mapToGlobal(QPoint(6,6)))
    headers.timer.stop()
    application.processEvents()
    for dock in (w.library,w.edit_toolbar,w.drawing.panel):
        assert not bounds(headers.top).intersects(bounds(dock))
    headers.update_hover(w.timeline.mapToGlobal(w.timeline.rect().center()))
    headers.timer.stop()
    application.processEvents()
    assert w.studio.timeline_bar.isVisible()
    assert not bounds(w.studio.timeline_bar).intersects(bounds(w.timeline))


def test_reader_panels_slide_in_their_own_direction(window, application):
    w=window
    w.workspaces.switch('read')
    w.resize(1280,800)
    c=w.studio
    w.library.hide()
    w.drawing.panel.hide()
    w.viewer.setFocus()
    application.processEvents()
    c.headers.update_hover(QPoint(-100,-100))
    c.headers.show_reader()
    c.headers.timer.stop()
    focus=application.focusWidget()
    def check(widget,offset):
        motion=widget.entrance
        assert motion.offset==offset and widget.pos()==motion.origin+offset
        motion.setCurrentTime(motion.duration()//2)
        assert widget.pos()!=motion.origin and widget.pos()!=motion.origin+offset
        motion.setCurrentTime(motion.duration())
        assert widget.pos()==motion.origin and widget.entrance is None
    check(c.top,QPoint(0,-18))
    assert c.view.window() is c.top.window()
    c.headers.show_ruler()
    check(c.timeline_bar,QPoint(0,18))
    c.dock_button.click()
    check(w.library.widget(),QPoint(-20,0))
    c.right_button.click()
    check(w.drawing.panel.widget(),QPoint(20,0))
    assert application.focusWidget() is focus


def test_read_header_is_one_row_and_timeline_enter_needs_no_poll(window,application):
    from PySide6.QtCore import QCoreApplication,QPointF,QRect
    from PySide6.QtGui import QEnterEvent
    w=window
    w.workspaces.switch('read')
    c=w.studio
    for width,height in ((1280,800),(640,400)):
        w.resize(width,height)
        application.processEvents()
        c.headers.show_reader()
        if motion:=getattr(c.top,'entrance',None): motion.setCurrentTime(motion.duration())
        controls=[c.menu_button,c.dock_button,c.language_button,*c.mode_buttons.values(),c.compare_button,
                  c.sync_button,c.right_button,c.options_button]
        rectangles=[QRect(b.mapToGlobal(QPoint()),b.size()) for b in controls]
        for i,(button,rect) in enumerate(zip(controls,rectangles)):
            assert button.isVisible() and button.window() is c.headers.top
            assert abs(rect.center().y()-c.headers.top.geometry().center().y())<=2
            assert c.headers.top.geometry().contains(rect)
            for previous,other in zip(controls[:i],rectangles[:i]):
                assert not rect.intersects(other), str((width,c.top.geometry().getRect(),c.view.geometry().getRect(),
                    [(b.text(),b.mapTo(c.top,QPoint()).x(),b.width()) for b in controls]))
    for simple in (True,False):
        w.workspaces.set_timeline_simple(simple)
        application.processEvents()
        away=w.viewer.mapToGlobal(w.viewer.rect().center())
        c.headers.update_hover(away)
        c.headers.timer.stop()
        assert not c.timeline_bar.isVisible()
        visible=QRect(w.timeline_panel.mapToGlobal(QPoint()),w.timeline_panel.size())
        cursor=visible.intersected(QRect(w.timeline.mapToGlobal(QPoint()),w.timeline.size())).center()
        here=w.timeline.mapFromGlobal(cursor)
        event=QEnterEvent(QPointF(here),QPointF(w.mapFromGlobal(cursor)),QPointF(cursor))
        QCoreApplication.sendEvent(w.timeline,event)
        assert c.timeline_bar.isVisible()
        c.headers.update_hover(c.timeline_bar.mapToGlobal(c.timeline_bar.rect().center()))
        assert c.timeline_bar.isVisible()
        c.headers.update_hover(away)
        assert not c.timeline_bar.isVisible()
