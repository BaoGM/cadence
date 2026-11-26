# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import Qt, QPoint, QDeadlineTimer
from PySide6.QtTest import QSignalSpy, QTest

from test_drawing import application, window


def finish_hide(widget):
    motion=getattr(widget,'entrance',None)
    if motion and motion.on_hidden is not None:
        motion.setCurrentTime(0)


def test_native_menus_modes_timeline_and_clock(window, application):
    w = window
    chrome = w.studio
    assert w.windowTitle().removeprefix('● ').startswith('Cadence 2.0 - ')
    assert chrome.menu.actions() == w.menuBar().actions()
    w.show_references()
    chrome.dock_button.click()
    assert w.library.isHidden() and not w.reference_combo.isVisible()
    chrome.dock_button.click()
    assert w.library.isVisible() and w.reference_combo.isVisible()
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
    finish_hide(chrome.top)
    assert not chrome.top.isVisible() and not chrome.view.isVisible()
    first,_=chrome.headers.geometries()
    chrome.headers.update_hover(QPoint(first.center().x(),first.top()+3))
    assert chrome.top.isVisible() and chrome.view.isVisible()
    assert chrome.file_group.isVisible()
    assert chrome.file_menu.isVisible() or all(button.isVisible() for button in chrome.file_buttons)
    chrome.file_buttons[0].defaultAction().trigger()
    assert w.workspaces.mode=='read' and w.doc.state.second_track is not None
    application.processEvents()
    chrome.headers.show_reader()
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


@pytest.mark.parametrize('floating', [False, True], ids=['docked', 'floating'])
def test_edit_controls_and_inspector_toggles(window, application, floating):
    if floating and application.platformName() == 'offscreen':
        pytest.skip('Exercise the detached inspector on a windowing platform')
    w = window
    chrome = w.studio
    assert 'header' not in w.panel_actions
    assert w.drawing.panel.isAncestorOf(w.exp_spin)
    assert chrome.view.isAncestorOf(w.editing_overflow)
    assert chrome.file_menu.menu().actions() == [b.defaultAction() for b in chrome.file_buttons]
    assert all(chrome.top.isAncestorOf(b) for b in chrome.file_buttons)
    w.set_layout_editable(True)
    w.drawing.panel.setFloating(floating)
    w.drawing.panel.hide()
    for index, visible in ((0, True), (1, True), (1, False), (1, True), (0, True), (0, False)):
        chrome.inspector_buttons[index].click()
        application.processEvents()
        assert w.drawing.inspector_tabs.currentIndex() == index
        assert w.drawing.panel.isVisible() == visible
        assert [b.isChecked() for b in chrome.inspector_buttons] == [visible and i == index for i in range(2)]
    w.drawing.panel.setFloating(False)


def test_video_layout_applies_only_settled_sizes(window, application):
    from PySide6.QtCore import QEvent, QObject
    w=window
    class Sizes(QObject):
        def eventFilter(self, obj, event):
            if event.type()==QEvent.Resize: sizes.append(obj.size())
            return False
    probe=Sizes()
    sizes=[]
    w.viewer.installEventFilter(probe)
    w.showMaximized()
    QTest.qWait(180)
    original=w.viewer.size()
    for fullscreen in (True,False):
        sizes.clear()
        w.toggle_fullscreen()
        deadline = QDeadlineTimer(2000)
        while w.viewer.layout_pending and not deadline.hasExpired():
            QTest.qWait(8)
        assert w.video_fullscreen==fullscreen and not w.viewer.layout_pending
        assert sizes and all(size==w.viewer.size() for size in sizes)
    assert w.isMaximized() and w.viewer.size()==original
    sizes.clear()
    w.studio.right_button.click()
    w.studio.right_button.click()
    QTest.qWait(80)
    assert not w.viewer.layout_pending and w.viewer.size()==original
    assert all(size==original for size in sizes)


def test_enabling_comparison_without_b_opens_references_and_disabling_keeps_them(window):
    w=window
    w.request_frame=lambda:None
    w.library_tabs.setCurrentIndex(1)
    w.library.hide()
    w.studio.compare_button.click()
    assert w.reference_combo.isVisible() and w.compare_enabled.isChecked()
    w.studio.compare_button.click()
    assert w.library.isVisible() and w.library_tabs.currentIndex()==w.reference_tab
    assert not w.compare_enabled.isChecked()


