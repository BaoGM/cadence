# SPDX-License-Identifier: GPL-3.0-only
import shutil
import time
from threading import Event
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest

from model import Document, Segment, State
from test_drawing import application, window
from test_render1170 import clips
from test_timeline200 import move_pointer


def wait_for(application, condition):
    until=time.monotonic()+10
    while not condition() and time.monotonic()<until:
        application.processEvents(); QTest.qWait(10)
    assert condition()


@pytest.mark.parametrize('simple',[False,True])
def test_remove_middle_clip_from_selected_track(window,simple):
    w=window; t=w.timeline
    w.request_frame=lambda:None
    w.doc.state=State(tuple(Segment('a',i,i+10,cut_before=True) for i in (0,10,20)))
    w.refresh(); w.workspaces.set_timeline_simple(simple)
    y=int(t.simple_track_rect().center().y()) if simple else t.track_y('video')+6
    point=QPoint(round(t.x_for(15)),y)
    QTest.mouseDClick(t,Qt.LeftButton,Qt.ShiftModifier,point)
    assert w.doc.state.selection_ranges()==((0,30),)
    QTest.mouseDClick(t,Qt.LeftButton,Qt.ControlModifier,point)
    assert w.doc.state.selection_ranges()==((0,10),(20,30))
    QTest.mouseDClick(t,Qt.LeftButton,Qt.ControlModifier,point)
    assert sum(b-a for a,b in w.doc.state.selection_ranges())==30


@pytest.mark.parametrize('release_keys',[Qt.NoModifier,Qt.AltModifier])
def test_transfer_requires_alt_until_release(window,release_keys):
    w=window; t=w.timeline
    w.request_frame=lambda:None
    w.add_media_track(); w.workspaces.set_timeline_simple(False)
    source,dest=w.doc.state.tracks
    upper,lower=(y+8 for _,y,_ in t.media_rows())
    x=round(t.x_for(6))
    QTest.mousePress(t,Qt.LeftButton,Qt.AltModifier,QPoint(x,upper))
    move_pointer(t,QPoint(x,lower),Qt.AltModifier)
    QTest.mouseRelease(t,Qt.LeftButton,release_keys,QPoint(x,lower))
    assert w.doc.state.tracks[1].length==(0 if release_keys==Qt.NoModifier else source.length)


@pytest.mark.parametrize(('origin','drop_frame','expected'),[('files',5,'before'),('tree',26,'after')])
def test_library_drop_preserves_current_clip(window,application,clips,tmp_path,origin,drop_frame,expected):
    w=window; original=Document(); original.append_media([clips[0]])
    w.install_doc(original)
    folder=tmp_path/'folder'; folder.mkdir()
    nested=folder/'sub'; nested.mkdir()
    first=folder/'first.mp4'; second=nested/'second.mp4'
    for path in (first,second): shutil.copyfile(clips[1]['path'],path)
    panel=w.playlists_panel
    identity=panel.store.create('collection',root=str(folder))
    panel.store.scanned(identity,str(folder),[str(first)])
    panel.rebuild((identity,str(folder))); panel.show_files()
    if origin=='tree':
        source=panel.tree; mime=source.mimeData([source.currentItem()])
    else:
        source=panel.files; mime=source.mimeData([source.item(0)])
    class Enter(QDragEnterEvent):
        def source(self): return source
    class Drop(QDropEvent):
        def source(self): return source
    t=w.timeline; y=next(t.media_rows())[1]+8
    pos=QPointF(t.x_for(drop_frame),y)
    arguments=(Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    entry=Enter(pos.toPoint(),*arguments); application.sendEvent(t,entry)
    assert entry.isAccepted()
    drop=Drop(pos,*arguments); application.sendEvent(t,drop)
    assert drop.isAccepted()
    wait_for(application,lambda:w.job is None)
    assert w.doc is original
    media=[Path(w.doc.media[s.media]['path']).name for s in w.doc.active_track.segments]
    expected_names=['first.mp4','red.mp4'] if expected=='before' else ['red.mp4','first.mp4','second.mp4']
    assert media==expected_names and w.doc.undo()
    assert [s.media for s in w.doc.active_track.segments]==[clips[0]['id']]


def test_lazy_poster_decodes_single_visible_frame(window,application,clips):
    w=window
    w.doc=Document(); w.doc.append_media(clips); w.refresh()
    w.library.show(); w.library_tabs.setCurrentIndex(1); application.processEvents()
    wait_for(application,lambda:any(w.source_previews.cache.values()))
    for images in w.source_previews.cache.values():
        assert len(images)==1 and not images[0].isNull()


def test_import_result_with_missing_track_does_not_touch_document():
    doc=Document(); before=doc.signature()
    item=dict(id='new',frames=10,fps='30')
    assert not doc.insert_track_sources('removed',[item],0,adopt_rate=True)
    assert doc.signature()==before and not doc.media and not doc.undo_stack
    assert doc.insert_track_sources(doc.active_track_id,[item],0,adopt_rate=True)
    assert doc.fps==30 and doc.undo() and not doc.dirty


def test_recursive_folder_order_exclusions_and_junctions(tmp_path,monkeypatch):
    import playlist_store as store
    root=str(tmp_path/'root'); sub=str(Path(root)/'sub')
    clips=[str(Path(root)/f'{i}.mp4') for i in range(3)]
    nested=str(Path(sub)/'nested.mp4')
    def scan(path,*,skip_junctions):
        assert skip_junctions
        if path==root: return [sub,str(tmp_path/'outside')],clips
        assert path==sub
        return [root],[nested]
    monkeypatch.setattr(store,'scan_folder',scan)
    records={root:dict(files=[clips[2]],excluded=[clips[1]])}
    assert store.folder_tree_files(root,records,Event())==[clips[2],clips[0],nested]


def test_selected_row_has_rounded_two_pixel_inset(application):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor,QImage,QPainter
    from PySide6.QtWidgets import QStyle
    from library_style import row_background
    image=QImage(160,25,QImage.Format_RGB32); image.fill(QColor('#171e26'))
    painter=QPainter(image); painter.setRenderHint(QPainter.Antialiasing)
    row_background(painter,QRect(0,0,160,25),QStyle.State_Selected)
    painter.end()
    for y in range(5,20):
        assert [image.pixelColor(x,y).name() for x in range(4)]==['#68e0cf','#68e0cf','#244044','#244044']
    for y in (0,24):
        assert image.pixelColor(0,y).name()=='#171e26'
        assert image.pixelColor(10,y).name()=='#244044'
