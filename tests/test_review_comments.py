# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from model import Document, State, Segment
from review_csv import ReviewRow, frame_number, load_csv, map_rows, merge_rows, write_csv
from review_otio import read_otio, write_otio
from session import read_session, write_snapshot
from test_drawing import application, window
from test_cadence180 import change, fake_media


def document(rate=24):
    doc=Document(rate)
    doc.state=State((Segment(None,0,100),),frame_markers=(0,9,20))
    return doc


def test_checkbox_accent_is_display_only(application):
    from PySide6.QtGui import QTextCursor
    from review_editor import BOLD, ReviewEditor
    from timeline_skin import AMBER

    editor = ReviewEditor()
    editor.load('🎬 ☐ Pose\n☑ Arc', ((5, 9, BOLD),))
    editor.show()
    application.processEvents()

    def colored_spans(block):
        return [(span.start, span.length, span.format.foreground().color().name())
                for span in block.layout().formats()]

    first = editor.document().begin()
    assert colored_spans(first) == [(3, 1, AMBER)]
    assert colored_spans(first.next()) == [(0, 1, AMBER)]
    image = editor.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    for position in (3, first.next().position()):
        cursor = QTextCursor(editor.document())
        cursor.setPosition(position)
        left = editor.cursorRect(cursor)
        cursor.movePosition(QTextCursor.NextCharacter)
        rect = left.united(editor.cursorRect(cursor))
        assert any(image.pixelColor(x, y).name() == AMBER
                   for y in range(round(rect.top()*scale), round((rect.bottom()+1)*scale))
                   for x in range(round(rect.left()*scale), round((rect.right()+1)*scale)))
    editor.toggle_box(3)
    application.processEvents()
    assert colored_spans(first) == [(3, 1, AMBER)]
    assert editor.toPlainText() == '🎬 ☑ Pose\n☑ Arc'
    assert editor.style_runs() == ((5, 9, BOLD),)
    editor.close()


def test_comment_lifetime_and_old_projects(tmp_path):
    doc=document()
    legacy=doc.to_data()
    del legacy['state']['marker_notes']
    assert Document.from_data(legacy).state.marker_notes==()
    doc.set_marker_note(9,10,'Réviser le geste')
    doc.rename_marker(9,'Contact')
    assert doc.format_version()==18
    target=tmp_path/'test.cadence'
    doc.save(target)
    assert Document.load(target).state==doc.state
    autosave=tmp_path/'last.json'
    write_snapshot(autosave,(doc.state,doc.media,doc.fps,doc.review,str(target),False),{})
    assert read_session(autosave)[1].state==doc.state
    doc.move_marker(9,95)
    assert doc.state.marker_notes==((95,5,'Réviser le geste'),)
    doc.commit('remove',replace(doc.state,frame_markers=(0,20)))
    assert not doc.state.marker_notes
    assert doc.undo() and doc.undo() and doc.state.marker_notes==((9,10,'Réviser le geste'),)


def test_review_panel_typed_text_duration_navigation(window,application):
    w=window
    tabs=w.drawing.inspector_tabs
    w.drawing.panel.show()
    tabs.setCurrentWidget(w.drawing.comments)
    panel=w.drawing.comments
    w.doc.commit('markers',replace(w.doc.state,frame_markers=(2,4)))
    w.seek(2)
    application.processEvents()
    assert panel.isVisible() and panel.text.isEnabled()
    panel.text.setFocus()
    QTest.keyClicks(panel.text,'Contact on hand')
    panel.duration.setValue(6)
    assert w.doc.state.marker_notes==((2,6,'Contact on hand'),)
    w.seek(4)
    panel.text.setPlainText('weight')
    w.seek(5)
    assert panel.text.toPlainText()=='Contact on hand' and panel.frame==2
    w.seek(8)
    assert panel.frame is None and panel.text.toPlainText()=='' and panel.add.isEnabled()
    panel.add.click()
    assert panel.frame==8 and 8 in w.doc.state.frame_markers


def test_comments_survive_retime_and_coincident_notes(fake_media):
    state=State((Segment('a',0,48),),frame_markers=(10,11),marker_notes=((10,5,'Arc'),(11,9,'Contact')))
    expanded,_=change(state,fake_media,target=12)
    assert expanded.marker_notes==((20,10,'Arc'),(22,18,'Contact'))
    collapsed,_=change(state,fake_media,target=240)
    assert collapsed.marker_notes==((1,1,'Arc\n\nContact'),)


