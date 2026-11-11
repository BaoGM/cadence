# SPDX-License-Identifier: GPL-3.0-only
import os,sys
from pathlib import Path
from dataclasses import replace,asdict
from fractions import Fraction
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drawing import Mark,DrawingKey,put_key,active_key,render_marks,render_layer,load_keys
from model import Document,State,Segment
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtGui import QImage,QTransform,QTabletEvent,QPointingDevice,QInputDevice
from PySide6.QtWidgets import QApplication

@pytest.fixture(autouse=True)
def cache_location(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))

@pytest.fixture(scope='module')
def application():
    app=QApplication.instance() or QApplication([])
    from PySide6.QtGui import QFontDatabase
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    yield app


def pixels(image):
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.bits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4).copy()


def test_exposures_split_preserve_sides_and_roundtrip(tmp_path):
    mark=Mark(points=((.2,.3,.6),(.8,.3,1.)))
    old=DrawingKey(0,20,(mark,)); new=DrawingKey(4,9,())
    keys=put_key((old,),new)
    assert [(k.start,k.end) for k in keys]==[(0,4),(4,9),(9,20)]
    assert keys[0].marks==keys[2].marks and active_key(keys,8)==new and active_key(keys,20) is None
    d=Document(); d.media={'a':{'id':'a','frames':20}}; d.state=State((Segment('a',0,20),)); baseline=d.state
    d.commit('draw',replace(d.state,drawings=keys)); assert d.dirty
    d.save(tmp_path/'draw.cadence'); loaded=Document.load(tmp_path/'draw.cadence')
    assert loaded.state.drawings==keys and not loaded.dirty
    d.undo(); assert d.state==baseline; d.redo(); assert d.state.drawings==keys
    with pytest.raises(ValueError): load_keys([asdict(old),asdict(new)])
    with pytest.raises(ValueError): load_keys([asdict(replace(old,marks=(replace(mark,points=((float('nan'),0,1),)),)))])


def test_pressure_opacity_eraser_and_text(application):
    mark=Mark(points=((.2,.5,.2),(.8,.5,1)),size=.2,color='#ff0000',opacity=.5)
    a=pixels(render_marks((mark,),200,100))
    assert a[:,40,3].sum()<a[:,160,3].sum()/2
    assert 125<=a[50,100,3]<=129 and a[:,:,3].max()<=129 # no alpha buildup along one stroke
    flat=pixels(render_marks((replace(mark,pressure=False),),200,100))
    assert abs(int(flat[:,40,3].sum())-int(flat[:,160,3].sum()))<150
    eraser=Mark(tool='eraser',points=((.5,.5,1),),size=.4,pressure=False)
    cleared=pixels(render_marks((mark,eraser),200,100)); assert cleared[50,100,3]==0 and cleared[50,40,3]>0
    text=pixels(render_marks((Mark(tool='text',points=((.1,.1,1),),size=.2,text='Cadence'),),200,100))
    assert np.count_nonzero(text[:,:,3])>100


def test_onion_selected_offsets_tint_and_exclusion(application):
    dot=Mark(points=((.5,.5,1),),size=.2,pressure=False,color='#ffffff')
    keys=(DrawingKey(1,2,(dot,)),DrawingKey(4,5,(replace(dot,points=((.8,.5,1),)),)))
    assert pixels(render_layer(keys,2,100,100))[:,:,3].max()==0
    ghost=pixels(render_layer(keys,2,100,100,1,2,.3))
    assert abs(int(ghost[50,50,0])-int(ghost[50,50,2]))<=1 and abs(int(ghost[50,80,2])-int(ghost[50,80,0]))<=1
    assert 36<=ghost[50,50,3]<=40
    # Multiple offsets into the same held key must not accumulate its ghost.
    held=(DrawingKey(0,4,(dot,)),)
    assert int(pixels(render_layer(held,4,100,100,3,0))[50,50,3])==pytest.approx(255*.3*.75,abs=2)

