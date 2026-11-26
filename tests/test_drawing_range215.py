# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtTest import QTest

from test_drawing import application, screen_point, window
from test_tools0160 import mouse


@pytest.mark.parametrize('mode', ['read', 'edit'])
@pytest.mark.parametrize('lane', ['video', 'drawing'])
def test_resize_after_drawing_on_shift_range(window, application, mode, lane):
    w = window
    w.request_frame = lambda: None
    w.workspaces.switch(mode)
    application.processEvents()
    t = w.timeline
    y = t.track_y('drawing') + 2
    media_y = t.simple_track_rect().center().y() if t.simple else t.track_y('video') + 10
    select_y = media_y if lane == 'video' else y

    def point(frame, height):
        return QPointF(t.x_for(frame), height)

    shift = Qt.KeyboardModifier.ShiftModifier
    mouse(t, QEvent.Type.MouseButtonPress, point(2.25, select_y), shift)
    mouse(t, QEvent.Type.MouseMove, point(10.25, select_y), shift)
    mouse(t, QEvent.Type.MouseButtonRelease, point(10.25, select_y), shift)
    assert t.selection_track == lane and w.doc.state.selection == (2, 11)

    d = w.drawing
    d.choose_tool('brush')
    application.processEvents()
    d.begin(screen_point(d, .2, .3), 1)
    d.move(screen_point(d, .5, .3), 1)
    d.finish()
    original = w.doc.state
    assert [(k.start, k.end) for k in original.drawings] == [(2, 11)]
    inside = round(t.x_for(8.45))
    outside = round(t.x_for(14.45))
    def clear_at_old_end():
        image = t.grab().toImage()
        assert image.pixelColor(inside, y) == image.pixelColor(outside, y)

    mouse(t, QEvent.Type.MouseButtonPress, point(11, y))
    mouse(t, QEvent.Type.MouseMove, point(6, y))
    assert t.drawing_track.preview[0].end == 6
    clear_at_old_end()
    QTest.keyClick(t, Qt.Key.Key_Escape)
    assert w.doc.state == original and t.selection_track == lane
    mouse(t, QEvent.Type.MouseButtonRelease, point(6, y))

    mouse(t, QEvent.Type.MouseButtonPress, point(11, y))
    mouse(t, QEvent.Type.MouseMove, point(6, y))
    mouse(t, QEvent.Type.MouseButtonRelease, point(6, y))
    assert w.doc.state.drawings[0].end == 6
    assert t.selection_track == lane
    assert w.doc.state.selection == ((2, 6) if lane == 'drawing' else (2, 11))
    clear_at_old_end()
    w.undo()
    assert w.doc.state == original
    w.redo()
    clear_at_old_end()