@pytest.mark.parametrize('width,height',[(640,440),(1280,800)])
def test_review_editor_accessible_after_side_panel_glide(window,application,width,height):
    w=window
    w.workspaces.switch('read')
    w.resize(width,height)
    dock=w.drawing.panel
    dock.hide()
    w.doc.commit('marker',replace(w.doc.state,frame_markers=(0,)))
    w.seek(0)
    application.processEvents()
    w.studio.right_button.click()
    motion=w.studio.side_motion
    motion.setCurrentTime(motion.duration())
    application.processEvents()
    tabs=w.drawing.inspector_tabs
    panel=w.drawing.comments
    bar=tabs.tabBar()
    where=bar.tabRect(tabs.indexOf(panel))
    assert bar.rect().contains(where) and w.childAt(bar.mapTo(w,where.center())) is bar
    QTest.mouseClick(bar,Qt.LeftButton,pos=where.center())
    assert tabs.currentWidget() is panel and panel.text.isEnabled()
    viewport=panel.text.viewport()
    assert w.childAt(viewport.mapTo(w,viewport.rect().center())) is viewport
    QTest.mouseClick(viewport,Qt.LeftButton,pos=viewport.rect().center())
    QTest.keyClicks(panel.text,'Comment')
    assert w.doc.state.marker_notes==((0,1,'Comment'),)


def test_csv_cadence_keyframe_roundtrip_and_conform(tmp_path):
    doc=document(Fraction(24000,1001))
    doc.set_marker_note(9,10,'Épaule, puis "main"\n2e ligne ')
    doc.rename_marker(9,'Contact')
    path=tmp_path/'notes.csv'
    write_csv(path,doc)
    kind,rows=load_csv(path)
    assert rows[1]['Frame']=='10'
    restore=document(doc.fps)
    assert merge_rows(restore,map_rows(kind,rows,restore.fps,100))
    assert restore.state==doc.state
    assert not merge_rows(restore,map_rows(kind,rows,restore.fps,100))
    assert map_rows(kind,rows,doc.fps*2,200)[1].start==18
    assert map_rows(kind,rows,doc.fps*2,200)[1].duration==20


def test_csv_syncsketch_and_xstudio(tmp_path):
    a=tmp_path/'sync.csv'
    a.write_text('Item Name,Frame Number,Comment\nShot,101,Note\nShot,101,Reply\n',encoding='utf-8-sig')
    kind,rows=load_csv(a)
    doc=document()
    converted=map_rows(kind,rows,doc.fps,100,origin='101',destination=9)
    assert merge_rows(doc,converted) and doc.state.marker_notes==((9,1,'Note\n\nReply'),)
    assert not merge_rows(doc,converted)
    a.write_text('Subject,Notes,Start Frame,End Frame,Created,User Name,Note Type,Media Flag,Annotated,Image\nPose,Arc,01:00:00:06,01:00:00:09,,,,,false,a.jpg\n')
    kind,rows=load_csv(a)
    assert map_rows(kind,rows,Fraction(24),100,origin='01:00:00:00')==[ReviewRow(6,4,'Pose','Arc')]
    assert frame_number('00:01:00;02',Fraction(30000,1001))==1800
    with pytest.raises(ValueError):
        frame_number('00:01:00;00',Fraction(30000,1001))
    with pytest.raises(ValueError):
        map_rows(kind,rows,Fraction(24),100,origin='0')
    with pytest.raises(ValueError):
        map_rows('cadence',[{'FPS':'1e99999999'}],Fraction(24),100)


def test_otio_roundtrip_ranges_and_clip_trims(tmp_path):
    doc=document()
    doc.set_marker_note(9,5,'À revoir')
    doc.rename_marker(9,'Main')
    otio=tmp_path/'review.otio'
    write_otio(otio,doc,tmp_path/'movie.mp4')
    rows=read_otio(otio,doc.fps,100)
    assert rows==[ReviewRow(0,1,'',''),ReviewRow(9,5,'Main','À revoir'),ReviewRow(20,1,'','')]
    data=json.loads(otio.read_bytes())
    track=data['tracks']['children'][0]
    clip=track['children'][0]
    clip['markers']=track.pop('markers')
    clip['source_range']['start_time']['value']=10
    clip['source_range']['duration']['value']=20
    clip['markers'][1]['name']='Revised in RV'
    otio.write_text(json.dumps(data))
    assert read_otio(otio,48,100)==[ReviewRow(0,8,'Main','Revised in RV'),ReviewRow(20,2,'','')]


