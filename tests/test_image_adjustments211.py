# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import av
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from drawing import DrawingKey, Mark
from media import export_video
from model import Document
from test_drawing import application, window
from test_render1170 import clips, document


def test_clicks_restore_independent_values_and_project_roundtrip(window, tmp_path):
    w = window
    w.workspaces.switch('edit')
    w.set_exposure(1.5)
    w.drawing.gamma.setValue(-4)
    QTest.mouseClick(w.exposure_button, Qt.LeftButton)
    QTest.mouseClick(w.drawing.gamma_button, Qt.LeftButton)
    assert (w.exp_spin.value(), w.drawing.gamma.value(), w.viewer.preview_gamma) == (0, 0, 0)
    path = tmp_path / 'bypassed.cadence'
    w.doc.save(path)
    loaded = Document.load(path)
    assert loaded.state == w.doc.state and loaded.to_data()['version'] == 20
    w.install_doc(loaded)
    QTest.mouseClick(w.drawing.gamma_button, Qt.LeftButton)
    assert (w.viewer.preview_gamma, w.exp_spin.value()) == (-4, 0)
    QTest.mouseClick(w.exposure_button, Qt.LeftButton)
    assert (w.exp_spin.value(), w.doc.state.exposure) == (1.5, 1.5)
    w.undo()
    assert w.doc.state.exposure == 0 and not w.exposure_button.isChecked()
    w.set_exposure(.75)
    assert w.exposure_button.isChecked() and not w.doc.state.bypassed_exposures


def test_bypassed_exposures_follow_tracks_and_survive_undo(clips):
    doc = document(clips)
    a, b = (t.info.id for t in doc.state.tracks)
    doc.select_track(a)
    doc.exposure(2.)
    doc.select_track(b)
    doc.exposure(-1.)
    doc.select_track(a, extend=True)
    doc.exposure(enabled=False)
    assert [t.exposure for t in doc.state.tracks] == [0, 0]
    assert dict(doc.state.bypassed_exposures) == {a: 2., b: -1.}
    doc.reorder_media_track(a, 1)
    doc.select_track(a)
    doc.select_track(b, extend=True)
    doc.exposure(enabled=True)
    assert {t.info.id:t.exposure for t in doc.state.tracks} == {a: 2., b: -1.}
    assert doc.undo() and len(doc.state.bypassed_exposures) == 2


def test_exposure_then_mask_matches_encoded_frame_and_recovery(clips, tmp_path):
    import json
    from native_render import preview_levels
    from session import write_snapshot

    doc = Document()
    doc.append_media([clips[0]])
    doc.exposure(-2.)
    doc.commit('Gamma', replace(doc.state, gamma=5.))
    path = tmp_path / 'sample.mp4'
    export_video(doc.state, doc.media, doc.fps, path)
    with av.open(clips[0]['path']) as source, av.open(str(path)) as output:
        before = next(source.decode(video=0)).to_ndarray(format='rgb24')[12,12]
        after = next(output.decode(video=0)).to_ndarray(format='rgb24')[12,12]
    expected = preview_levels(-2,5)[before]
    assert np.max(np.abs(after.astype(int)-expected)) <= 4
    doc.exposure(enabled=False)
    recovery = tmp_path / 'session.json'
    write_snapshot(recovery, (doc.state,doc.media,doc.fps,{},None,True), {})
    record = json.loads(recovery.read_text(encoding='utf-8'))['document']
    assert record['version'] == 20 and Document.from_data(record).state == doc.state


@pytest.mark.parametrize('ext,gamma,enabled,two_tracks,expected', [
    ('mp4', 10, True, False, (255,255,255)),
    ('gif', -10, True, True, (0,0,0)),
    ('mov', 5, True, True, (254,128,128)),
    ('mp4', 5, False, False, (253,0,0)),
])
def test_exported_mask_under_drawings(application, clips, tmp_path, ext, gamma, enabled, two_tracks, expected):
    doc = document(clips) if two_tracks else Document()
    if not two_tracks: doc.append_media([clips[0]])
    mark = Mark(points=((.5,.5,1.),), size=.25, color='#00ff00', pressure=False)
    state = replace(doc.state, gamma=gamma, gamma_enabled=enabled, drawings=(DrawingKey(0,1,(mark,)),))
    path = tmp_path / ('render.' + ext)
    export_video(state, doc.media, doc.fps, path)
    with av.open(str(path)) as container:
        frame = next(container.decode(video=0)).to_ndarray(format='rgb24').astype(int)
    assert np.max(np.abs(frame[8,8] - expected)) <= 5
    assert np.max(np.abs(frame[frame.shape[0]//2,frame.shape[1]//2] - (0,255,0))) <= 8
