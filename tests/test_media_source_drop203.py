# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMenu

from model import Document, locate
from test_drawing import application, window
from test_tracks1170 import media


def test_menu_appends_only_to_named_track_even_with_both_selected(window):
    w = window
    first = w.doc.active_track_id
    w.add_media_track()
    second = w.doc.active_track_id
    w.doc.select_track(first, extend=True)
    w.refresh()
    w.media_list.item(0).setSelected(True)
    before = w.doc.state
    menu = QMenu()
    actions = w.media_source_drops.track_menu(menu).actions()
    assert len(actions) == 2 and actions[1].isEnabled()
    actions[1].trigger()
    tracks = w.doc.state.tracks
    assert tracks[0] == before.tracks[0]
    assert tracks[1].length == 30 and locate(tracks[1].audio, 0) == ('a', 0)
    assert w.doc.selected_track_ids == (second,)
    assert w.doc.undo() and w.doc.state == before


def test_native_drop_pads_empty_target_and_leaves_source_intact(window):
    w = window
    w.add_media_track()
    timeline = w.timeline
    timeline.simple = False
    w.refresh()
    sources = w.media_list
    item = sources.item(0)
    data = sources.mimeData([item])
    class Enter(QDragEnterEvent):
        def source(self):
            return sources
    class Drop(QDropEvent):
        def source(self):
            return sources

    y = list(timeline.media_rows())[1][1] + 10
    point = QPointF(timeline.x_for(12), y)
    flags = Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier
    entry = Enter(point.toPoint(), *flags)
    QApplication.sendEvent(timeline, entry)
    assert entry.isAccepted() and not w.media_source_drops.line.isHidden()
    event = Drop(point, *flags)
    QApplication.sendEvent(timeline, event)
    assert event.isAccepted() and w.media_source_drops.line.isHidden()
    source, target = w.doc.state.tracks
    assert source.length == 30 and locate(source.segments, 0) == ('a', 0)
    assert target.length == 42 and locate(target.segments, 11)[0] is None
    assert locate(target.segments, 12) == locate(target.audio, 12) == ('a', 0)
    assert w.media_list.count() == 1


def test_batch_source_order_audio_only_and_undo():
    doc = Document()
    doc.append_media([media('video', 5), dict(media('sound', 3), has_video=False)])
    doc.add_media_track()
    empty = doc.active_track_id
    before = doc.state
    assert doc.add_sources_to_track(empty, ['sound', 'video'])
    track = doc.active_track
    assert track.length == 8 and locate(track.segments, 0)[0] is None
    assert locate(track.audio, 0) == ('sound', 0)
    assert locate(track.segments, 3) == ('video', 0)
    assert not doc.add_sources_to_track(empty, ['missing', 'sound'])
    assert doc.undo() and doc.state == before