def opened_comments(w,application):
    w.drawing.panel.show()
    panel=w.drawing.comments
    w.drawing.inspector_tabs.setCurrentWidget(panel)
    w.doc.commit('markers',replace(w.doc.state,frame_markers=(2,6,10)))
    w.seek(2)
    application.processEvents()
    return panel


def test_review_selectors_use_qwidget_window(window,application):
    from PySide6.QtWidgets import QComboBox,QFileDialog
    from dialogs import DialogPresentation
    panel=opened_comments(window,application)
    dialog=QFileDialog(panel)
    dialog.setOption(QFileDialog.DontUseNativeDialog)
    dialog.setNameFilters(['Commentaires CSV (*.csv)','Marqueurs OpenTimelineIO (*.otio)'])
    dialog.show()
    application.processEvents()
    assert panel.window() is window
    DialogPresentation().center(dialog)
    combo=dialog.findChild(QComboBox,'fileTypeCombo')
    QTest.mouseClick(combo,Qt.LeftButton)
    QTest.keyClick(combo.view(),Qt.Key_Down)
    QTest.keyClick(combo.view(),Qt.Key_Return)
    assert dialog.selectedNameFilter().endswith('(*.otio)')
    dialog.close()


def test_review_marker_keys_and_ranges(window,application):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    panel=opened_comments(window,application)
    panel.items.setFocus()
    QTest.keyClick(panel.items,Qt.Key_Down)
    assert window.doc.state.position==6
    QTest.keyClick(panel.items,Qt.Key_Up)
    assert window.doc.state.position==2
    window.doc.set_marker_note(2,1,'Contact',((0,7,2),))
    window.doc.rename_marker(2,'Main')
    window.refresh()
    panel.set_range_mode(False)
    def choose_ranges():
        menu=QApplication.activePopupWidget()
        QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[1]).center())
    QTimer.singleShot(40,choose_ranges)
    panel.range_menu(panel.range_label,panel.range_label.rect().center())
    assert panel.range_stack.currentWidget() is panel.ranges
    edit=panel.ranges
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit,'5, 8, 12-20, 9')
    QTest.keyClick(edit,Qt.Key_Return)
    state=window.doc.state
    assert window.doc.state.position==5
    assert state.frame_markers==(5,6,8,9,10,12)
    assert state.marker_notes==((5,1,'Contact'),(8,1,'Contact'),(9,1,'Contact'),(12,9,'Contact'))
    assert state.marker_names==tuple((f,'Main') for f in (5,8,9,12))
    assert state.marker_styles==tuple((f,((0,7,2),)) for f in (5,8,9,12))
    with pytest.raises(ValueError):
        window.doc.set_marker_ranges(5,{10:2,8:1})
    assert window.doc.state is state
    panel.items.setFocus()
    QTest.keyClick(panel.items,Qt.Key_Delete)
    assert 5 not in window.doc.state.frame_markers
    assert window.doc.undo() and window.doc.state==state
    window.refresh()
    rect=panel.items.visualItemRect(panel.items.item(0))
    def choose_delete():
        menu=QApplication.activePopupWidget()
        QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
    QTimer.singleShot(40,choose_delete)
    panel.marker_menu(rect.center())
    assert 5 not in window.doc.state.frame_markers
    panel.set_range_mode(False)