@pytest.fixture
def window(application,tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    from app import MainWindow
    w=MainWindow(); w.workspaces.switch('edit'); w.doc.media={'a':{'id':'a','name':'test','path':'test.mp4','width':640,'height':360,'frames':30,'fps':'24'}}
    w.doc.state=State((Segment('a',0,30),)); w.refresh(); w.viewer.set_frame(np.zeros((360,640,3),np.uint8)); w.show(); application.processEvents()
    yield w
    w.doc.saved_signature=w.doc.signature(); w.close(); application.processEvents()


def test_mouse_selection_keys_transformed_canvas_and_history(window,application):
    w=window; d=w.drawing; v=w.viewer
    d.choose_tool('brush'); application.processEvents()
    w.doc.select(3,8); w.doc.state=replace(w.doc.state,position=3); w.refresh()
    center=QPointF(v.width()/2,v.height()/2)
    d.begin(center,1); d.move(center+QPointF(60,0),1); d.finish()
    key=w.doc.state.drawings[0]; assert (key.start,key.end)==(3,8) and len(key.marks)==1
    assert len(w.doc.undo_stack)==1
    w.doc.undo(); assert not w.doc.state.drawings; w.doc.redo(); assert w.doc.state.drawings==(key,)
    v.zoom=1.7; v.angle=37; v.pan=QPointF(30,-20)
    size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); rect=d.a_rect(size)
    transform=QTransform(); transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y()); transform.rotate(v.angle); transform.scale(v.zoom,v.zoom)
    screen=transform.map(QPointF(rect.x()+rect.width()*.25,rect.y()+rect.height()*.75))
    assert d.point(screen)==pytest.approx((.25,.75))
    v.flip_h=True; v.flip_v=True; assert d.point(screen)==pytest.approx((.75,.25))
    w.doc.state=replace(w.doc.state,selection=None,position=12); w.refresh(); v.flip_h=False; v.flip_v=False; v.reset_view(); d.copy_key()
    assert active_key(w.doc.state.drawings,12).marks==key.marks
    d.delete_key(); assert active_key(w.doc.state.drawings,12) is None


def test_real_qt_tablet_event_path(window,application):
    d=window.drawing; v=window.viewer; d.choose_tool('brush'); application.processEvents()
    device=QPointingDevice('Synthetic tablet',42,QInputDevice.DeviceType.Stylus,QPointingDevice.PointerType.Pen,QInputDevice.Capability.Position|QInputDevice.Capability.Pressure,1,2)
    center=QPointF(v.width()/2,v.height()/2)
    for kind,offset,pressure in [(QEvent.Type.TabletPress,0,.15),(QEvent.Type.TabletMove,40,.8),(QEvent.Type.TabletRelease,40,0)]:
        event=QTabletEvent(kind,device,center+QPointF(offset,0),center+QPointF(offset,0),pressure,0,0,0,0,0,Qt.KeyboardModifier.NoModifier,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton if kind!=QEvent.Type.TabletRelease else Qt.MouseButton.NoButton)
        QApplication.sendEvent(v,event); assert event.isAccepted()
    marks=window.doc.state.drawings[0].marks
    assert len(marks)==1 and [p[2] for p in marks[0].points]==[.15,.8]
    assert not hasattr(d,'tablet_label')


