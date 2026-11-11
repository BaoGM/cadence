# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import json,subprocess
import numpy as np
import pytest,av
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QLabel,QCheckBox,QPushButton
from test_drawing import application,window,screen_point,pixels
from drawing import Mark,DrawingKey,render_marks,active_key,translate_mark
from draw_ui import TOOL_SPECS
from model import Document,State,Segment
from media import prepare_media,export_video,ffmpeg

def mouse(widget,kind,point,mods=Qt.KeyboardModifier.NoModifier):
    button=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    event=QMouseEvent(kind,point,QPointF(widget.mapToGlobal(point.toPoint())),button,buttons,mods)
    QApplication.sendEvent(widget,event)

def test_simple_timeline_range_draw_delete_and_undo(window,application):
    w=window; w.request_frame=lambda:None; w.workspaces.switch('read'); application.processEvents(); t=w.timeline
    shift=Qt.KeyboardModifier.ShiftModifier
    mouse(t,QEvent.Type.MouseButtonPress,QPointF(t.x_for(2.25),35),shift)
    mouse(t,QEvent.Type.MouseMove,QPointF(t.x_for(10.25),35),shift)
    mouse(t,QEvent.Type.MouseButtonRelease,QPointF(t.x_for(10.25),35),shift)
    assert w.doc.state.selection==(2,11) and t.selection_track=='video'
    color=t.grab().toImage().pixelColor(round(t.x_for(6)),40); assert color.green()>color.red()
    d=w.drawing; d.choose_tool('brush'); application.processEvents()
    d.begin(screen_point(d,.2,.3),1); d.move(screen_point(d,.5,.3),1); d.finish()
    assert t.simple and w.workspaces.mode=='read' and [(k.start,k.end) for k in w.doc.state.drawings]==[(2,11)]
    menu=t.context_menu(QPointF(t.x_for(6),35)); actions=menu.actions(); titles=[a.text() for a in actions]
    assert titles[:2]==['Code temporel','Images'] and actions[titles.index('Supprimer l’audio')+1].isSeparator()
    assert actions[titles.index('Supprimer les clés')-1].isSeparator()
    actions[titles.index('Supprimer les clés')].trigger(); assert not w.doc.state.drawings and w.doc.state.length==30
    w.undo(); assert w.doc.state.drawings
    actions[titles.index('Supprimer le média')].trigger(); assert w.doc.state.length==21 and not w.doc.state.drawings
    w.undo(); assert w.doc.state.length==30 and w.doc.state.drawings; menu.deleteLater()
    # Regular dragging returns to scrub, clearing the range.
    mouse(t,QEvent.Type.MouseButtonPress,QPointF(t.x_for(15.25),35)); mouse(t,QEvent.Type.MouseButtonRelease,QPointF(t.x_for(15.25),35))
    assert w.doc.state.position==15 and w.doc.state.selection is None

def test_tools_auto_activation_and_clean_panels(window,application):
    w=window; d=w.drawing
    assert not d.enabled and d.tool.currentData()=='cursor' and not hasattr(d,'enable')
    w.set_panel('drawing',False); application.processEvents()
    for title,name,key in TOOL_SPECS:
        d.tool_actions[name].trigger(); assert d.tool.currentData()==name and d.enabled==(name!='cursor')
        assert d.panel.isHidden() and not d.panel_action.isChecked()
        assert d.tool_buttons[name].isChecked() and not d.tool_actions[name].icon().isNull()
        assert w.action_registry['Outils/'+title][1]==key
    w.set_panel('drawing',True); application.processEvents()
    for title,name,key in TOOL_SPECS:
        d.tool_actions[name].trigger(); assert not d.panel.isHidden() and d.panel_action.isChecked()
    d.choose_tool('cursor'); assert not d.enabled
    w.clip_tools.activate('crop'); assert w.clip_tools.mode=='crop' and not d.enabled
    d.choose_tool('brush'); assert w.clip_tools.mode is None and d.enabled
    texts=[obj.text() for obj in d.panel.findChildren(QLabel)+d.panel.findChildren(QCheckBox)+d.panel.findChildren(QPushButton)]
    for old in ('DRAW OVER · calque de dessins','Activer le calque · D','CLÉS · images du montage','Souris : pression constante','Sur la sélection','Pression → taille'):
        assert old not in texts
    assert d.onion.text()=='Activer la pelure d’oignon' and not hasattr(w,'compare_status')
    assert 'Dessin/Activer le calque' not in w.action_registry