def test_review_click_checkbox_and_format_undo(window,application,tmp_path):
    from PySide6.QtGui import QTextCursor
    from review_editor import BOLD,ITALIC,UNDERLINE,STRIKE
    panel=opened_comments(window,application)
    edit=panel.text
    edit.setPlainText('👋 Contact')
    cursor=edit.textCursor()
    cursor.setPosition(3)
    cursor.movePosition(QTextCursor.End,QTextCursor.KeepAnchor)
    edit.setTextCursor(cursor)
    for mask in (BOLD,ITALIC,UNDERLINE,STRIKE):
        QTest.mouseClick(panel.styles[mask],Qt.LeftButton)
    assert edit.style_runs()==((3,10,15),)
    QTest.mouseClick(panel.checkbox,Qt.LeftButton)
    assert edit.toPlainText()=='☐ 👋 Contact'
    start=QTextCursor(edit.document())
    leading=edit.cursorRect(start).center()
    start.movePosition(QTextCursor.NextCharacter)
    trailing=edit.cursorRect(start).center()
    QTest.mouseClick(edit.viewport(),Qt.LeftButton,pos=(leading+trailing)/2)
    assert edit.toPlainText()=='☑ 👋 Contact'
    assert window.doc.state.marker_styles==((2,((5,12,15),)),)
    assert window.doc.format_version()==19
    path=tmp_path/'comment.cadence'
    window.doc.save(path)
    assert Document.load(path).state==window.doc.state
    window.seek(6)
    assert not edit.toPlainText()
    window.seek(2)
    assert edit.toPlainText()=='☑ 👋 Contact' and edit.style_runs()==((5,12,15),)


def test_style_buttons_follow_mixed_selection_and_insertion_format(window,application):
    from PySide6.QtGui import QTextCursor
    from review_editor import BOLD, ITALIC
    panel=opened_comments(window,application)
    edit=panel.text
    window.doc.set_marker_note(2,1,'☐abCD',((1,3,BOLD),(3,5,ITALIC)))
    window.refresh()
    def select(start,end):
        cursor=edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end,QTextCursor.KeepAnchor)
        edit.setTextCursor(cursor)
    def checked(): return {style for style,button in panel.styles.items() if button.isChecked()}
    select(0,3)
    assert checked()=={BOLD}
    select(5,1)
    assert not checked()
    QTest.mouseClick(panel.styles[BOLD],Qt.LeftButton)
    assert checked()=={BOLD} and edit.style_runs()==((1,3,BOLD),(3,5,BOLD|ITALIC))
    select(1,5)
    QTest.keyClick(edit,Qt.Key_B,Qt.ControlModifier)
    assert not checked() and edit.style_runs()==((3,5,ITALIC),)
    select(0,1)
    assert not checked() and not any(button.isEnabled() for button in panel.styles.values())
    select(5,5)
    assert checked()=={ITALIC}
    QTest.mouseClick(panel.styles[BOLD],Qt.LeftButton)
    QTest.keyClicks(edit,'X')
    assert checked()=={BOLD,ITALIC} and edit.style_runs()[-1]==(5,6,BOLD|ITALIC)
    window.seek(6)
    assert not checked() and all(button.isEnabled() for button in panel.styles.values())
    window.seek(2)
    assert not checked() and edit.toPlainText()=='☐abCDX'


def test_styled_interchange_retime_project_and_snapshot(tmp_path,fake_media):
    doc=document()
    doc.set_marker_note(9,1,'👁 Pose',((3,7,3),))
    snapshot=tmp_path/'last.json'
    write_snapshot(snapshot,(doc.state,doc.media,doc.fps,doc.review,None,True),{})
    assert read_session(snapshot)[1].state==doc.state
    for kind in ('csv','otio'):
        path=tmp_path/('notes.'+kind)
        target=document()
        if kind=='otio':
            write_otio(path,doc,tmp_path/'shot.mp4')
            rows=read_otio(path,24,100)
        else:
            write_csv(path,doc)
            flavor,data=load_csv(path)
            assert data[1]['Notes']=='👁 Pose'
            rows=map_rows(flavor,data,24,100)
            data[1]['Notes']='New'
            assert not map_rows(flavor,data,24,100)[1].styles
        assert merge_rows(target,rows) and target.state==doc.state
        assert not merge_rows(target,rows)
    state=State((Segment('a',0,48),),frame_markers=(10,11),marker_notes=((10,5,'👁'),(11,8,'Oui')),
                marker_styles=((10,((0,2,1),)),(11,((0,3,2),))))
    collapsed,_=change(state,fake_media,target=240)
    assert collapsed.marker_notes==((1,1,'👁\n\nOui'),)
    assert collapsed.marker_styles==((1,((0,2,1),(4,7,2))),)


