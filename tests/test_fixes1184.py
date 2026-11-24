# SPDX-License-Identifier: GPL-3.0-only
import shutil
import threading

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from model import State, Segment, MediaTrack, TrackInfo
from test_drawing import application, window
from test_render1170 import clips, document
from test_sync1120 import pump


@pytest.fixture(scope='module', autouse=True)
def isolated_cache(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('CADENCE_CACHE',str(tmp_path_factory.mktemp('media-cache')))
        yield


@pytest.mark.parametrize('simple,lane', [(True, 'video'), (False, 'video'), (False, 'audio')])
@pytest.mark.parametrize('frame,expected', [(4, (0, 10)), (18, (10, 25)), (27, (0, 30))])
def test_plain_double_click_selects_clip_or_track_in_gap(window, application, simple, lane, frame, expected):
    w=window; t=w.timeline; w.request_frame=lambda:None
    segments=(Segment('a', 0, 10), Segment('a', 10, 25), Segment(None, 0, 5))
    w.doc.state=State(segments, audio_segments=segments, selection=(1, 3))
    if lane=='audio': w.doc.expand_track_audio(w.doc.active_track_id, True)
    t.simple=simple; w.refresh(); application.processEvents()
    info=w.doc.active_track.info
    y=round(t.simple_track_rect().center().y()) if simple else t.track_y(lane)+9
    point=QPoint(round(t.x_for(frame)), y)
    modifier=Qt.ShiftModifier if frame==27 else Qt.NoModifier
    QTest.mouseClick(t, Qt.LeftButton, modifier, point)
    QTest.mouseDClick(t, Qt.LeftButton, modifier, point)
    QTest.mouseRelease(t, Qt.LeftButton, modifier, point)
    assert w.doc.state.selection==expected
    assert t.selection_track==lane and t.gesture is None and t.anchor is None
    assert w.doc.active_track.info==info
    QTest.mouseMove(t, point+QPoint(40,0))
    assert w.doc.state.selection==expected


@pytest.mark.parametrize('target', ['title', 'past_end', 'clip'])
def test_double_click_uses_clicked_track_without_expanding_audio(window, application, target):
    w=window; t=w.timeline; w.request_frame=lambda:None
    second=MediaTrack(TrackInfo('second','Piste 2'), (Segment('a',0,8), Segment('a',10,30)))
    w.doc.state=State((Segment('a',0,60),), second_track=second)
    w.doc.select_track(w.doc.state.track_info.id); t.simple=False; w.refresh(); application.processEvents()
    row=next(y for track,y,height in t.media_rows() if track.info.id=='second')
    x=40 if target=='title' else round(t.x_for(40 if target=='past_end' else 14))
    point=QPoint(x,row+9)
    modifier=Qt.NoModifier if target=='clip' else Qt.ShiftModifier
    QTest.mouseClick(t,Qt.LeftButton,modifier,point)
    QTest.mouseDClick(t,Qt.LeftButton,modifier,point)
    QTest.mouseRelease(t,Qt.LeftButton,modifier,point)
    assert w.doc.state.selection==((8,28) if target=='clip' else (0,28))
    assert w.doc.selected_track_ids==('second',)
    assert not w.doc.active_track.info.audio_expanded


def test_chevron_still_expands_audio(window, application):
    w=window; w.request_frame=lambda:None; w.timeline.simple=False; w.refresh(); application.processEvents()
    point=QPoint(10,w.timeline.track_y('video')+9)
    QTest.mouseClick(w.timeline,Qt.LeftButton,Qt.NoModifier,point)
    assert w.doc.active_track.info.audio_expanded
    QTest.mouseClick(w.timeline,Qt.LeftButton,Qt.NoModifier,point)
    assert not w.doc.active_track.info.audio_expanded


@pytest.mark.parametrize('kind', ['list', 'nested_folder'])
def test_library_double_click_opens_only_chosen_video_and_autoplays(window, application, clips, monkeypatch, tmp_path, kind):
    w=window; panel=w.playlists_panel; old=document(clips); w.install_doc(old)
    original=old.state
    selected_folder=None
    if kind=='list': identity=panel.store.create('Playlist', [m['path'] for m in clips])
    else:
        root=tmp_path/'root'; child=root/'shot'; child.mkdir(parents=True)
        for index, media in enumerate(clips):shutil.copyfile(media['path'],child/f'{index}.mp4')
        identity=panel.store.create('Root',root=root); panel.rebuild((identity,str(root)))
        pump(application,lambda:w.job is None and not panel.scans,timeout=10)
        panel.tree.setCurrentItem(panel.tree.currentItem().child(0))
        pump(application,lambda:w.job is None and not panel.scans,timeout=10)
        selected_folder=str(child)
    if kind=='list': panel.rebuild((identity,None))
    w.library.show(); w.library_tabs.setCurrentWidget(panel); application.processEvents()
    pump(application,lambda:w.job is None and not panel.scans,timeout=10)
    errors=[]; monkeypatch.setattr(w,'error',errors.append)
    selected_path=panel.files.item(1).data(Qt.ItemDataRole.UserRole)
    point=panel.files.visualItemRect(panel.files.item(1)).center()
    QTest.mouseClick(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert panel.files.selectedItems()==[panel.files.item(1)] and w.doc is old and w.job is None
    assert not w.transport.running and not panel.temporary
    QTest.mouseDClick(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseRelease(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    try: pump(application,lambda:w.job is None and w.transport.running,timeout=30)
    except AssertionError:
        raise AssertionError(dict(errors=errors, same_doc=w.doc is old, job=bool(w.job),
                                  pending=bool(panel.pending_playback), point=(point.x(),point.y()),
                                  visible=panel.files.isVisible(), paths=panel.all_paths()))
    assert not errors and w.doc is not old and old.state==original
    assert [m['path'] for m in w.doc.media.values()]==[selected_path]
    assert w.doc.state.length==clips[1]['frames']
    assert any(r['doc'] is old for r in panel.temporary)
    assert panel.current==(identity,selected_folder) and panel.files.count()==2
    w.pause()


def test_library_selection_and_drag_do_not_open_a_video(window, application, tmp_path, monkeypatch):
    panel=window.playlists_panel
    paths=[tmp_path/'a.mp4',tmp_path/'b.mp4',tmp_path/'c.mp4']
    for path in paths:path.write_bytes(b'fixture')
    identity=panel.store.create('Playlist',paths); panel.rebuild((identity,None))
    window.library.show(); window.library_tabs.setCurrentWidget(panel); application.processEvents()
    jobs=[]; monkeypatch.setattr(window,'begin_task',lambda *a:jobs.append(a))
    first=panel.files.visualItemRect(panel.files.item(0)).center()
    second=panel.files.visualItemRect(panel.files.item(1)).center()
    third=panel.files.visualItemRect(panel.files.item(2)).center()
    QTest.mouseClick(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,first)
    QTest.mouseClick(panel.files.viewport(),Qt.LeftButton,Qt.ShiftModifier,third)
    assert len(panel.files.selectedItems())==3 and not jobs
    QTest.mouseClick(panel.files.viewport(),Qt.LeftButton,Qt.ControlModifier,first)
    assert len(panel.files.selectedItems())==2 and not jobs
    import json
    from playlist_ui import LIBRARY_MIME
    payload=panel.files.mimeData(panel.files.selectedItems())
    assert json.loads(bytes(payload.data(LIBRARY_MIME)))['paths']==[str(path) for path in paths[1:]]
    QTest.mouseClick(panel.files.viewport(),Qt.RightButton,Qt.NoModifier,first)
    assert not jobs
    panel.files.setDragEnabled(False)
    QTest.mousePress(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,first)
    event=QMouseEvent(QEvent.MouseMove,QPointF(second+QPoint(30,0)),QPointF(panel.files.viewport().mapToGlobal(second)),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    application.sendEvent(panel.files.viewport(),event)
    QTest.mouseRelease(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,second)
    assert not jobs


def test_failed_library_open_preserves_edit_without_playing(window, application, tmp_path, monkeypatch):
    w=window; panel=w.playlists_panel; old=w.doc; original=old.state
    broken=tmp_path/'broken.mp4'; broken.write_bytes(b'not a video')
    errors=[]; monkeypatch.setattr(w,'error',errors.append)
    panel.play_file(str(broken))
    pump(application,lambda:w.job is None,timeout=15)
    assert not errors and not panel.file_error.isHidden() and panel.file_error.text()
    assert w.doc is old and old.state==original
    assert not panel.temporary and not panel.play_timer.isActive() and not w.transport.running


@pytest.mark.parametrize('case', ['quick', 'slow', 'multiple'])
def test_media_open_shows_progress_only_when_needed(window, application, monkeypatch, case):
    import app
    shown=[]; applied=[]; release=threading.Event()
    class ObservedProgress(app.QProgressDialog):
        def showEvent(self, event):
            shown.append(self.value())
            super().showEvent(event)
    monkeypatch.setattr(app,'QProgressDialog',ObservedProgress)
    def prepare(progress,cancel):
        progress(.37,'Test')
        while not release.wait(.01) and not cancel.is_set(): pass
        return 'ok'
    paths=['a','b'] if case=='multiple' else ['a']
    window.begin_media_open(paths,'Test',prepare,applied.append)
    try:
        assert bool(shown)==(case=='multiple')
        if case=='slow':
            pump(application,lambda:bool(shown),timeout=5)
            assert shown==[37]
            QTest.keyClick(window.dialog,Qt.Key_Escape)
            assert window.job.cancel.is_set()
    finally:
        release.set()
        pump(application,lambda:window.job is None,timeout=5)
    assert applied==([] if case=='slow' else ['ok'])
    assert window.dialog is None
    if case=='quick':
        QTest.qWait(1100)
        assert not shown


@pytest.mark.parametrize('mode',['read','edit','short'])
def test_library_lists_do_not_overlap_in_small_window(window,application,mode):
    w=window; panel=w.playlists_panel
    w.workspaces.switch('edit' if mode=='short' else mode); w.comparison_panel.hide(); w.drawing.panel.hide()
    w.library.show(); w.library_tabs.setCurrentWidget(panel)
    w.resize(640,400)
    if mode=='short': panel.setFixedHeight(100)
    QTest.qWait(100)
    tree=panel.tree.geometry(); files=panel.files.geometry()
    assert panel.tree.mapToGlobal(panel.tree.rect().bottomLeft()).y()<panel.files.mapToGlobal(panel.files.rect().topLeft()).y()
    assert panel.files.parentWidget().rect().contains(files)
    assert min(tree.height(),files.height())>=panel.fontMetrics().height()+8
    for view in (panel.tree, panel.files):
        assert view.viewport().height() >= view.itemDelegate().row_height
    content=panel.tree.parentWidget().parentWidget()
    assert content.parentWidget().width()>=content.minimumSizeHint().width()