@pytest.mark.parametrize('tool',['brush','eraser','arrow','rectangle','ellipse'])
def test_shift_horizontal_drag_changes_size_without_drawing(window,application,tool):
    w=window; d=w.drawing; d.choose_tool(tool); application.processEvents(); d.size.setValue(40)
    v=w.viewer; point=screen_point(d,.5,.5); shift=Qt.KeyboardModifier.ShiftModifier
    mouse(v,QEvent.Type.MouseButtonPress,point,shift)
    mouse(v,QEvent.Type.MouseMove,point+QPointF(40,0),shift)
    assert d.size.value()==pytest.approx(60) and not d.stroke
    mouse(v,QEvent.Type.MouseMove,point-QPointF(20,0),shift)
    assert d.size.value()==pytest.approx(30)
    mouse(v,QEvent.Type.MouseButtonRelease,point-QPointF(20,0),shift)
    assert d.size_drag is None and v.cursor().shape()==Qt.CursorShape.CrossCursor
    assert not w.doc.state.drawings and not w.doc.undo_stack

@pytest.mark.parametrize('tool',['arrow','rectangle','ellipse'])
def test_vector_shape_style_lasso_serialization_and_history(window,application,tmp_path,tool):
    w=window; d=w.drawing; w.request_frame=lambda:None; w.select(3,8)
    d.choose_tool(tool); d.wheel.set_color('#ff0000'); d.size.setValue(10); d.opacity.setValue(60); application.processEvents()
    d.begin(screen_point(d,.2,.2),.1); d.move(screen_point(d,.6,.7),.9,Qt.KeyboardModifier.ShiftModifier); d.finish()
    key=w.doc.state.drawings[0]; mark=key.marks[0]
    assert (key.start,key.end)==(3,8) and mark.tool==tool and len(mark.points)==2 and not mark.pressure
    assert mark.size==pytest.approx(10/360) and mark.color=='#ff0000' and mark.opacity==.6
    if tool!='arrow': assert abs(mark.points[1][0]-mark.points[0][0])*640==pytest.approx(abs(mark.points[1][1]-mark.points[0][1])*360)
    image=pixels(render_marks((mark,),640,360)); assert 145<=image[:,:,3].max()<=155 and image[:,:,0].max()==255 and not image[:,:,1].any()
    d.choose_tool('lasso'); d.begin(screen_point(d,.1,.1),1)
    for pt in ((.8,.1),(.8,.9),(.1,.9),(.1,.1)): d.move(screen_point(d,*pt),1)
    d.finish(); assert d.selection.indices==(0,)
    center=d.selection.bounds().center(); d.begin(screen_point(d,center.x(),center.y()),1)
    d.move(screen_point(d,center.x()+.05,center.y()+.04),1); d.finish()
    moved=w.doc.state.drawings[0].marks[0]
    assert moved.points[0][0]==pytest.approx(mark.points[0][0]+.05)
    w.undo(); assert w.doc.state.drawings[0].marks[0]==mark
    w.redo(); assert w.doc.state.drawings[0].marks[0]==moved
    path=tmp_path/(tool+'.cadence'); w.doc.save(path); assert json.loads(path.read_text())['version']==11
    assert Document.load(path).state.drawings==w.doc.state.drawings

def test_key_navigation_buttons_and_delete_shortcut(window,application):
    w=window; w.request_frame=lambda:None; marks=(Mark(points=((.2,.2,1),)),)
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(2,5,marks),DrawingKey(12,14,marks),DrawingKey(22,25,marks)),position=22); w.refresh()
    w.next_key_btn.click(); assert w.doc.state.position==2
    w.previous_key_btn.click(); assert w.doc.state.position==22
    w.previous_key_btn.click(); assert w.doc.state.position==12
    playback=next(a.menu() for a in w.menuBar().actions() if a.text()=='Lecture')
    for title,expected in [('Clé précédente',2),('Clé suivante',12)]:
        action=w.action_registry['Lecture/'+title][0]
        assert action in playback.actions()
        action.trigger(); assert w.doc.state.position==expected
    action,key=w.action_registry['Dessin/Supprimer les clés']; assert key=='D'
    action.trigger(); assert [k.start for k in w.doc.state.drawings]==[2,22] and w.doc.state.length==30
    w.undo(); assert [k.start for k in w.doc.state.drawings]==[2,12,22]


def test_drawing_visibility_menu_stays_in_sync(window,application):
    d=window.drawing; action=d.visibility_action
    assert action.isChecked() and d.visible.isChecked() and not d.enabled
    action.trigger(); assert not action.isChecked() and not d.visible.isChecked() and not d.enabled
    d.visible.setChecked(True); assert action.isChecked()
    d.choose_tool('brush'); action.trigger()
    assert not action.isChecked() and d.enabled
    d.choose_tool('cursor'); action.trigger()
    assert action.isChecked() and d.visible.isChecked() and not d.enabled


