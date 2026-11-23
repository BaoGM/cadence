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
    first,second,_=chrome.headers.geometries()
    chrome.headers.update_hover(QPoint(second.center().x(),first.top()+3))
    assert chrome.top.isVisible() and chrome.view.isVisible()
    assert abs(chrome.mode_group.geometry().center().x()-w.rect().center().x())<=2
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
