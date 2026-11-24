# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from drawing import DrawingKey, Mark
from model import Document, Segment, State
from test_drawing import application
from widgets import Timeline


@pytest.fixture(params=[False, True], ids=['detailed', 'simple'])
def timeline(application, request):
    doc = Document()
    doc.media = {key: {'name': name, 'frames': 32} for key, name in
                 [('a','Approche.mov'), ('b','Traversée.mov'), ('c','Lisière.mov')]}
    doc.state = State(tuple(Segment(key,0,32) for key in doc.media), position=48,
                      drawings=(DrawingKey(14,24,(Mark(),)),), frame_markers=(36,))
    widget = Timeline()
    widget.simple = request.param
    widget.resize(800,100)
    def refresh():
        widget.set_document(doc.state,doc.media,24)
    def move(a,b,at,kind):
        doc.move_range(a,b,at,'linked')
        refresh()
    def copy(a,b,at):
        doc.duplicate_range(a,b,at)
        refresh()
    widget.moved.connect(move)
    widget.duplicated.connect(copy)
    widget.drawingResized.connect(lambda *args: (doc.resize_drawing(*args),refresh()))
    refresh()
    widget.show()
    application.processEvents()
    yield widget,doc
    widget.close()
    widget.deleteLater()


def point(widget,frame):
    y = widget.simple_track_rect().bottom()-6 if widget.simple else widget.track_y('video')+9
    return QPoint(round(widget.x_for(frame)),round(y))


def move_pointer(widget,point,mods):
    local=QPointF(point)
    event=QMouseEvent(QEvent.Type.MouseMove,local,QPointF(widget.mapToGlobal(point)),
                      Qt.NoButton,Qt.LeftButton,mods)
    QApplication.sendEvent(widget,event)


@pytest.mark.parametrize('copy',[False,True],ids=['move','copy'])
def test_animated_drop_snap_and_one_undo(timeline,copy):
    widget,doc=timeline
    mods=Qt.AltModifier|Qt.ShiftModifier if copy else Qt.AltModifier
    original=doc.state
    start=point(widget,7); end=point(widget,91)
    QTest.mousePress(widget,Qt.LeftButton,mods,start)
    move_pointer(widget,end,mods)
    assert widget.clip_preview.phase=='lift' and widget.clip_preview.copying==copy
    assert widget.drop_frame==96
    QTest.mouseRelease(widget,Qt.LeftButton,mods,end)
    assert widget.clip_preview.phase=='land' and widget.clip_preview.destination==doc.state.position
    assert [s.media for s in doc.state.segments]==(['a','b','c','a'] if copy else ['b','c','a'])
    assert doc.state.segments==doc.state.audio
    assert doc.undo() and doc.state==original
    assert doc.redo() and doc.state!=original
    QTest.qWait(210)
    assert widget.clip_preview.phase is None


@pytest.mark.parametrize('stop',['escape','focus','click'])
def test_dismiss_without_edit_or_seek(timeline,stop):
    widget,doc=timeline
    original=doc.state; seeks=[]
    widget.seek.connect(seeks.append)
    p=point(widget,8); q=point(widget,90)
    QTest.mousePress(widget,Qt.LeftButton,Qt.AltModifier,p)
    if stop!='click': move_pointer(widget,q,Qt.AltModifier)
    if stop=='escape': QTest.keyClick(widget,Qt.Key_Escape)
    if stop=='focus': QApplication.sendEvent(widget,QEvent(QEvent.Type.WindowDeactivate))
    QTest.mouseRelease(widget,Qt.LeftButton,Qt.AltModifier,q if stop!='click' else p)
    assert not seeks and doc.state==original and not doc.undo_stack
    assert widget.clip_preview.phase is None and widget.drop_frame is None


