# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel

from model import Segment, with_tracks
from test_tracks1170 import two_tracks
from test_render1170 import application, clips, document


@pytest.mark.parametrize('lengths', [(10, 80), (80, 10), (0, 80)])
def test_media_readout_beyond_short_track(application, lengths):
    from app import MainWindow
    doc, first, second = two_tracks(*lengths)
    label = QLabel()
    window = SimpleNamespace(doc=doc, media_info=label)
    try:
        for identity in (first, second):
            doc.select_track(identity)
            for frame in (0, 9, 10, 70, 79, 80):
                MainWindow.update_media_info(window, frame)
                assert label.text()
        tracks = tuple(replace(t, segments=(Segment(None, 0, t.length),)) for t in doc.state.tracks)
        doc.state = with_tracks(doc.state, tracks)
        MainWindow.update_media_info(window, 70)
        assert label.text() != '-'
    finally:
        label.deleteLater()


@pytest.mark.parametrize('simple',[False,True])
def test_empty_timeline_hint_stays_within_row(application,simple):
    from model import State
    from widgets import Timeline
    timeline = Timeline()
    timeline.resize(700, 100)
    timeline.simple=simple
    timeline.set_document(State(), {}, 24)
    image = timeline.grab().toImage()
    top=timeline.media_top()
    left,right=timeline.track_left(),timeline.track_right()
    ink=[(x,y) for y in range(top,image.height()) for x in range(left+1,right)
         if image.pixelColor(x,y).lightness()>80]
    xs,ys=zip(*ink)
    assert min(ys)>top+2 and max(ys)<image.height()-2
    assert abs((min(ys)+max(ys))/2-(top+image.height())/2)<3
    assert abs((min(xs)+max(xs))/2-(left+right)/2)<=timeline.fontMetrics().averageCharWidth()
    timeline.deleteLater()


@pytest.mark.parametrize('span', [(0, 40), (0, 10), (10, 20), (30, 40)])
def test_cross_track_move_removes_source_without_placeholder(span):
    from model import locate
    doc, first, second = two_tracks(40, 20)
    doc.select_track(first, extend=True)
    before = doc.state
    start, end = span
    assert doc.transfer_media(first, second, start, end, 20)
    moved = doc.state
    source, target = moved.tracks
    assert source.length == 40 - (end - start)
    expected = list(range(start)) + list(range(end, 40))
    for segments in (source.segments, source.audio):
        assert all(segment.media is not None for segment in segments)
        assert [locate(segments, i)[1] for i in range(source.length)] == expected
    for i in range(end - start):
        assert locate(target.segments, 20 + i) == locate(target.audio, 20 + i) == ('a', start + i)
    assert doc.undo() and doc.state == before
    assert doc.redo() and doc.state == moved


def test_scrub_and_playback_beyond_short_upper_track(application, clips, tmp_path, monkeypatch):
    import sys
    from app import MainWindow
    from test_sync1120 import pump
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow(); window.show(); errors = []
    window.error = errors.append
    monkeypatch.setattr(sys, 'excepthook', lambda kind, error, traceback: errors.append(str(error)))
    doc = document(clips)
    upper, lower = doc.state.tracks
    upper = replace(upper, segments=(replace(upper.segments[0], end=12),),
                    audio_segments=(replace(upper.audio[0], end=12),))
    doc.state = with_tracks(doc.state, (upper, lower)); doc.select_track(upper.info.id)
    window.install_doc(doc); window.volume.setMuted(True)
    try:
        window.seek(30)
        pump(application, lambda: window.display_frame == 30)
        window.seek(10); window.playback_mode = 'once'; window.toggle_play()
        pump(application, lambda: window.doc.state.position > 24)
        pump(application, lambda: not window.transport.running)
        assert not errors
        window.edit_track_structure(doc.reorder_media_track, lower.info.id, -1)
        window.seek(30); pump(application, lambda: window.display_frame == 30)
        assert not errors
    finally:
        window.doc.saved_signature = window.doc.signature(); window.close(); application.processEvents()
