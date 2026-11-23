# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from model import Document, Segment


def check(window, output, media=None):
    w = window
    w.workspaces.switch('edit')
    if media is not None:
        doc = Document(); doc.append_media([media])
        doc.state = replace(doc.state, segments=(Segment(media['id'], 0, 30), Segment(media['id'], 40, 70)))
        w.install_doc(doc)
        for simple in (False, True):
            w.timeline.simple = simple; w.refresh(); QApplication.processEvents()
            t = w.timeline
            point = QPoint(round(t.x_for(40)), round(t.simple_track_rect().center().y()) if simple else t.track_y('video')+9)
            QTest.mouseDClick(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            QTest.mouseRelease(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            assert doc.state.selection == (30, 60)
            t.grab().save(str(output/f'double-click-clip-{simple}.png'))
            if not simple:
                point = QPoint(40, t.track_y('video')+9)
                QTest.mouseDClick(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, point)
                QTest.mouseRelease(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, point)
                assert doc.state.selection == (0, 60)
                t.grab().save(str(output/'double-click-track.png'))
    w.set_layout_editable(False); w.library.show(); w.comparison_panel.show()
    QApplication.processEvents()
    before = w.library.height()
    point = QPoint(w.library.geometry().center().x(), (w.library.geometry().bottom()+w.comparison_panel.y())//2)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(w, point+QPoint(0, -50), 20); QTest.qWait(60)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=point+QPoint(0, -50))
    assert w.library.height() < before-25
    w.grab().save(str(output/'resized-sidebar.png'))
    w.library.hide(); w.comparison_panel.hide(); w.drawing.panel.hide()
    QApplication.processEvents()
    assert w.edit_toolbar.width() <= 64
    w.set_panel('transport', False); QTest.qWait(40)
    hover = w.hover_transport
    for width, height in ((1360, 890), (640, 400)):
        w.resize(width, height); QTest.qWait(80)
        hover.update_hover(QPoint(-50, -50))
        assert not hover.overlay.isVisible()
        w.grab().save(str(output/f'hover-hidden-{width}.png'))
        hover.update_hover(hover.zone().center())
        assert hover.overlay.isVisible() and hover.toggle.isVisible()
        assert not w.play_btn.isVisible() and not w.volume.isVisible()
        assert hover.overlay.width() < 190 and hover.overlay.height() < 50
        assert hover.overlay.rect().contains(hover.toggle.geometry())
        w.grab().save(str(output/f'hover-visible-{width}.png'))
        assert w.transport_widget.isHidden() and not w.panel_actions['transport'].isChecked()
    w.set_panel('transport', True); QTest.qWait(50)
    assert w.transport_widget.widget() is hover.strip and w.play_btn.isVisible()
    w.resize(1360, 890)
    return dict(whole_track_double_click=media is not None, locked_divider_resize=True,
                narrow_tools=True, hidden_transport_hover=True, hover_controls_centered=True)
