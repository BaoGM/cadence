# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from model import Document, Segment, State, locate, with_tracks
from test_drawing import application, window
from test_render1170 import clips, document
from test_timeline200 import move_pointer, timeline
from widgets import Timeline
import timeline_skin


@pytest.mark.parametrize('width,length,last_tick', [(640, 1000, 1000), (1920, 1212, 1200)])
def test_four_digit_graduation_visible_at_end(timeline, monkeypatch, width, length, last_tick):
    widget, _ = timeline
    widget.resize(width, widget.height())
    widget.set_document(State((Segment('a', 0, length),)), {}, 24)
    widget.set_units('frames')
    labels = {}
    original = timeline_skin.label

    def record(painter, area, text, *args, **kwargs):
        original(painter, area, text, *args, **kwargs)
        if text.isdecimal():
            labels[text] = area, painter.fontMetrics().horizontalAdvance(text)

    monkeypatch.setattr(timeline_skin, 'label', record)
    widget.grab()
    area, natural_width = labels[str(last_tick)]
    assert area.width() >= natural_width
    assert abs(area.center().x()-widget.x_for(last_tick))<=1 and area.right()<widget.width()
    assert widget.frame_for(widget.track_right()) == length - 1


def test_read_headers_and_transport_keep_hover(window, application, clips):
    w = window
    doc = Document()
    doc.append_media([clips[0]])
    w.install_doc(doc)
    w.workspaces.switch('read')
    w.workspaces.set_timeline_simple(True)
    w.transport_widget.show()
    w.resize(1280, 800)
    application.processEvents()
    headers = w.studio.headers
    first, second, bar = headers.geometries()
    away = w.viewer.mapToGlobal(w.viewer.rect().center())
    headers.update_hover(away)
    assert not headers.top.isVisible() and not headers.ruler.isVisible()
    headers.update_hover(first.center())
    assert headers.top.isVisible() and headers.view.isVisible()
    headers.update_hover(second.center())
    assert headers.top.isVisible() and headers.view.isVisible()

    play = w.play_btn.mapToGlobal(w.play_btn.rect().center())
    assert not bar.contains(play)
    timeline = w.timeline.mapToGlobal(w.timeline.rect().center())
    for point in (timeline, play, bar.center()):
        headers.update_hover(away)
        headers.update_hover(point)
        assert headers.ruler.isVisible()
    QTest.mouseClick(w.play_btn, Qt.LeftButton)
    headers.update_hover(play)
    assert headers.ruler.isVisible() and w.transport.running
    QTest.mouseClick(w.play_btn, Qt.LeftButton)
    headers.update_hover(away)
    assert not headers.ruler.isVisible()
    w.transport_widget.hide()
    application.processEvents()
    bar = headers.geometries()[2]
    headers.update_hover(QPoint(bar.center().x(), bar.top() - 8))
    assert headers.ruler.isVisible()


@pytest.mark.parametrize('outcome', ['move', 'offset', 'copy', 'escape', 'outside'])
def test_alt_drop_to_empty_track(application, outcome):
    doc = Document()
    doc.state = State((Segment('a', 0, 48),))
    first = doc.active_track.info.id
    doc.add_media_track()
    second = doc.active_track.info.id
    original = doc.state
    timeline = Timeline()
    timeline.resize(960, timeline.height())

    def refresh():
        timeline.active_media_id = doc.active_track_id
        timeline.selected_media_ids = doc.selected_track_ids
        timeline.set_document(doc.state, {}, 24)

    def select(identity, mode):
        doc.select_track(identity)
        refresh()

    def transfer(*args):
        assert doc.transfer_media(*args)
        refresh()

    timeline.mediaTrackSelected.connect(select)
    timeline.mediaTransferred.connect(transfer)
    refresh()
    timeline.show()
    application.processEvents()
    try:
        assert doc.selected_track_ids == (second,)
        upper, lower = (y + 9 for _, y, _ in timeline.media_rows())
        start = QPoint(round(timeline.x_for(12)), upper)
        offset = 8 if outcome == 'offset' else 0
        end = QPoint(round(timeline.x_for(12 + offset)), lower)
        keys = Qt.AltModifier | Qt.ShiftModifier if outcome == 'copy' else Qt.AltModifier
        QTest.mousePress(timeline, Qt.LeftButton, keys, start)
        move_pointer(timeline, end, keys)
        assert timeline.cross_target == second and timeline.drop_frame == offset
        assert timeline.clip_preview.phase == 'lift' and doc.state == original
        if outcome == 'escape':
            QTest.keyClick(timeline, Qt.Key_Escape)
        if outcome == 'outside':
            end.setY(-5)
        QTest.mouseRelease(timeline, Qt.LeftButton, keys, end)
        if outcome in ('outside', 'escape'):
            assert doc.state == original and timeline.clip_preview.phase is None
            return
        source, target = doc.state.tracks
        assert source.info.id == first and target.info.id == second
        assert source.length == (48 if outcome == 'copy' else 0)
        assert target.length == offset + 48 and doc.active_track_id == second
        assert doc.selected_track_ids == (second,)
        assert locate(target.segments, offset) == locate(target.audio, offset) == ('a', 0)
        assert timeline.clip_preview.phase == 'land'
        assert doc.undo() and doc.state == original
    finally:
        timeline.close()
        timeline.deleteLater()


def test_drag_between_tracks_in_either_direction(window, application, clips):
    w = window
    w.resize(1000, 720)
    t = w.timeline
    for simple in (False, True):
        w.workspaces.set_timeline_simple(simple)
        for source_index in (0, 1):
            for occupied in (False, True):
                doc = document(clips)
                tracks = list(doc.state.tracks)
                source, target = tracks[source_index], tracks[1 - source_index]
                if not occupied:
                    target = replace(target, segments=(), audio_segments=())
                    tracks[1 - source_index] = target
                    doc.state = with_tracks(doc.state, tracks)
                doc.select_track(source.info.id if simple else target.info.id)
                w.install_doc(doc)
                application.processEvents()
                x = round(t.x_for(12))
                if simple:
                    start = QPoint(x, 39)
                    end = QPoint(t.track_left() // 2, 39)
                    keys = Qt.AltModifier
                else:
                    rows = list(t.media_rows())
                    start = QPoint(x, rows[source_index][1] + 8)
                    end = QPoint(x, rows[1 - source_index][1] + 8)
                    keys = Qt.AltModifier
                QTest.mousePress(t, Qt.LeftButton, keys, start)
                move_pointer(t, end, keys)
                assert t.cross_target == target.info.id and t.drop_frame == 0
                QTest.mouseRelease(t, Qt.LeftButton, keys, end)
                result = doc.state.tracks[1 - source_index]
                assert result.info.id == target.info.id and result.length == source.length + target.length
                assert doc.active_track_id == result.info.id and doc.state.tracks[source_index].length == 0
                assert locate(result.segments, 0) == locate(source.segments, 0)
                assert locate(result.audio, 0) == locate(source.audio, 0)
                if occupied:
                    assert locate(result.segments, source.length) == locate(target.segments, 0)
                assert doc.undo() and doc.state.tracks == tuple(tracks)
