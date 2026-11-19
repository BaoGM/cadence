# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from drawing import DrawingKey, Mark
from model import Document


def check(window, output, media):
    doc = Document(); doc.append_media([media])
    original = (DrawingKey(10, 20, (Mark(),)),)
    doc.state = replace(doc.state, drawings=original)
    window.install_doc(doc)
    timeline = window.timeline
    for simple in (True, False):
        timeline.simple = simple; window.refresh(); QApplication.processEvents()
        y = timeline.track_y('drawing')+2
        before = timeline.grab().toImage()
        for kind, frame in ((QEvent.Type.MouseButtonPress, 20), (QEvent.Type.MouseMove, 30)):
            point = QPointF(timeline.x_for(frame), y)
            button = Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton
            QApplication.sendEvent(timeline, QMouseEvent(kind, point, QPointF(timeline.mapToGlobal(point.toPoint())), button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
            assert doc.state.selection is None
        preview = timeline.grab().toImage()
        assert before.copy(0, y-3, before.width(), 7) != preview.copy(0, y-3, preview.width(), 7)
        assert doc.state.drawings == original
        QApplication.sendEvent(timeline, QMouseEvent(QEvent.Type.MouseButtonRelease, point, QPointF(timeline.mapToGlobal(point.toPoint())), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        assert doc.state.drawings[0].end == 30 and doc.state.selection is None
        timeline.grab().save(str(output / ('keys-simple.png' if simple else 'keys-detailed.png')))
        assert doc.undo(); window.refresh()
    doc.add_media_track(); window.refresh()
    link = window.sync3d
    old = link.metadata
    try:
        link.metadata = dict(fps=doc.fps)
        link.check_rate(); link.adapt_current()
    finally:
        link.metadata = old
    window.video_mirror_action.setChecked(True)
    from video_mirror import toggle
    toggle(window, True); QApplication.processEvents()
    mirror = window.video_mirror
    assert mirror.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert mirror.canvas.geometry() == mirror.rect()
    mirror.canvas.setFocus(); mirror.update_controls(QPoint(100, 100))
    assert not mirror.controls.isVisible()
    mirror.grab().save(str(output / 'video-mirror-clean.png'))
    mirror.update_controls(mirror.controls.geometry().center())
    assert mirror.controls.isVisible()
    mirror.grab().save(str(output / 'video-mirror-controls.png'))
    mirror.close_button.click()
    assert not mirror.isVisible() and not window.video_mirror_action.isChecked()
    return dict(key_handle_selection_isolated=True, key_drag_live_preview_both_views=True,
                empty_track_sync_safe=True, frameless_mirror=True, mirror_hover_controls=True)
