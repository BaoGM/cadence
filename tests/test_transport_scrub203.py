# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from test_drawing import application, window


def test_transport_scrubs_relative_to_playhead(window, application):
    w = window
    bar = w.compact_transport.strip
    start = QPoint(10, bar.height() // 2)
    delta = QPoint(round(w.viewer.scrub_pixels * 6), 0)
    w.seek(10)
    QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(bar, start + delta)
    assert w.timeline.external_scrubbing and w.doc.state.position == 16
    QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, start + delta)
    assert not w.timeline.external_scrubbing and not w.transport.running
    QTest.mousePress(bar, Qt.LeftButton, Qt.ShiftModifier, start)
    QTest.mouseRelease(bar, Qt.LeftButton, Qt.ShiftModifier, start + delta)
    assert w.doc.state.position == 18
    QTest.mouseClick(w.next_frame_btn, Qt.LeftButton)
    assert w.doc.state.position == 19 and w.compact_transport.scrub_owner is None


def test_transport_resumes_and_cleans_up_interrupted_scrub(window, application, monkeypatch, tmp_path):
    w = window
    bar = w.compact_transport.strip
    start = QPoint(10, bar.height() // 2)
    audio = tmp_path / 'silence.pcm'
    audio.write_bytes(bytes(30 * 2000 * 4))
    w.doc.media['a']['audio'] = str(audio)
    monkeypatch.setattr(w, 'request_frame', lambda: None)
    w.seek(6)
    w.toggle_play()
    assert w.transport.running
    QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(bar, start + QPoint(round(w.viewer.scrub_pixels * 3), 0))
    assert w.timeline.external_scrubbing and not w.transport.running
    application.sendEvent(bar, QEvent(QEvent.WindowDeactivate))
    assert not w.timeline.external_scrubbing and w.transport.running
    QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, start)
    w.pause()
