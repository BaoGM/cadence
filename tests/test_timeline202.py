# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QToolButton

from drawing import DrawingKey, Mark
from test_timeline200 import application, timeline
from timeline_skin import marker_areas, marker_at, marker_label


def move(widget,point,modifiers=Qt.NoModifier):
    app=QApplication.instance()
    app.sendEvent(widget,QMouseEvent(QEvent.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),
                                    Qt.NoButton,Qt.LeftButton,modifiers))


@pytest.mark.parametrize('duration',[1,10])
def test_key_body_drags_without_modifier(timeline,duration):
    t,doc=timeline
    doc.state=replace(doc.state,drawings=(DrawingKey(14,14+duration,(Mark(),)),DrawingKey(60,64,(Mark(),))))
    def refresh():
        t.set_document(doc.state,doc.media,24)
    t.drawingMoved.connect(lambda *args:(doc.move_drawings(*args),refresh()))
    refresh()
    original=doc.state
    start=QPoint(round(t.x_for(14+duration/2)),t.track_y('drawing')+2)
    end=start+QPoint(round(t.x_for(29)-t.x_for(14)),0)
    QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,start)
    move(t,end)
    assert t.drawing_track.preview[0].start==29 and doc.state==original
    QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,end)
    assert doc.state.drawings[0]==DrawingKey(29,29+duration,original.drawings[0].marks)
    assert doc.state.drawings[1]==original.drawings[1] and doc.undo() and doc.state==original


def test_marker_move_cancel_collision_and_history(timeline):
    t,doc=timeline
    doc.state=replace(doc.state,frame_markers=(24,70),marker_names=((24,'Impact'),))
    def refresh():
        t.set_document(doc.state,doc.media,24)
    t.markerMoved.connect(lambda *args:(doc.move_marker(*args),refresh()))
    refresh();original=doc.state
    areas=list(marker_areas(t))
    assert marker_label(t,1,70)==''
    assert abs(areas[0][2].center().y()-(t.simple_track_rect().center().y() if t.simple else 10.5))<1
    start=areas[0][2].center().toPoint()
    assert marker_at(t,start)==(24,'Impact')
    def drag(to):
        end=start+QPoint(round(t.x_for(to)-t.x_for(24)),0)
        QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,start);move(t,end)
        return end
    end=drag(70)
    assert t.marker_drag.destination==70 and not t.marker_drag.valid()
    QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,end)
    assert doc.state==original and not doc.undo_stack
    drag(36);QTest.keyClick(t,Qt.Key_Escape)
    assert t.marker_drag.source is None and not doc.undo_stack
    end=drag(36)
    assert doc.state==original
    QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,end)
    assert doc.state.frame_markers==(36,70) and doc.state.marker_names==((36,'Impact'),)
    assert doc.undo() and doc.state==original and doc.redo() and doc.state.marker_names==((36,'Impact'),)


def test_passive_header_scrub_and_controls(timeline):
    t,doc=timeline
    band=QFrame()
    layout=QHBoxLayout(band)
    label=QLabel('Timeline');button=QToolButton();button.setText('s')
    layout.addWidget(label); layout.addStretch(); layout.addWidget(button)
    band.resize(t.width(),36)
    band.show()
    t.install_scrub_band(band)
    started,ended,positions,clicked=[],[],[],[]
    t.scrubStarted.connect(lambda:started.append(True))
    t.scrubFinished.connect(lambda:ended.append(True))
    t.seek.connect(positions.append)
    button.clicked.connect(lambda:clicked.append(True))
    def point(frame):
        return QPoint(band.mapFromGlobal(t.mapToGlobal(QPoint(round(t.x_for(frame+.4)),0))).x(),18)
    try:
        QTest.mousePress(band,Qt.LeftButton,Qt.NoModifier,point(25))
        move(band,point(52))
        QTest.mouseRelease(band,Qt.LeftButton,Qt.NoModifier,point(52))
        assert positions==[25,52] and started==ended==[True]
        QTest.mouseClick(button,Qt.LeftButton)
        assert clicked==[True] and positions==[25,52]
        QTest.mouseClick(label,Qt.LeftButton)
        assert len(started)==len(ended)==2
    finally:
        band.close()


def test_discontinuous_selection_duration_counts_each_frame_once(timeline):
    t,doc=timeline
    t.state=replace(doc.state,selection=(2,33),selected_clips=(('a',2,12),('b',4,9),('a',21,33)))
    assert t.selection_label()=='22 images · 00:00:00:22'


def test_clip_names_and_drawing_selection_in_each_view(timeline,monkeypatch):
    import timeline_skin

    t, doc = timeline
    t.selection_track = 'drawing'
    t.state = replace(doc.state, selection=(5, 11))
    labels = []
    original = timeline_skin.label
    def collect(p, area, text, *args, **kwargs):
        labels.append(text)
        original(p, area, text, *args, **kwargs)
    monkeypatch.setattr(timeline_skin, 'label', collect)
    image = t.grab().toImage()
    assert set(name for name in labels if name.endswith('.mov')) == (set() if t.simple else {m['name'] for m in doc.media.values()})
    x, y = round(t.x_for(8)), t.track_y('drawing')+2
    assert image.pixelColor(x, y).green() - image.pixelColor(round(t.x_for(12)), y).green() >= 40