def test_exposure_handle_does_not_select_clip_range(timeline):
    widget,doc=timeline
    hits=[]
    widget.selectionDragged.connect(lambda *args:hits.append(args))
    key=doc.state.drawings[0]
    y=widget.track_y('drawing')+2
    if widget.simple:
        bar=widget.simple_track_rect()
        assert 16<y<bar.top()-3
        assert not widget.drawing_track.contains(point(widget,24))
        assert widget.height()==42
    p=QPoint(round(widget.x_for(key.end)),y)
    q=QPoint(round(widget.x_for(key.end+7)),y)
    QTest.mousePress(widget,Qt.LeftButton,Qt.NoModifier,p)
    move_pointer(widget,q,Qt.NoModifier)
    assert widget.drawing_track.preview[0].end==31
    QTest.mouseRelease(widget,Qt.LeftButton,Qt.NoModifier,q)
    assert doc.state.drawings[0].end==31 and not hits

def test_marker_flag_renames_and_seeks_its_frame_in_each_view(timeline):
    from dataclasses import replace
    from timeline_skin import marker_areas, marker_at
    widget, doc = timeline
    last = doc.state.length - 1
    doc.state = replace(doc.state, frame_markers=(12,last), marker_names=((last,'Contact'),))
    widget.set_document(doc.state,doc.media,doc.fps)
    _, frame, flag_area, text_area = list(marker_areas(widget))[-1]
    assert frame==last and text_area.right()<flag_area.left()
    point=QPoint(round(text_area.right()-9),round(text_area.center().y()))
    assert marker_at(widget,point)==(last,'Contact')
    renamed, sought=[],[]
    widget.renameMarker.connect(renamed.append)
    widget.seek.connect(sought.append)
    menu=widget.context_menu(point)
    next(a for a in menu.actions() if a.data()=='rename_marker').trigger()
    menu.deleteLater()
    QTest.mouseClick(widget,Qt.LeftButton,Qt.NoModifier,point)
    assert renamed==[last] and sought==[last]


def test_header_add_controls_ignore_occupied_frames(application):
    from dataclasses import replace
    widget=Timeline()
    state=State((Segment('a',0,60),),position=13,drawings=(DrawingKey(12,18,(Mark(),)),),frame_markers=(13,))
    widget.set_document(state,{},24)
    markers,keys=[],[]
    widget.markerAdded.connect(markers.append)
    widget.drawingKeyAdded.connect(lambda:keys.append(True))
    for position in (13,24):
        widget.set_document(replace(state,position=position),{},24)
        for y in (11,33): QTest.mouseClick(widget,Qt.LeftButton,Qt.NoModifier,QPoint(widget.track_left()-16,y))
    assert markers==[24] and keys==[True]


def test_folded_track_reads_one_thumbnail_and_expanded_track_reads_a_strip(application,tmp_path):
    import time
    import av
    import numpy as np
    from dataclasses import replace
    path=tmp_path/'colors.mkv'
    with av.open(str(path),'w') as movie:
        video=movie.add_stream('ffv1',rate=24)
        video.width,video.height=32,24
        for i in range(24):
            color=(220,10,10) if i<12 else (10,130,55)
            array=np.full((24,32,3),color,np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(array,format='rgb24')): movie.mux(packet)
        for packet in video.encode(): movie.mux(packet)
    state=State((Segment('clip',12,24),))
    media={'clip':dict(proxy=str(path),fps='24',frames=24,name='colors.mkv')}
    widget=Timeline()
    widget.resize(800,116)
    widget.show()
    try:
        for count in (1,7):
            expanded=count==7
            widget.set_document(replace(state,track_info=replace(state.track_info,audio_expanded=expanded)),media,24)
            until=time.monotonic()+5
            while time.monotonic()<until:
                application.processEvents()
                if any(len(images)==count for images in widget.thumbnails.cache.values()): break
                time.sleep(.01)
            images=next(images for images in widget.thumbnails.cache.values() if len(images)==count)
            for image in images:
                color=image.pixelColor(image.width()//2,image.height()//2)
                assert color.green()>100 and color.red()<30
            if not expanded: assert all(len(row)==1 for row in widget.thumbnails.cache.values())
    finally:
        widget.close()
        widget.deleteLater()