@pytest.mark.parametrize('source',['file','track'])
def test_ab_with_a_loaded_source_preserves_left_panel_and_fullscreen(window,application,source):
    w=window
    w.request_frame=lambda:None
    if source=='file':
        w.set_reference_sequence([w.doc.media['a']])
    else:
        w.use_track_reference(w.doc.active_track_id)
    w.show_references()
    w.compare_enabled.click()
    assert w.reference_combo.isVisible() and not w.viewer.comparing
    w.library_tabs.setCurrentIndex(1)
    w.studio.compare_button.click()
    assert w.library.isVisible() and w.library_tabs.currentIndex()==1 and w.viewer.comparing
    w.compare_action.trigger()
    assert w.library.isVisible() and w.library_tabs.currentIndex()==1 and not w.viewer.comparing
    w.library.hide()
    w.compare_cycle_btn.click()
    assert w.library.isHidden() and w.library_tabs.currentIndex()==1 and w.viewer.comparing
    w.compare_action.trigger()
    w.activateWindow()
    w.setFocus()
    application.processEvents()
    QTest.keyClick(w,Qt.Key_X,Qt.ShiftModifier)
    assert w.library.isHidden() and w.library_tabs.currentIndex()==1 and w.viewer.comparing
    w.toggle_fullscreen()
    w.compare_action.trigger()
    w.compare_action.trigger()
    assert w.video_fullscreen and w.library.isHidden() and w.viewer.comparing
    w.toggle_fullscreen()


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
    headers.update_hover(w.play_btn.mapToGlobal(w.play_btn.rect().center()))
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
    finish_hide(c.top)
    finish_hide(c.timeline_bar)
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
    for button,dock,left in ((c.dock_button,w.library,True),(c.right_button,w.drawing.panel,False)):
        initial=w.viewer_workspace.geometry()
        button.click()
        motion=c.side_motion
        motion.pause()
        start,end=motion.paths[dock]
        assert start.right()<0 if left else start.left()>=w.width()
        assert start.width()==end.width()
        motion.setCurrentTime(motion.duration()//2)
        middle=w.viewer_workspace.geometry()
        assert middle.width()<initial.width() and (middle.left()>initial.left())==left
        assert dock.geometry().width()==end.width()
        assert (start.left()<dock.x()<end.left()) if left else (end.left()<dock.x()<start.left())
        button.click()
        assert w.viewer_workspace.geometry()==middle
        assert dock.isHidden()
        closing=motion.previews[dock]
        motion.setCurrentTime(motion.duration()//2)
        assert middle.width()<w.viewer_workspace.width()<initial.width()
        assert closing.isVisible()
        motion.setCurrentTime(motion.duration())
        assert w.viewer_workspace.geometry()==initial and not motion.previews and w.layout().isEnabled()
    assert application.focusWidget() is focus


def test_read_header_is_one_row_and_transport_enter_needs_no_poll(window,application):
    from PySide6.QtCore import QAbstractAnimation,QCoreApplication,QPointF,QRect
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
        finish_hide(c.timeline_bar)
        assert not c.timeline_bar.isVisible()
        track=w.timeline.mapToGlobal(w.timeline.rect().center())
        event=QEnterEvent(QPointF(w.timeline.mapFromGlobal(track)),QPointF(w.mapFromGlobal(track)),QPointF(track))
        QCoreApplication.sendEvent(w.timeline,event)
        assert not c.timeline_bar.isVisible()
        strip=w.transport_widget.widget()
        cursor=strip.mapToGlobal(strip.rect().center())
        event=QEnterEvent(QPointF(strip.mapFromGlobal(cursor)),QPointF(w.mapFromGlobal(cursor)),QPointF(cursor))
        QCoreApplication.sendEvent(strip,event)
        assert c.timeline_bar.isVisible()
        motion=c.timeline_bar.entrance
        motion.setCurrentTime(motion.duration()//2)
        midway=motion.currentTime()
        c.headers.update_hover(track)
        assert motion.direction()==QAbstractAnimation.Backward and motion.currentTime()==midway
        c.headers.update_hover(cursor)
        assert motion.direction()==QAbstractAnimation.Forward and motion.currentTime()==midway
        motion.setCurrentTime(motion.duration())
        c.headers.update_hover(track)
        finish_hide(c.timeline_bar)
        assert not c.timeline_bar.isVisible()
