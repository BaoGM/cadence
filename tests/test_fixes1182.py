# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from model import Document, MediaTrack, Segment, State, TrackInfo
from test_drawing import application, window


def test_pending_single_offer_cannot_interrupt_bulk_adaptation(window, application, monkeypatch):
    w = window; link = w.sync3d
    w.doc.media = {key: dict(id=key, path=key, name=key, width=640, height=360, fps='24', original_fps='12', frames=30)
                   for key in ('a', 'b', 'c')}
    w.doc.state = State(tuple(Segment(key, 0, 30) for key in w.doc.media))
    monkeypatch.setattr(type(link), 'enabled', property(lambda self: True))
    link.metadata = dict(fps=Fraction(24))
    questions, jobs = [], []
    def question(*args):
        questions.append(args[2])
        application.processEvents()
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', question)
    monkeypatch.setattr(w, 'begin_task', lambda title, prepare, apply: (jobs.append((prepare, apply)), setattr(w, 'job', True)))
    link.check_rate()
    link.adapt_current(True)
    application.processEvents()
    w.job = None
    assert len(questions) == 1
    assert len(jobs) == 1
    converted = []
    def prepare(path, fps, progress, cancel, quality, cadence):
        converted.append(path)
        return dict(w.doc.media[path], id=path+'-adapted', cadence=cadence)
    monkeypatch.setattr('media.prepare_media', prepare)
    work, apply = jobs[0]
    monkeypatch.setattr(w, 'request_frame', lambda: None)
    apply(work(lambda *a: None, threading.Event()))
    assert set(converted) == {'a', 'b', 'c'}
    for position in (1, 35, 65, 2, 70):
        w.doc.state = replace(w.doc.state, position=position)
        link.check_rate(); application.processEvents()
    assert len(questions) == 1


def test_real_bulk_conversion_survives_cache_save_and_scrubbing(application, tmp_path, monkeypatch):
    from pathlib import Path
    import shutil
    from media import prepare_batch
    from sync3d import TimelineLink
    from test_sync1120 import Window
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path/'prefs.json'))
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path/'cache'))
    paths = []
    for index in range(2):
        path = tmp_path/f'clip-{index}.mp4'
        shutil.copyfile(Path(__file__).resolve().parents[1]/'assets/Demonstration.mp4', path); paths.append(str(path))
    media = prepare_batch(paths, None, lambda *a: None, threading.Event(), quality='480p')
    w = Window(); w.doc = Document(); w.doc.append_media(media)
    w.doc.add_media_track(); w.doc.append_media([media[0]])
    baseline = w.doc.state; original_fps = w.doc.fps
    w.preferences = {'preview_quality': '480p'}
    w.pause = w.commit_exposure = w.refresh = w.request_frame = lambda: None
    w.drawing = SimpleNamespace(finish=lambda: None)
    w.begin_task = lambda title, prepare, apply: apply(prepare(lambda *a: None, threading.Event()))
    link = TimelineLink(w); monkeypatch.setattr(type(link), 'enabled', property(lambda self: True))
    link.metadata = dict(fps=Fraction(30))
    questions = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: questions.append(a[2]) or QMessageBox.StandardButton.Yes)
    try:
        link.adapt_current(True)
        assert [t.length for t in w.doc.state.tracks] == [t.length for t in baseline.tracks]
        assert w.doc.fps == original_fps
        for segment in w.doc.state.all_segments:
            if segment.media: assert w.doc.media[segment.media]['cadence']['rate'] == '30'
        assert w.doc.undo() and w.doc.state == baseline
        assert w.doc.redo()
        path = tmp_path/'converted.cadence'; w.doc.save(path); w.doc = Document.load(path)
        for track in w.doc.state.tracks:
            w.doc.select_track(track.info.id)
            for frame in range(0, track.length, 25):
                w.doc.state = replace(w.doc.state, position=frame)
                link.check_rate(); application.processEvents()
        assert len(questions) == 1
    finally:
        link.stop(); w.close(); w.deleteLater(); application.processEvents()


