# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import math
import pytest
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtWidgets import QApplication
from test_drawing import application,window,screen_point,pixels
from test_tools0160 import mouse
from drawing import active_key,render_layer,Mark,DrawingKey,vector_path
from shape_gesture import ShapeGesture,rotate,add,sub,mul
from PySide6.QtGui import QKeyEvent,QFont,QFontInfo
from PySide6.QtWidgets import QInputDialog
from draw_fonts import FAMILIES
from preferences import defaults,validate

SHIFT=Qt.KeyboardModifier.ShiftModifier
CTRL=Qt.KeyboardModifier.ControlModifier
ALT=Qt.KeyboardModifier.AltModifier


@pytest.mark.parametrize('tool',['brush','eraser','arrow','rectangle','ellipse','text','lasso'])
def test_selected_range_scrub_then_activate_drawing(window,application,tool):
    w=window; w.request_frame=lambda:None; d=w.drawing
    w.select(3,9); w.viewer.scrub.emit(20)
    assert w.doc.state.selection==(3,9) and w.doc.state.position==20
    d.choose_tool(tool); application.processEvents()
    assert 3<=w.doc.state.position<9 and w.doc.state.selection==(3,9)
    if tool not in ('text','lasso','eraser'):
        d.begin(screen_point(d,.2,.2),1); d.move(screen_point(d,.5,.5),1)
        key=replace(d.stroke_key,marks=d.stroke_key.marks+(d.stroke,))
        assert pixels(render_layer((key,),w.doc.state.position,640,360))[:,:,3].any()
        d.finish(); assert active_key(w.doc.state.drawings,w.doc.state.position)


@pytest.mark.parametrize('tool',['arrow','rectangle','ellipse'])
def test_vector_modifiers_translate_center_and_rotate(tool):
    g=ShapeGesture(tool,(100.,100.)); g.update((180.,140.))
    a,b=g.a,g.b
    g.update((200.,170.),alt=True)
    assert g.a==add(a,(20,30)) and g.b==add(b,(20,30))
    center=mul(add(g.a,g.b),.5)
    g.update((220.,180.),ctrl=True)
    assert mul(add(g.a,g.b),.5)==pytest.approx(center)
    assert sub(g.b,g.a)==pytest.approx((120,60))
    pivot=g.a; size=sub(g.b,g.a); last=g.last
    g.update(add(pivot,rotate(sub(last,pivot),90)),ctrl=True,alt=True)
    assert g.a==pivot and sub(g.b,g.a)==pytest.approx(size) and g.angle==pytest.approx(90)
    # Return to resizing in the local coordinates of the rotated shape.
    end=g.last; g.update(add(end,(0,20)))
    assert sub(g.b,g.a)==pytest.approx((size[0]+20,size[1]))


@pytest.mark.parametrize('tool',['rectangle','ellipse'])
def test_shift_and_ctrl_shift_and_ctrl_alt_shift(tool):
    g=ShapeGesture(tool,(100.,100.)); g.update((160.,130.))
    g.update((180.,135.),shift=True)
    assert sub(g.b,g.a)==pytest.approx((80,80))
    center=mul(add(g.a,g.b),.5)
    g.update((170.,135.),shift=True,ctrl=True)
    assert sub(g.b,g.a)==pytest.approx((60,60))
    assert mul(add(g.a,g.b),.5)==pytest.approx(center)
    pivot=g.a; size=sub(g.b,g.a)
    g.update(add(pivot,rotate(sub(g.last,pivot),35)),shift=True,ctrl=True,alt=True)
    assert g.a==pivot and sub(g.b,g.a)==pytest.approx(size) and g.angle==pytest.approx(35)


def test_arrow_shift_snaps_direction_and_ctrl_keeps_center():
    g=ShapeGesture('arrow',(0.,0.)); g.update((100.,37.),shift=True)
    extent=sub(g.b,g.a)
    assert math.degrees(math.atan2(extent[1],extent[0]))==pytest.approx(15)
    center=mul(add(g.a,g.b),.5)
    g.update((130.,70.),shift=True,ctrl=True)
    assert mul(add(g.a,g.b),.5)==pytest.approx(center)
    angle=math.degrees(math.atan2(g.b[1]-g.a[1],g.b[0]-g.a[0]))
    assert angle/15==pytest.approx(round(angle/15))