def test_export_exact_draw_range_and_eraser(application,tmp_path):
    import av,subprocess
    from media import ffmpeg,prepare_media,export_video
    source=tmp_path/'black.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=12:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media=prepare_media(source)
    mark=Mark(points=((.25,.5,1),),size=.3,pressure=False,color='#ff0000')
    state=State((Segment(media['id'],0,12),),drawings=(DrawingKey(3,6,(mark,)),))
    target=tmp_path/'draw.mp4'; export_video(state,{media['id']:media},Fraction(12),target)
    with av.open(str(target)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(frames)==12
    assert [i for i,f in enumerate(frames) if f[45,40,0]>150]==[3,4,5]
    target=tmp_path/'mirror.mp4'; export_video(replace(state,flip_h=True),{media['id']:media},Fraction(12),target)
    with av.open(str(target)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert frames[3][45,120,0]>150 and frames[3][45,40,0]<20

def test_text_tool_and_color_selector(window,application,monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    d=window.drawing; v=window.viewer; d.choose_tool('text'); application.processEvents()
    monkeypatch.setattr(QInputDialog,'getMultiLineText',lambda *args:('Arial\nDeux lignes',True))
    assert d.wheel.set_color('#12a4ef') and d.hex.text()=='#12a4ef'
    d.begin(QPointF(v.width()/2,v.height()/2),1); d.finish()
    key=window.doc.state.drawings[0]
    assert key.marks[0].tool=='text' and key.marks[0].text=='Arial\nDeux lignes'
    assert key.marks[0].color=='#12a4ef' and (key.start,key.end)==(0,1)
    d.before.setValue(3); d.after.setValue(0); assert d.before.value()==3 and d.after.value()==0
    center,r,square=d.wheel.geometry_parts(); d.wheel.drag='hue'; d.wheel.choose(center+QPointF(r*.85,0)); assert d.wheel.h==pytest.approx(0)
    d.wheel.drag='sv'; d.wheel.choose(square.bottomLeft()); assert d.wheel.color()=='#000000'

def test_linked_drawing_edits_follow_video_and_can_be_detached():
    def make():
        d=Document(); d.state=State((Segment('a',0,30),),drawings=tuple(DrawingKey(i,i+1,(Mark(points=((.2,.2,1),),text=str(i)),)) for i in range(30)))
        return d
    def follows(d):
        expected=[i if seg.media else None for seg in d.state.segments for i in range(seg.start,seg.end)]
        actual=[int(active_key(d.state.drawings,i).marks[0].text) if active_key(d.state.drawings,i) else None for i in range(d.state.length)]
        assert actual==expected
    for gap in (False,True):
        d=make(); original=d.state; d.move_range(0,10,30,'linked',gap); follows(d); d.undo(); assert d.state==original; d.redo(); follows(d)
    d=make(); d.select(3,8); d.cut(True); follows(d); d.state=replace(d.state,position=d.state.length); d.paste(True); follows(d)
    d=make(); d.duplicate_range(2,6); follows(d)
    d=make(); d.delete_ranges([(2,5),(4,8),(20,22)]); follows(d)
    d=make(); d.delete_track_range(4,8,'video'); follows(d)
    d=make(); d.state=replace(d.state,position=0); d.insert_gap(5); follows(d)
    d=make(); old=d.state.drawings; d.move_range(0,10,30,'audio'); assert d.state.drawings==old
    d=make(); d.state=replace(d.state,drawings_linked=False); old=d.state.drawings; d.move_range(0,10,30); assert d.state.drawings==old


def test_drawing_range_move_resize_collision_and_undo():
    mark=Mark(points=((.2,.3,1),)); d=Document(); d.state=State((Segment('a',0,40),),drawings=(DrawingKey(2,5,(mark,)),DrawingKey(7,9,(mark,)),DrawingKey(25,30,(mark,))))
    original=d.state
    assert d.move_drawings(2,9,12)
    assert [(k.start,k.end) for k in d.state.drawings]==[(12,15),(17,19),(25,30)]
    assert d.state.segments==original.segments
    assert not d.move_drawings(12,19,23) # Would overwrite the third exposure.
    d.undo(); assert d.state==original
    d.resize_drawing(2,0,20); assert [(k.start,k.end) for k in d.state.drawings]==[(0,7),(7,9),(25,30)]
    d.undo(); d.delete_drawings(3,4); assert [(k.start,k.end) for k in d.state.drawings][:2]==[(2,3),(4,5)]


def test_onion_fades_with_temporal_distance(application):
    keys=tuple(DrawingKey(10-distance,11-distance,(Mark(points=((x,.5,1),),size=.1,pressure=False),)) for distance,x in [(1,.2),(2,.5),(4,.8)])
    image=pixels(render_layer(keys,10,100,100,4,0,.8))
    a,b,c=[int(image[50,x,3]) for x in (20,50,80)]
    assert a>b>c and b==pytest.approx(a*.75,abs=2) and c==pytest.approx(a/4,abs=2)


def screen_point(d,x,y):
    v=d.viewer; size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); rect=d.a_rect(size)
    transform=QTransform(); transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y()); transform.rotate(v.angle); transform.scale(v.zoom,v.zoom)
    return transform.map(QPointF(rect.x()+rect.width()*x,rect.y()+rect.height()*y))


def test_lasso_and_text_move_with_undo(window,application,monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog,'getMultiLineText',lambda *args:('',False))
    w=window; d=w.drawing; v=w.viewer
    first=Mark(points=((.2,.2,1),(.35,.3,1)),size=.01); second=Mark(points=((.7,.7,1),),size=.04)
    text=Mark(tool='text',points=((.5,.1,1),),size=.05,text='Arial')
    key=DrawingKey(0,4,(first,second,text)); w.doc.state=replace(w.doc.state,drawings=(key,)); w.refresh()
    d.choose_tool('lasso'); application.processEvents()
    d.begin(screen_point(d,.1,.1),1)
    for x,y in ((.45,.1),(.45,.4),(.1,.4),(.1,.1)): d.move(screen_point(d,x,y),1)
    d.finish(); assert d.selection.indices==(0,)
    d.begin(screen_point(d,.25,.25),1); d.move(screen_point(d,.35,.4),1); d.finish()
    changed=w.doc.state.drawings[0]
    assert changed.marks[0].points[0][:2]==pytest.approx((.3,.35)) and changed.marks[1:]==key.marks[1:]
    w.doc.undo(); assert w.doc.state.drawings==(key,); w.refresh()
    d.choose_tool('text'); hit=d.selection.geometry(text).boundingRect().center(); d.begin(screen_point(d,hit.x(),hit.y()),1); assert d.selection.gesture=='translate'
    d.move(screen_point(d,hit.x()+.1,hit.y()+.1),1); d.finish()
    assert w.doc.state.drawings[0].marks[2].points[0][:2]==pytest.approx((.6,.2))
    assert w.doc.state.drawings[0].marks[:2]==key.marks[:2]


def test_key_list_multiselect_delete_and_navigation(window,application):
    from PySide6.QtCore import QItemSelectionModel
    w=window; d=w.drawing; mark=Mark(points=((.2,.2,1),))
    w.request_frame=lambda:None
    w.doc.state=replace(w.doc.state,drawings=tuple(DrawingKey(i,i+1,(mark,)) for i in (2,7,15))); w.refresh()
    d.keys.item(0).setSelected(True); d.keys.item(2).setSelected(True); d.key_clicked(d.keys.item(2)); w.refresh()
    assert len(d.keys.selectedItems())==2
    d.delete_key(); assert [k.start for k in w.doc.state.drawings]==[7]
    w.doc.undo(); w.refresh(); w.seek(8)
    from PySide6.QtTest import QTest
    w.activateWindow(); w.timeline.setFocus(); application.processEvents()
    QTest.keyClick(w.timeline,Qt.Key.Key_Comma); assert w.doc.state.position==7
    QTest.keyClick(w.timeline,Qt.Key.Key_Period); assert w.doc.state.position==15
    assert w.action_registry['Lecture/Clé précédente'][1]==',' and w.action_registry['Lecture/Clé suivante'][1]=='.'
    assert w.action_registry['Dessin/Ajouter un marqueur'][1]=='S'


def test_drawing_timeline_gestures_and_canvas_cursor(window,application):
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QMouseEvent
    w=window; d=w.drawing; t=w.timeline; w.request_frame=lambda:None
    mark=Mark(points=((.2,.2,1),)); w.doc.state=replace(w.doc.state,drawings=(DrawingKey(3,8,(mark,)),DrawingKey(23,26,(mark,))))
    w.refresh(); application.processEvents()
    def drag(x1,x2,mod):
        for kind,x,button in ((QEvent.Type.MouseButtonPress,x1,Qt.MouseButton.LeftButton),(QEvent.Type.MouseMove,x2,Qt.MouseButton.NoButton),(QEvent.Type.MouseButtonRelease,x2,Qt.MouseButton.LeftButton)):
            pos=QPointF(x,158); event=QMouseEvent(kind,pos,QPointF(t.mapToGlobal(pos.toPoint())),button,Qt.MouseButton.LeftButton,mod); QApplication.sendEvent(t,event)
    drag(t.x_for(5),t.x_for(15),Qt.KeyboardModifier.AltModifier)
    assert [(k.start,k.end) for k in w.doc.state.drawings]==[(13,18),(23,26)]
    assert t.selection_track=='drawing'
    drag(t.x_for(18),t.x_for(21),Qt.KeyboardModifier.NoModifier)
    assert w.doc.state.drawings[0].end==21
    drag(t.x_for(14),t.x_for(19),Qt.KeyboardModifier.ShiftModifier)
    assert w.doc.state.selection==(14,20)
    d.choose_tool('brush'); v=w.viewer; application.processEvents()
    pos=QPointF(v.width()/2,v.height()/2)
    global_pos=QPointF(v.mapToGlobal(pos.toPoint()))
    press=QMouseEvent(QEvent.Type.MouseButtonPress,pos,global_pos,Qt.MouseButton.MiddleButton,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.NoModifier)
    release=QMouseEvent(QEvent.Type.MouseButtonRelease,pos,global_pos,Qt.MouseButton.MiddleButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(v,press); QApplication.sendEvent(v,release)
    assert v.cursor().shape()==Qt.CursorShape.CrossCursor


def test_link_option_saved_and_drawing_clipboard_is_track_only(window,tmp_path):
    w=window; w.request_frame=lambda:None; mark=Mark(points=((.4,.4,1),))
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(2,5,(mark,)),)); w.refresh()
    w.link_drawings.setChecked(False); assert not w.doc.state.drawings_linked
    w.doc.save(tmp_path/'unlinked.cadence'); assert not Document.load(tmp_path/'unlinked.cadence').state.drawings_linked
    w.timeline.selection_track='drawing'; w.select(2,5); video=w.doc.state.segments; audio=w.doc.state.audio
    w.cut_selection(); assert not w.doc.state.drawings and w.doc.state.segments==video and w.doc.state.audio==audio
    w.seek(10); w.paste_selection(); assert [(k.start,k.end) for k in w.doc.state.drawings]==[(10,13)]
    assert w.doc.state.segments==video and w.doc.state.audio==audio