def test_range_parse_boundaries():
    from review_format import frame_ranges
    assert frame_ranges('5, 8, 10-20, 9',100)=={5:1,8:1,10:11,9:1}
    assert frame_ranges('0 - 29, 5–6',30)=={0:30,5:2}
    for value in ('','3-1','-1','0-30','2,,5','2-'):
        with pytest.raises(ValueError): frame_ranges(value,30)

def test_comment_editor_keeps_editing_shortcuts(window,application):
    panel=opened_comments(window,application)
    whole=window.doc.state.all_segments
    panel.text.setFocus()
    QTest.keyClicks(panel.text,'CV')
    QTest.keyClick(panel.text,Qt.Key_Home)
    QTest.keyClick(panel.text,Qt.Key_Delete)
    QTest.keyClick(panel.text,Qt.Key_End)
    QTest.keyClick(panel.text,Qt.Key_B,Qt.ControlModifier)
    QTest.keyClicks(panel.text,'B')
    assert panel.text.toPlainText()=='VB'
    assert panel.text.style_runs()==((1,2,1),)
    if application.platformName()=='offscreen':
        QTest.keyClick(panel.text,Qt.Key_A,Qt.ControlModifier)
        QTest.keyClick(panel.text,Qt.Key_C,Qt.ControlModifier)
        QTest.keyClick(panel.text,Qt.Key_End)
        QTest.keyClick(panel.text,Qt.Key_V,Qt.ControlModifier)
        assert panel.text.toPlainText()=='VBVB'
    assert window.doc.state.all_segments==whole and window.doc.state.position==2
    assert window.doc.state.frame_markers==(2,6,10)

def test_ranges_without_active_marker_and_visible_validation(window,application):
    panel=opened_comments(window,application)
    window.doc.commit('clear',replace(window.doc.state,frame_markers=()))
    window.refresh()
    panel.set_range_mode(True)
    edit=panel.ranges
    assert panel.frame is None and edit.isEnabled()
    def enter(value):
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit,value)
        QTest.keyClick(edit,Qt.Key_Return)
    enter('5, 8, 10-20, 9')
    state=window.doc.state
    assert state.frame_markers==(5,8,9,10) and state.marker_notes==((10,11,''),)
    assert window.doc.state.position==5 and panel.frame==5
    enter('3-')
    assert window.doc.state is state and edit.text()=='3-' and edit.isModified()
    assert edit.toolTip() and edit.accessibleDescription()==edit.toolTip()
    window.refresh()
    assert edit.text()=='3-'
    enter('8,9')
    assert window.doc.state is state and edit.text()=='8,9' and edit.toolTip()
    enter('1-3')
    assert window.doc.state.frame_markers==(1,8,9,10)
    assert not edit.toolTip() and edit.text()=='1-3'
    panel.set_range_mode(False)


def test_review_boxes_keep_normal_format_including_legacy_and_paste(window,application):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QTextCursor
    from review_editor import flags
    panel=opened_comments(window,application)
    edit=panel.text
    edit.load('👋☐ One\n☑ Two',((0,13,15),))
    assert edit.style_runs()==((0,2,15),(3,7,15),(9,13,15))
    edit.selectAll()
    for style in panel.styles:
        QTest.mouseClick(panel.styles[style],Qt.LeftButton)
    assert not edit.style_runs()
    for style in panel.styles:
        QTest.mouseClick(panel.styles[style],Qt.LeftButton)
    assert edit.style_runs()==((0,2,15),(3,7,15),(9,13,15))
    cursor=edit.textCursor()
    for pos in (2,8):
        cursor.setPosition(pos+1)
        assert not flags(cursor.charFormat())
    cursor.setPosition(2)
    cursor.setPosition(3,QTextCursor.KeepAnchor)
    edit.setTextCursor(cursor)
    QTest.keyClick(edit,Qt.Key_I,Qt.ControlModifier)
    assert not panel.styles[2].isChecked()
    edit.moveCursor(QTextCursor.End)
    mime=QMimeData()
    mime.setText('☐Paste')
    edit.insertFromMimeData(mime)
    cursor.setPosition(14)
    assert not flags(cursor.charFormat())
    assert edit.style_runs()[-1]==(14,19,15)
    old=document().to_data()
    old['state']['marker_notes']=[(9,1,'☐x☑'),(20,1,'☐')]
    old['state']['marker_styles']=[(9,[(0,3,15)]),(20,[(0,1,15)])]
    assert Document.from_data(old).state.marker_styles==((9,((1,2,15),)),)