@pytest.mark.parametrize('tool',['arrow','rectangle','ellipse'])
def test_modifier_events_preview_save_lasso_and_undo(window,application,tmp_path,tool):
    from model import Document
    w=window; w.request_frame=lambda:None; d=w.drawing; d.choose_tool(tool); application.processEvents()
    start=screen_point(d,.25,.25); end=screen_point(d,.5,.5)
    mouse(w.viewer,QEvent.Type.MouseButtonPress,start)
    mouse(w.viewer,QEvent.Type.MouseMove,end)
    QApplication.sendEvent(w.viewer,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Alt,ALT))
    before=d.stroke
    mouse(w.viewer,QEvent.Type.MouseMove,end+QPointF(25,10),ALT)
    assert sub(d.stroke.points[1][:2],d.stroke.points[0][:2])==pytest.approx(sub(before.points[1][:2],before.points[0][:2]))
    QApplication.sendEvent(w.viewer,QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Alt,Qt.KeyboardModifier.NoModifier))
    # Rotate through the controller, matching the preview geometry used by lasso/export.
    mouse(w.viewer,QEvent.Type.MouseMove,end+QPointF(45,-55),ALT|CTRL)
    assert abs(d.stroke.angle)>1
    mark=d.stroke; mouse(w.viewer,QEvent.Type.MouseButtonRelease,end+QPointF(45,-55),ALT|CTRL)
    assert len(w.doc.undo_stack)==1 and w.doc.state.drawings[0].marks==(mark,)
    path=tmp_path/'rotated.cadence'; w.doc.save(path); assert Document.load(path).state.drawings==w.doc.state.drawings
    before=vector_path(replace(mark,angle=0),640,360).boundingRect()
    after=vector_path(mark,640,360).boundingRect(); assert after!=before
    d.choose_tool('lasso'); bounds=d.selection.geometry(mark).boundingRect()
    assert bounds.width()>0 and bounds.height()>0
    w.undo(); assert not w.doc.state.drawings
    w.redo(); assert w.doc.state.drawings[0].marks==(mark,)


def test_alt_moves_new_text_box_and_existing_text(window,application,monkeypatch):
    d=window.drawing; window.request_frame=lambda:None; d.choose_tool('text'); application.processEvents()
    monkeypatch.setattr(QInputDialog,'getMultiLineText',lambda *a:('Texte libre',True))
    d.begin(screen_point(d,.2,.2),1); d.move(screen_point(d,.5,.4),1)
    before=d.pending_text_rect()
    d.move(screen_point(d,.6,.5),1,ALT); after=d.pending_text_rect()
    assert after.size()==before.size() and after.x()==pytest.approx(before.x()+.1)
    d.finish(); key=window.doc.state.drawings[0]; mark=key.marks[0]
    hit=d.selection.geometry(mark).boundingRect().center()
    d.begin(screen_point(d,hit.x(),hit.y()),1,modifiers=ALT)
    d.move(screen_point(d,hit.x()+.05,hit.y()+.04),1,ALT); d.finish()
    moved=window.doc.state.drawings[0].marks[0]
    assert moved.box==mark.box and moved.points[0][0]==pytest.approx(mark.points[0][0]+.05)
    window.undo(); assert window.doc.state.drawings[0].marks[0]==mark


def test_alt_during_text_handle_resize_translates_box(window,application):
    w=window; w.request_frame=lambda:None; d=w.drawing
    mark=Mark(tool='text',points=((.2,.2,1),),text='Texte',box=(.3,.2))
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(0,10,(mark,)),)); d.choose_tool('text'); application.processEvents()
    d.select_text(0,w.doc.state.drawings[0]); corner=d.selection.geometry(mark).boundingRect().bottomRight()
    d.begin(screen_point(d,corner.x(),corner.y()),1)
    assert d.selection.gesture=='resize_text'
    d.move(screen_point(d,corner.x()+.1,corner.y()+.1),1,ALT); d.finish()
    moved=w.doc.state.drawings[0].marks[0]
    assert moved.box==pytest.approx(mark.box) and moved.points[0][:2]==pytest.approx((.3,.3))