def test_escape_cancels_brush_size_gesture(window,application):
    w=window; d=w.drawing; d.choose_tool('brush'); application.processEvents(); d.size.setValue(40)
    point=screen_point(d,.5,.5); shift=Qt.KeyboardModifier.ShiftModifier
    mouse(w.viewer,QEvent.Type.MouseButtonPress,point,shift)
    mouse(w.viewer,QEvent.Type.MouseMove,point+QPointF(40,0),shift)
    assert d.size.value()==60
    w.action_registry['Édition/Effacer la sélection / quitter le plein écran'][0].trigger()
    assert d.size.value()==40 and d.size_drag is None and not w.doc.state.drawings

def test_shapes_export_exact_range_and_existing_projects(application,tmp_path):
    source=tmp_path/'black.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=black:s=320x180:r=12:d=1','-c:v','libx264',str(source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media=prepare_media(source)
    marks=tuple(Mark(tool=tool,points=((.15+i*.2,.2,1),(.3+i*.2,.7,1)),size=.03,color='#ff0000',pressure=False) for i,tool in enumerate(('arrow','rectangle','ellipse')))
    state=State((Segment(media['id'],0,12),),drawings=(DrawingKey(3,8,marks),))
    output=tmp_path/'shapes.mp4'; export_video(state,{media['id']:media},Fraction(12),output)
    with av.open(str(output)) as f: frames=[frame.to_ndarray(format='rgb24') for frame in f.decode(video=0)]
    assert len(frames)==12
    for i,frame in enumerate(frames):
        red=(frame[:,:,0].astype(int)-frame[:,:,1].astype(int)>80).sum()
        assert (red>400) if 3<=i<8 else (red==0)
    doc=Document(); doc.media={media['id']:media}; doc.state=replace(state,drawings=()); path=tmp_path/'old.cadence'; doc.save(path)
    old=json.loads(path.read_text()); old['version']=8; path.write_text(json.dumps(old)); assert Document.load(path).state==doc.state

def test_reset_panel_layout_preserves_project_and_other_mode(window,application):
    w=window; original=w.doc.state; w.request_frame=lambda:None
    read_profile=dict(w.workspaces.profiles['read'])
    w.layout_action.trigger(); w.library.show(); w.drawing.panel.show(); w.header.hide()
    w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,w.timeline_panel)
    w.comparison_panel.setFloating(True); application.processEvents()
    assert not any(label.text()=='\u22ee\u22ee' for label in w.findChildren(QLabel))
    w.reset_layout_action.trigger(); application.processEvents()
    assert not w.layout_editable and not w.comparison_panel.isFloating()
    assert w.dockWidgetArea(w.timeline_panel)==Qt.DockWidgetArea.BottomDockWidgetArea
    assert w.dockWidgetArea(w.header)==Qt.DockWidgetArea.TopDockWidgetArea
    assert not w.library.isHidden() and not w.drawing.panel.isHidden() and not w.header.isHidden()
    assert w.workspaces.profiles['read']==read_profile and w.doc.state==original
    view=next(a.menu() for a in w.menuBar().actions() if a.text()=='Affichage')
    assert view.actions()[-1] is w.reset_layout_action and view.actions()[-2].isSeparator()
    w.workspaces.switch('read'); w.header.show(); w.timeline_panel.hide(); w.reset_panel_layout(); application.processEvents()
    assert w.timeline.simple and not w.timeline_panel.isHidden() and w.header.isHidden()

def test_new_tool_shortcuts_preserve_older_custom_keys(window):
    from preferences import defaults,validate
    data=defaults(window.action_registry)
    data['shortcuts'].pop('Outils/Flèche')
    data['shortcuts']['Lecture/Image suivante']='A'
    data['shortcuts'].pop('Outils/Curseur')
    data['shortcuts']['Dessin/Activer le calque']='Ctrl+Alt+D'
    data['shortcuts'].pop('Lecture/Clé suivante')
    data['shortcuts']['Dessin/Clé suivante']='Ctrl+Alt+K'
    current=validate(data,window.action_registry)
    assert current['shortcuts']['Lecture/Image suivante']=='A' and current['shortcuts']['Outils/Flèche']==''
    assert current['shortcuts']['Outils/Curseur']=='Ctrl+Alt+D'
    assert current['shortcuts']['Lecture/Clé suivante']=='Ctrl+Alt+K'