def test_review_draft_validates_atomically_on_frame_and_ranges(window,application):
    panel=opened_comments(window,application)
    w=window
    w.seek(3)
    panel.set_range_mode(False)
    edit=panel.ranges
    assert panel.range_stack.currentWidget() is edit and edit.text()=='3'
    history=len(w.doc.undo_stack)
    panel.text.setFocus()
    QTest.keyClick(panel.text,Qt.Key_B,Qt.ControlModifier)
    QTest.keyClicks(panel.text,'Pose')
    assert w.doc.state.frame_markers==(2,6,10) and len(w.doc.undo_stack)==history
    w.seek(6)
    assert not panel.text.toPlainText()
    w.seek(4)
    assert panel.text.toPlainText()=='Pose' and edit.text()=='4'
    edit.setFocus()
    QTest.keyClick(edit,Qt.Key_Return)
    assert w.doc.state.position==4 and w.doc.state.marker_notes==((4,1,'Pose'),)
    assert w.doc.state.marker_styles==((4,((0,4,1),)),) and len(w.doc.undo_stack)==history+1
    w.seek(8)
    assert not panel.text.toPlainText()
    panel.set_range_mode(True)
    panel.text.setFocus()
    QTest.keyClicks(panel.text,'Hold')
    for expression in ('2, 12','12-13,16'):
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit,expression)
        QTest.keyClick(edit,Qt.Key_Return)
        if expression.startswith('2,'):
            assert panel.frame is None and panel.text.toPlainText()=='Hold' and edit.toolTip()
    assert w.doc.state.marker_notes==((4,1,'Pose'),(12,2,'Hold'),(16,1,'Hold'))
    assert len(w.doc.undo_stack)==history+2


def test_delete_review_rows_keeps_playhead_and_follows_next(window,application):
    panel=opened_comments(window,application)
    panel.items.setFocus()
    for frame,following in ((2,6),(6,10),(10,None)):
        assert panel.items.currentItem().data(Qt.UserRole)==frame
        QTest.keyClick(panel.items,Qt.Key_Delete)
        window.refresh()
        assert window.doc.state.position==2 and panel.frame==following
        assert frame not in window.doc.state.frame_markers
    assert panel.items.currentRow()==-1


def test_right_click_deletion_elsewhere_preserves_playhead(window,application):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    panel=opened_comments(window,application)
    target=panel.items.visualItemRect(panel.items.item(1)).center()
    QTest.mousePress(panel.items.viewport(),Qt.RightButton,pos=target)
    QTest.mouseRelease(panel.items.viewport(),Qt.RightButton,pos=target)
    def remove():
        menu=QApplication.activePopupWidget()
        QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
    QTimer.singleShot(20,remove)
    panel.marker_menu(target)
    assert window.doc.state.position==2 and window.doc.state.frame_markers==(2,10)
    assert panel.frame==10
    QTest.keyClick(panel.items,Qt.Key_Delete)
    assert panel.frame==2 and window.doc.state.position==2


@pytest.mark.parametrize('extension,stem',[('csv','contact'),('otio','retake'),('csv','scene.v1'),('otio','scene.v2'),('csv','note.CSV')])
def test_export_review_uses_complete_name(window,application,tmp_path,monkeypatch,extension,stem):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QComboBox,QFileDialog,QLineEdit
    from pathlib import Path
    from review_panel import CommentExportDialog
    panel=opened_comments(window,application)
    movie=tmp_path/'shot.mp4'
    movie.touch()
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args:(str(movie),''))
    def choose():
        dialog=QApplication.activeModalWidget()
        assert isinstance(dialog,CommentExportDialog)
        dialog.setDirectory(str(tmp_path))
        combo=dialog.findChild(QComboBox,'fileTypeCombo')
        if extension=='otio':
            QTest.mouseClick(combo,Qt.LeftButton)
            QTest.keyClick(combo.view(),Qt.Key_Down)
            QTest.keyClick(combo.view(),Qt.Key_Return)
        edit=dialog.findChild(QLineEdit,'fileNameEdit')
        edit.setFocus()
        QTest.keyClicks(edit,stem)
        QTest.keyClick(edit,Qt.Key_Return)
    QTimer.singleShot(30,choose)
    panel.export_file()
    path=tmp_path/(stem if Path(stem).suffix.lower()=='.'+extension else stem+'.'+extension)
    if extension=='csv': assert len(load_csv(path)[1])==3
    else: assert len(read_otio(path,24,30))==3