@pytest.mark.parametrize('simple,title', [(True, False), (False, False), (False, True)])
def test_double_click_selects_clicked_clip_or_track(window, application, simple, title):
    w = window; t = w.timeline; w.request_frame = lambda: None
    second = MediaTrack(TrackInfo('second', 'Piste 2'), (Segment('a', 0, 8), Segment('a', 10, 30)))
    w.doc.state = State((Segment('a', 0, 30), Segment('a', 0, 30)), second_track=second)
    w.doc.select_track('second'); t.simple = simple; w.refresh(); application.processEvents()
    point = QPoint(40 if title else round(t.x_for(13)),
                   round(t.simple_track_rect().center().y()) if simple else t.track_y('video')+9)
    modifier=Qt.ShiftModifier if title else Qt.NoModifier
    QTest.mouseDClick(t, Qt.MouseButton.LeftButton, modifier, point)
    QTest.mouseRelease(t, Qt.MouseButton.LeftButton, modifier, point)
    assert w.doc.state.selection == ((0, 28) if title else (8, 28))
    assert w.doc.selected_track_ids == ('second',)
    assert t.gesture is None and t.media_title_drag is None


@pytest.mark.parametrize('mode', ['read', 'edit'])
def test_locked_sidebar_divider_remains_draggable(window, application, mode):
    w = window; w.workspaces.switch(mode)
    w.show_references(); w.set_layout_editable(False)
    w.resize(1360, 890); application.processEvents()
    before = w.reference_split.sizes()[0]
    handle = w.reference_split.handle(1)
    point = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(handle, point+QPoint(0, -60), 30)
    QTest.qWait(50)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point+QPoint(0, -60))
    application.processEvents()
    assert w.reference_split.sizes()[0] < before-30
    assert not w.layout_editable


def test_tools_remain_narrow_without_sidebar_panels(window, application):
    w = window
    w.library.hide(); application.processEvents()
    assert w.edit_toolbar.width() <= 64
    assert w.centralWidget().x() <= 74
    w.resize(1600, 900); application.processEvents()
    assert w.edit_toolbar.width() <= 64
    w.show_references(); application.processEvents()
    assert w.library.width() >= 180
    assert w.edit_toolbar.width() <= 64


def test_hidden_transport_hover_and_workspace_state(window, application):
    w = window; hover = w.hover_transport
    w.set_panel('transport', False); application.processEvents()
    hover.update_hover(QPoint(-50, -50))
    assert not hover.overlay.isVisible()
    hover.update_hover(hover.zone().center())
    assert hover.overlay.isVisible() and hover.toggle.isVisible()
    assert not w.play_btn.isVisible() and not w.workspaces.toggle.isVisible()
    assert not w.volume.isVisible() and not w.loop_btn.isVisible()
    assert w.transport_widget.isHidden() and not w.panel_actions['transport'].isChecked()
    w.workspaces.capture(); assert not w.workspaces.profiles['edit']['transport']
    hover.update_hover(QPoint(-50, -50))
    assert not hover.overlay.isVisible()
    w.set_panel('transport', True); QTest.qWait(30)
    assert w.transport_widget.widget() is w.compact_transport.strip
    assert w.play_btn.isVisible() and not hover.overlay.isVisible()


@pytest.mark.parametrize('saved,expected', [(None, 'loop'), ({}, 'loop'), ({'playback_mode':'invalid'}, 'loop'),
                                           ({'playback_mode':'once'}, 'once'), ({'playback_mode':'loop'}, 'loop')])
def test_default_loop_and_persisted_choice(window, application, saved, expected):
    import json
    from playback_preferences import load, path
    w = window
    if saved is not None: path().write_text(json.dumps(saved), encoding='utf-8')
    load(w)
    assert w.playback_mode == expected
    assert w.loop_btn.isChecked() == (expected=='loop')
    assert w.loop_btn.symbol == expected
    w.loop_btn.click(); QTest.qWait(350)
    changed = 'once' if expected=='loop' else 'loop'
    assert json.loads(path().read_text(encoding='utf-8'))['playback_mode'] == changed
    load(w)
    assert w.playback_mode == changed and w.loop_btn.isChecked() == (changed=='loop')