def test_radius_persists_on_each_video_frame(application):
    dot=Mark(points=((.5,.5,1),),size=.2,pressure=False)
    keys=(DrawingKey(10,13,(dot,)),)
    alpha=lambda frame:int(pixels(render_layer(keys,frame,100,100,3,3,.6))[50,50,3])
    assert [alpha(f) for f in (6,7,8,9,13,14,15,16)]==pytest.approx([0,38.25,76.5,114.75,114.75,76.5,38.25,0],abs=2)

def test_marker_shortcut_and_wrapping(window,application):
    from PySide6.QtTest import QTest
    w=window; w.request_frame=lambda:None
    w.activateWindow(); w.timeline.setFocus(); application.processEvents()
    w.seek(29); w.step(1); assert w.doc.state.position==0
    w.step(-1); assert w.doc.state.position==29
    w.seek(5); QTest.keyClick(w.timeline,Qt.Key.Key_S)
    assert w.doc.state.frame_markers==(5,) and not w.doc.state.drawings
    w.select(10,14); w.drawing.add_marker()
    assert w.doc.state.frame_markers==(5,10) and not w.doc.state.drawings
    w.seek(5); w.drawing.navigate(1); assert w.doc.state.position==10
    w.drawing.navigate(1); assert w.doc.state.position==5
    w.drawing.navigate(-1); assert w.doc.state.position==10
    w.doc.undo(); assert w.doc.state.frame_markers==(5,)
    w.doc.redo(); assert w.doc.state.frame_markers==(5,10)