def test_otio_media_browser_preserves_selected_output_directory(window,application,tmp_path):
    from pathlib import Path
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QComboBox,QFileDialog,QLineEdit,QPushButton
    from review_panel import CommentExportDialog
    panel=opened_comments(window,application)
    output=tmp_path/'reviews'/'approved'/'shot.v3.otio'
    movie=tmp_path/'media'/'reference.mp4'
    output.parent.mkdir(parents=True)
    movie.parent.mkdir()
    movie.touch()
    def choose_movie():
        dialog=QApplication.activeModalWidget()
        assert isinstance(dialog,QFileDialog) and not isinstance(dialog,CommentExportDialog)
        field=dialog.findChild(QLineEdit,'fileNameEdit')
        field.setText(str(movie))
        QTest.keyClick(field,Qt.Key_Return)
    def choose_output():
        dialog=QApplication.activeModalWidget()
        dialog.setDirectory(str(tmp_path))
        combo=dialog.findChild(QComboBox,'fileTypeCombo')
        QTest.mouseClick(combo,Qt.LeftButton)
        QTest.keyClick(combo.view(),Qt.Key_Down)
        QTest.keyClick(combo.view(),Qt.Key_Return)
        field=dialog.findChild(QLineEdit,'fileNameEdit')
        field.setText(str(output.relative_to(tmp_path).with_suffix('')))
        QTimer.singleShot(30,choose_movie)
        QTest.mouseClick(dialog.movie_row.findChild(QPushButton),Qt.LeftButton)
        QTest.keyClick(field,Qt.Key_Return)
    QTimer.singleShot(35,choose_output)
    panel.export_file()
    reference=json.loads(output.read_bytes())['tracks']['children'][0]['children'][0]['media_references']['DEFAULT_MEDIA']
    assert reference['target_url']==movie.as_uri()
    assert list(tmp_path.rglob('*.otio'))==[output]
    previous=[]
    def cancel():
        dialog=QApplication.activeModalWidget()
        previous.append(Path(dialog.directory().absolutePath()))
        dialog.reject()
    QTimer.singleShot(35,cancel)
    panel.export_file()
    assert previous==[output.parent]


def test_export_compares_existing_file_after_suffix(window,application,tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QLineEdit,QMessageBox
    panel=opened_comments(window,application)
    target=tmp_path/'existing.csv'
    target.write_bytes(b'already exists')
    prompts=[]
    def choose():
        dialog=QApplication.activeModalWidget()
        dialog.setDirectory(str(tmp_path))
        edit=dialog.findChild(QLineEdit,'fileNameEdit')
        edit.setText('existing')
        def decline():
            question=QApplication.activeModalWidget()
            if isinstance(question,QMessageBox):
                prompts.append(question.text())
                question.button(QMessageBox.No).click()
        QTimer.singleShot(25,decline)
        dialog.accept()
        dialog.reject()
    QTimer.singleShot(25,choose)
    panel.export_file()
    assert prompts and 'existing.csv' in prompts[0]
    assert target.read_bytes()==b'already exists'


@pytest.mark.parametrize('format_name',['csv','otio'])
def test_old_extensionless_export_can_be_imported(window,application,tmp_path,monkeypatch,format_name):
    from PySide6.QtWidgets import QFileDialog
    panel=opened_comments(window,application)
    legacy=document()
    legacy.set_marker_note(9,2,'Reprise')
    path=tmp_path/'notes'
    if format_name=='otio':
        write_otio(path,legacy,tmp_path/'shot.mp4')
    else:
        write_csv(path,legacy)
    filters=[]
    def choose(_parent,_title,_folder,choices):
        filters.extend(choices.split(';;'))
        return str(path),filters[-1]
    monkeypatch.setattr(QFileDialog,'getOpenFileName',choose)
    panel.import_file()
    assert len(filters)==2 and filters[-1].endswith('(*)')
    assert (9,2,'Reprise') in window.doc.state.marker_notes