def test_rotated_forms_and_free_font_reach_export(application,tmp_path):
    import subprocess,av,numpy as np
    from fractions import Fraction
    from model import State,Segment
    from media import ffmpeg,prepare_media,export_video
    from drawing import render_marks
    from draw_fonts import load_fonts
    load_fonts(); source=tmp_path/'source.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=black:s=320x180:r=12:d=1','-c:v','libx264',str(source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media=prepare_media(source)
    marks=(Mark(tool='rectangle',points=((.35,.1,1),(.7,.3,1)),angle=35,size=.02,color='#ff0000'),Mark(tool='text',points=((.1,.65,1),),text='Été libre',font_family='Dancing Script',box=(.8,.25),color='#ffffff',bold=True))
    state=State((Segment(media['id'],0,12),),drawings=(DrawingKey(2,9,marks),))
    target=tmp_path/'rotated-font.mp4'; export_video(state,{media['id']:media},Fraction(12),target)
    with av.open(str(target)) as container: frames=[f.to_ndarray(format='rgb24') for f in container.decode(video=0)]
    expected=pixels(render_marks(marks,320,180))
    assert len(frames)==12
    for i,frame in enumerate(frames):
        if 2<=i<9:
            opaque=expected[:,:,3]>240
            assert np.mean(abs(frame[opaque].astype(float)-expected[:,:,:3][opaque]))<25
        else: assert frame.max()<8


def test_fonts_have_live_samples_and_keep_existing_text(window,application):
    d=window.drawing; combo=d.font_combo
    assert [combo.itemText(i) for i in range(combo.count())]==list(FAMILIES)
    for family in FAMILIES:
        font=combo.itemData(combo.findText(family),Qt.ItemDataRole.FontRole)
        assert font.family()==family and QFontInfo(font).family()==family
    assert combo.currentFont().family()=='Noto Sans'
    mark=Mark(tool='text',points=((.2,.2,1),),text='Arial conservé',box=(.4,.2))
    window.doc.state=replace(window.doc.state,drawings=(DrawingKey(0,10,(mark,)),)); window.request_frame=lambda:None
    d.choose_tool('text'); d.select_text(0,window.doc.state.drawings[0]); d.read_text_style(mark)
    assert combo.currentFont().family()=='Arial'
    combo.setCurrentFont(QFont('Comic Neue'))
    assert window.doc.state.drawings[0].marks[0].font_family=='Comic Neue'
    window.undo(); assert window.doc.state.drawings[0].marks[0].font_family=='Arial'


def test_moved_draw_menu_preserves_shortcut_and_transport_centers(window,application):
    w=window; menus={a.text():a.menu() for a in w.menuBar().actions()}
    action=w.action_registry['Affichage/Afficher les outils de dessin'][0]
    assert action in menus['Affichage'].actions() and action not in menus['Dessin'].actions()
    data=defaults(w.action_registry); data['shortcuts'].pop('Affichage/Afficher les outils de dessin')
    data['shortcuts']['Dessin/Afficher les outils de dessin']='Ctrl+Alt+D'
    assert validate(data,w.action_registry)['shortcuts']['Affichage/Afficher les outils de dessin']=='Ctrl+Alt+D'
    w.workspaces.switch('read'); application.processEvents(); strip=w.transport_widget.widget()
    for widget in (w.transport_buttons,w.workspaces.toggle,w.volume,w.media_info):
        center=widget.mapTo(strip,widget.rect().center()).y()
        assert abs(center-strip.rect().center().y())<=8
        assert widget.mapTo(strip,widget.rect().topLeft()).y()>=0
        assert widget.mapTo(strip,widget.rect().bottomRight()).y()<strip.height()