def test_text_box_fit_style_resize_and_save(window,application,monkeypatch,tmp_path):
    from PySide6.QtWidgets import QInputDialog
    from draw_text import fitted_layout
    d=window.drawing; d.choose_tool('text'); application.processEvents()
    calls=[]
    monkeypatch.setattr(QInputDialog,'getMultiLineText',lambda *a:(calls.append(1) or 'Texte automatique',True))
    d.begin(screen_point(d,.1,.1),1); d.move(screen_point(d,.6,.4),1)
    assert not calls and not window.doc.state.drawings
    d.finish(); mark=window.doc.state.drawings[0].marks[0]
    assert mark.box==pytest.approx((.5,.3))
    for button in d.style_buttons.values(): button.setChecked(True)
    mark=window.doc.state.drawings[0].marks[0]
    assert mark.bold and mark.italic and mark.strikeout and mark.underline
    small=fitted_layout(mark,640/360)[0].pixelSize()
    d.begin(screen_point(d,.6,.4),1); assert d.selection.gesture=='resize_text'
    d.move(screen_point(d,.9,.7),1); d.finish()
    mark=window.doc.state.drawings[0].marks[0]
    assert mark.box==pytest.approx((.8,.6))
    assert fitted_layout(mark,640/360)[0].pixelSize()>small
    image=pixels(render_marks((replace(mark,color='#ff0000'),),640,360))
    assert image[:,:,3].max()>0 and image[:,:,0].max()>200
    assert not image[:35,:,3].any() and not image[:,:63,3].any()
    window.doc.save(tmp_path/'text.cadence')
    assert Document.load(tmp_path/'text.cadence').state.drawings==window.doc.state.drawings
    assert not hasattr(d,'enable') and d.enabled
    for name in ('brush','eraser','lasso','text'): assert not d.tool_actions[name].icon().isNull()

def test_old_tool_shortcuts_migrate(window):
    from preferences import defaults,validate
    data=defaults(window.action_registry)
    data['shortcuts'].pop('Outils/Texte')
    data['shortcuts']['Dessin/Texte Arial']='Ctrl+Alt+T'
    assert validate(data,window.action_registry)['shortcuts']['Outils/Texte']=='Ctrl+Alt+T'
