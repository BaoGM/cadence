# SPDX-License-Identifier: GPL-3.0-only
"""Packaged end-to-end verification, invoked explicitly with --self-test DIR."""
import json,os,time
from pathlib import Path
from fractions import Fraction
from dataclasses import replace

def run(directory):
    output=Path(directory).resolve(); output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    os.environ['CADENCE_CACHE']=str(output/'cache')
    os.environ['CADENCE_PREFS']=str(output/'preferences.json')
    os.environ['TEMP']=str(output); os.environ['TMP']=str(output)
    import sys,av,ssl
    tls_context = ssl.create_default_context()
    assert tls_context.check_hostname and tls_context.verify_mode == ssl.CERT_REQUIRED
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from app import MainWindow,STYLE
    from model import Document,State,Segment
    from media import prepare_media,export_video,ffmpeg
    from ui_text import tr,language
    app=QApplication.instance() or QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    for font in ['arial.ttf','segoeui.ttf','segoeuib.ttf','consola.ttf','consolab.ttf','seguisym.ttf']:
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    source=Path(os.environ.get('CADENCE_SMOKE_MEDIA',str(Path(__file__).parent/'assets'/'Demonstration.mp4')))
    if not source.is_file(): raise FileNotFoundError('Set CADENCE_SMOKE_MEDIA to the test video supplied with the source archive.')
    media=prepare_media(source)
    doc=Document(Fraction(media['fps'])); doc.media={media['id']:media}; doc.state=State((Segment(media['id'],0,media['frames']),))
    win=MainWindow(); win.scrub_audio.set_enabled(False); win.show(); app.processEvents()
    assert win.workspaces.mode=='read' and {k for k,p in win.workspaces.panels.items() if not p.isHidden()}=={'timeline','transport','timecode'}
    win.grab().save(str(output/'accueil.png')); win.workspaces.switch('edit'); app.processEvents()
    assert all(not p.isHidden() for p in win.workspaces.panels.values())
    check_navigation_shortcuts(win)
    assert win.timeline.track_left()==win.timeline.width()-win.timeline.track_right()
    for panel in (win.transport_widget,win.timeline_panel):
        assert panel.x()==0 and panel.width()==win.width()
        assert win.edit_toolbar.geometry().bottom()<panel.y()
    win.install_doc(doc)
    try:
        assert not win.copy_audio.isChecked()
        win.select(24,48); win.cut_selection()
        assert doc.state.length==168
        win.undo(); assert doc.state.length==192
        win.redo(); assert doc.state.length==168
        win.seek(168); win.paste_selection(); assert doc.state.length==192
        assert any(s.media is None for s in doc.state.audio)
        win.link_tracks.setChecked(False); win.move_section(0,24,192,'audio'); win.undo(); win.redo();
        win.set_exposure(.5); win.toggle_flip('flip_h'); win.timeline.set_units('frames'); win.seek(30)
        end=time.time()+10
        while win.rendered_token!=win.token and time.time()<end: app.processEvents(); QTest.qWait(20)
        assert win.viewer.image is not None and win.rendered_token==win.token
        win.grab().save(str(output/'interface.png'))
        before=doc.state; win.duplicate_section(0,24); assert doc.state.length==216; win.undo(); assert doc.state==before
        doc.save(output/'verification.cadence')
        export_video(doc.state,doc.media,doc.fps,output/'verification.mp4',True)
        with av.open(str(output/'verification.mp4')) as c: count=sum(1 for f in c.decode(video=0))
        assert count==192
        # Exercise the bundled WASAPI extension and audio mux without opening a microphone.
        import shutil,wave,numpy as np
        from types import SimpleNamespace
        from capture_audio import mux_audio,pa
        if os.name=='nt': assert pa.get_portaudio_version()>0
        from clip_geometry import apply_geometry
        storage=np.zeros((350,640,3),np.uint8); capture_rgb=storage[:,:638]; capture_rgb[:,:,0]=230
        assert not capture_rgb.flags.c_contiguous
        fitted=apply_geometry(capture_rgb,Segment('capture',0,1),16/9)
        assert fitted.shape==(350,622,3) and fitted[175,311,0]==230
        mixed=output/'capture-audio-mix.mp4'; shutil.copyfile(output/'verification.mp4',mixed)
        tracks=[]
        for name,frequency in [('ordinateur',440),('microphone',880)]:
            wav=output/(name+'.wav'); rate=48000
            tone=(np.sin(np.arange(rate*2)/rate*2*np.pi*frequency)*5000).astype('<i2')
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(tone.tobytes())
            tracks.append(SimpleNamespace(path=wav,first_time=100.,error=None))
        mux_audio(mixed,tracks,100.)
        with av.open(str(mixed)) as c:
            assert len(c.streams.audio)==1 and sum(1 for _ in c.decode(video=0))==192
        with av.open(str(mixed)) as c:
            resample=av.AudioResampler(format='fltp',layout='mono',rate=48000)
            audio=np.concatenate([a.to_ndarray().ravel() for frame in c.decode(audio=0) for a in resample.resample(frame)])
        spectrum=abs(np.fft.rfft(audio[:rate])); assert spectrum[440]>100 and spectrum[880]>100
        # Exercise both preview decoders, all comparison layouts and the new controls in the executable.
        win.set_exposure(0)
        win.toggle_flip('flip_v'); assert doc.state.flip_h and doc.state.flip_v
        win.viewer.setFocus(); win.action_registry['Affichage/Réinitialiser le canvas'][0].trigger()
        assert not doc.state.flip_h and not doc.state.flip_v
        win.undo(); assert doc.state.flip_h and doc.state.flip_v
        win.redo(); assert not doc.state.flip_h and not doc.state.flip_v
        win.use_reference(media); win.compare_offset.setValue(12); win.seek(30)
        end=time.time()+10
        while win.rendered_token!=win.token and time.time()<end: app.processEvents(); QTest.qWait(20)
        assert win.viewer.reference_rgb is not None and win.rendered_token==win.token
        from comparison import MODES
        win.compare_enabled.setChecked(False); win.comparison_panel.hide()
        for index,(_,mode) in enumerate(MODES):
            win.compare_cycle_btn.click(); app.processEvents()
            assert win.compare_mode.currentData()==mode and win.viewer.comparing and win.comparison_panel.isHidden()
            win.grab().save(str(output/f'comparison-{mode}.png'))
            win.compare_controls.grab().save(str(output/f'buttons-{mode}.png'))
        win.compare_swap_btn.click(); assert win.viewer.compare_swapped and win.compare_cycle_btn.symbol=='front_b'
        win.compare_cycle_btn.click(); assert not win.viewer.comparing and not win.compare_swap_btn.isEnabled()
        win.compare_cycle_btn.click(); assert win.viewer.comparing and win.viewer.compare_mode=='horizontal'
        win.loop_btn.click(); assert win.playback_mode=='loop'
        win.loop_btn.grab().save(str(output/'loop-button.png'))
        win.loop_btn.click(); assert win.playback_mode=='once'
        doc.review=win.comparison_snapshot(); doc.save(output/'comparison.cadence')
        check_reference_sequence(win,media,output)
        win.compare_mode.setCurrentIndex(0); app.processEvents(); win.grab().save(str(output/'interface.png'))
        # Draw-over survives serialization and reaches the packaged FFmpeg export.
        from drawing import Mark,DrawingKey,active_key
        from PySide6.QtCore import QPointF,Qt
        win.compare_enabled.setChecked(False); win.seek(30)
        end=time.time()+10
        while win.rendered_token!=win.token and time.time()<end: app.processEvents(); QTest.qWait(20)
        win.set_panel('drawing',False); win.drawing.choose_tool('brush'); app.processEvents()
        assert win.drawing.panel.isHidden() and not win.drawing.panel_action.isChecked()
        win.doc.state=replace(win.doc.state,selection=(24,48)); win.refresh()
        v=win.viewer; center=QPointF(v.width()/2,v.height()/2)
        win.drawing.begin(center-QPointF(100,0),.25)
        for x in range(-90,101,10): win.drawing.move(center+QPointF(x,-35*__import__('math').sin(x/70)),(x+100)/250+.2)
        win.drawing.finish()
        key=active_key(doc.state.drawings,30); assert key and (key.start,key.end)==(24,48)
        assert len(key.marks)==1 and key.marks[0].pressure
        text=Mark(tool='text',points=((.1,.1,1),),size=.04,color='#ffb35e',text='Draw over · Cadence',box=(.7,.16),bold=True,italic=True)
        win.drawing.commit_key(replace(key,marks=key.marks+(text,)),'Texte de vérification')
        before_move=doc.state
        assert doc.move_range(0,24,192) and active_key(doc.state.drawings,6)
        doc.undo(); assert doc.state==before_move; win.refresh()
        assert doc.resize_drawing(24,24,50); assert doc.state.drawings[0].end==50
        doc.undo(); win.refresh()
        win.drawing.choose_tool('text')
        bounds=win.drawing.selection.geometry(text).boundingRect(); hit=bounds.center()
        def screen(x,y):
            size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); rect=win.drawing.a_rect(size)
            return QPointF(v.width()/2+rect.x()+x*rect.width(),v.height()/2+rect.y()+y*rect.height())
        win.drawing.begin(screen(hit.x(),hit.y()),1); assert win.drawing.selection.gesture=='translate'
        win.drawing.move(screen(hit.x()+.05,hit.y()+.05),1); win.drawing.finish()
        assert abs(doc.state.drawings[0].marks[-1].points[0][0]-.15)<.001
        win.undo()
        win.drawing.choose_tool('lasso')
        win.drawing.begin(screen(.3,.3),1)
        for x,y in ((.75,.3),(.75,.7),(.3,.7),(.3,.3)): win.drawing.move(screen(x,y),1)
        win.drawing.finish(); assert 0 in win.drawing.selection.indices
        assert win.action_registry['Dessin/Ajouter un marqueur'][1]=='S'
        doc.save(output/'draw-over.cadence'); assert Document.load(output/'draw-over.cadence').state.drawings==doc.state.drawings
        win.comparison_panel.hide(); app.processEvents(); win.grab().save(str(output/'draw-over.png'))
        export_state=replace(doc.state,segments=(Segment(media['id'],0,12),),audio_segments=(Segment(media['id'],0,12),),drawings=(DrawingKey(3,8,(text,Mark(tool='group',points=((0,0,1),),children=(Mark(points=((.5,.5,1),),size=.2,pressure=False),Mark(tool='eraser',points=((.5,.5,1),),size=.1,pressure=False))))),),position=0,selection=None)
        export_video(export_state,doc.media,doc.fps,output/'draw-over.mp4',False)
        with av.open(str(output/'draw-over.mp4')) as c: assert sum(1 for f in c.decode(video=0))==12
        win.drawing.selection.indices=(); win.clip_tools.activate('resize'); win.clip_tools.rect=__import__('PySide6.QtCore',fromlist=['QRectF']).QRectF(.1,.1,.8,.8)
        win.clip_tools.frame.angle=20; win.clip_tools.update_pending(); win.clip_tools.commit()
        assert win.doc.state.segments[win.clip_tools.index].placement==(.1,.1,.8,.8)
        assert win.doc.state.segments[win.clip_tools.index].rotation==20
        export_video(replace(export_state,segments=(replace(win.doc.state.segments[win.clip_tools.index],start=0,end=12),)),doc.media,doc.fps,output/'rotated-clip.mp4',False)
        win.undo()
        # New tools are exercised through the actual controller in the packaged app.
        win.select(48,72)
        for tool,a,b in [('arrow',(.12,.2),(.35,.42)),('rectangle',(.42,.2),(.62,.5)),('ellipse',(.7,.2),(.9,.5))]:
            win.drawing.choose_tool(tool); app.processEvents()
            win.drawing.begin(screen(*a),1); win.drawing.move(screen(*b),1)
            if tool=='rectangle': win.drawing.move(screen(b[0]-.08,b[1]+.04),1,Qt.KeyboardModifier.AltModifier|Qt.KeyboardModifier.ControlModifier)
            win.drawing.finish()
        shapes=active_key(doc.state.drawings,48)
        assert [m.tool for m in shapes.marks]==['arrow','rectangle','ellipse']
        assert abs(shapes.marks[1].angle)>1
        selection=win.drawing.selection; selection.indices=(0,1,2); selection.key_start=shapes.start; selection.source=doc.state.drawings
        win.clip_tools.activate('resize'); assert win.clip_tools.target=='drawing'
        win.clip_tools.frame.angle=25; win.clip_tools.rect=win.clip_tools.rect.translated(.01,.03); win.clip_tools.update_pending(); app.processEvents()
        win.grab().save(str(output/'selection-transform.png')); win.clip_tools.commit()
        shapes=active_key(doc.state.drawings,48); assert all(m.transform!=(1.,0.,0.,1.,0.,0.) for m in shapes.marks)
        doc.save(output/'vector-shapes.cadence'); assert Document.load(output/'vector-shapes.cadence').state.drawings==doc.state.drawings
        export_video(replace(export_state,drawings=(replace(shapes,start=3,end=8),)),doc.media,doc.fps,output/'vector-shapes.mp4',False)
        win.drawing.choose_tool('cursor'); assert not win.drawing.enabled
        win.drawing.panel.show(); app.processEvents()
        win.drawing.choose_tool('brush'); assert not win.drawing.panel.isHidden()
        win.drawing.choose_tool('cursor')
        end=time.time()+10
        while win.rendered_token!=win.token and time.time()<end: app.processEvents(); QTest.qWait(20)
        assert win.rendered_token==win.token
        win.grab().save(str(output/'vector-tools.png'))
        win.next_key_btn.click(); assert doc.state.position==24
        win.previous_key_btn.click(); assert doc.state.position==48
        win.action_registry['Lecture/Clé suivante'][0].trigger(); assert doc.state.position==24
        win.action_registry['Lecture/Clé précédente'][0].trigger(); assert doc.state.position==48
        win.drawing.visibility_action.trigger(); assert not win.drawing.visible.isChecked()
        win.drawing.visibility_action.trigger(); assert win.drawing.visible.isChecked() and not win.drawing.enabled
        win.workspaces.switch('read'); app.processEvents(); assert win.timeline.simple
        win.select(48,72); app.processEvents()
        menu=win.timeline.context_menu(QPointF(win.timeline.x_for(60),35))
        assert tr('Supprimer les clés') in [a.text() for a in menu.actions()]; menu.deleteLater()
        assert win.compare_cycle_btn.isVisible()
        win.compare_cycle_btn.click(); app.processEvents(); assert win.viewer.comparing and win.comparison_panel.isHidden()
        from PySide6.QtCore import QPoint
        strip=win.transport_widget.widget()
        center=win.transport_buttons.mapTo(strip,win.transport_buttons.rect().center()).x()
        assert abs(center-strip.rect().center().x())<=2
        assert win.volume.mapTo(strip,QPoint(win.volume.width(),0)).x()>=strip.width()-16
        assert strip.height()==42 and win.transport_widget.height()<=44
        assert not win.timecode_overlay.rect().isEmpty() and win.timecode_overlay.rect().height()==22
        assert win.timeline.x_for(0)==win.timeline.width()-win.timeline.x_for(doc.state.length)
        win.grab().save(str(output/'mode-lecture.png'))
        win.workspaces.switch('edit'); app.processEvents()
        from capture import CaptureDialog
        dialog=CaptureDialog(win); dialog.show(); app.processEvents(); dialog.grab().save(str(output/'capture-options.png')); dialog.reject()
        from preferences import ShortcutDialog
        from PySide6.QtWidgets import QTabWidget
        shortcuts=ShortcutDialog(win.action_registry,win.preferences,win); shortcuts.show(); app.processEvents()
        assert [shortcuts.tabs.tabText(i) for i in range(3)]==tr(['Préférences','Raccourcis','Vue et navigation'])
        assert shortcuts.language.currentData()=='fr' and not shortcuts.clear_on_exit.isChecked()
        assert 'Fichier/Options…' in win.action_registry and 'Édition/Raccourcis et navigation…' not in win.action_registry
        shortcuts.grab().save(str(output/'options-preferences.png'))
        shortcuts.tabs.setCurrentIndex(1); app.processEvents(); shortcuts.grab().save(str(output/'raccourcis-clavier.png'))
        shortcuts.tabs.setCurrentIndex(2); app.processEvents()
        shortcuts.grab().save(str(output/'raccourcis-canvas.png')); shortcuts.reject()
        from guide import fill_browser
        from PySide6.QtWidgets import QTextBrowser
        guide=QTextBrowser(); guide.resize(850,650); fill_browser(guide,win.action_registry); guide.show(); app.processEvents()
        assert ('Fichier > Options' if language()=='fr' else 'File > Options') in guide.toPlainText()
        guide.grab().save(str(output/'guide.png')); guide.close()
        win.drawing.choose_tool('text'); app.processEvents(); combo=win.drawing.font_combo
        from draw_fonts import FAMILIES
        from PySide6.QtGui import QFontInfo
        assert all(QFontInfo(combo.itemData(combo.findText(name),Qt.ItemDataRole.FontRole)).family()==name for name in FAMILIES)
        combo.showPopup(); app.processEvents(); combo.view().window().grab().save(str(output/'polices-libres.png')); combo.hidePopup()
        win.drawing.choose_tool('cursor')
        for entry in win.menuBar().actions():
            menu=entry.menu(); menu.popup(win.menuBar().mapToGlobal(QPoint(20,30))); app.processEvents()
            menu.grab().save(str(output/f'menu-{menu.title()}.png')); menu.hide()
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QContextMenuEvent
        visibility=win.library.isVisible(); context_checked=[]
        def choose_panel():
            menu=app.activePopupWidget()
            if menu is None: return
            try:
                menu.grab().save(str(output/'menu-panneaux.png'))
                action=next(a for a in menu.actions() if a.data()=='library')
                context_checked.append(action.isEnabled()); action.trigger()
            finally: menu.close()
        QTimer.singleShot(30,choose_panel)
        point=win.viewer.rect().center(); app.sendEvent(win.viewer,QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,win.viewer.mapToGlobal(point)))
        assert context_checked==[True] and win.library.isVisible()!=visibility
        win.library_action.trigger(); assert win.library.isVisible()==visibility
        assert not {'inspector','meta','status'} & win.panel_widgets().keys()
        popup=win.createPopupMenu(); assert popup.actions()[0].data()=='workspace_mode' and not win.viewer.toolTip(); popup.deleteLater()
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent,QKeyEvent
        from media import run_ffmpeg,PreviewReader
        t=win.timeline; win.workspaces.set_timeline_simple(True); app.processEvents()
        mode=win.workspaces.mode; panels={k:p.isHidden() for k,p in win.workspaces.panels.items()}
        menu=t.context_menu(QPointF(t.x_for(10),35)); action=next(a for a in menu.actions() if a.data()=='timeline_simple')
        action.trigger(); assert not t.simple and win.workspaces.mode==mode
        assert panels=={k:p.isHidden() for k,p in win.workspaces.panels.items()}
        action.trigger(); assert t.simple; menu.deleteLater()
        points={frame:QPointF(t.x_for(frame+.25),35) for frame in (10,25)}
        for kind,frame,mods in ((QEvent.Type.MouseButtonPress,10,Qt.KeyboardModifier.NoModifier),(QEvent.Type.MouseMove,25,Qt.KeyboardModifier.ShiftModifier)):
            if kind==QEvent.Type.MouseMove: app.sendEvent(t,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Shift,Qt.KeyboardModifier.ShiftModifier))
            point=points[frame]; button=Qt.MouseButton.LeftButton if kind==QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton
            app.sendEvent(t,QMouseEvent(kind,point,QPointF(t.mapToGlobal(point.toPoint())),button,Qt.MouseButton.LeftButton,mods))
        assert doc.state.position==25 and doc.state.selection==(10,26)
        end=time.monotonic()+5
        while win.rendered_token!=win.token and time.monotonic()<end: QTest.qWait(10)
        assert win.rendered_token==win.token
        app.sendEvent(t,QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Shift,Qt.KeyboardModifier.NoModifier))
        assert doc.state.selection is None and doc.state.position==25
        point=points[25]; app.sendEvent(t,QMouseEvent(QEvent.Type.MouseButtonRelease,point,QPointF(t.mapToGlobal(point.toPoint())),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
        assert win.drawing.ghost.value()==100 and win.preferences['preview_quality']=='native'
        tabs=win.drawing.panel.findChild(QTabWidget); tabs.setCurrentIndex(0); win.drawing.panel.show(); app.processEvents()
        spin=win.drawing.after; edit=spin.lineEdit(); previous=spin.value()
        QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(8,edit.height()//2))
        QTest.keyClicks(edit,'10'); assert spin.value()==previous
        QTest.keyClick(edit,Qt.Key.Key_Return); assert spin.value()==10 and spin.suffix()==''
        win.drawing.panel.grab().save(str(output/'pelures.png')); tabs.setCurrentIndex(0)
        source4k=output/'native4k.mp4'; run_ffmpeg(['-f','lavfi','-i','color=red:s=3840x2160:r=12:d=0.25','-c:v','libx264','-preset','ultrafast',str(source4k)])
        hd=prepare_media(source4k); reader=PreviewReader()
        try: assert reader.read(hd,0).shape==(2160,3840,3)
        finally: reader.close()
        low=prepare_media(source4k,quality='480p'); assert low['proxy_height']==480
        # Verify the actual packaged drawing menus and their shared edit routing.
        win.doc.state=replace(doc.state,drawings=(DrawingKey(2,6,(Mark(points=((.2,.3,1.),)),)),),position=20,selection=None)
        win.workspaces.set_timeline_simple(False); win.refresh(); baseline=doc.state
        menu=t.drawing_track.context_menu(t.x_for(3.25))
        next(a for a in menu.actions() if a.data()=='copy').trigger(); menu.deleteLater()
        assert doc.state==baseline and doc.drawing_clipboard_length==4
        win.drawing.clipboard_actions['cut'].trigger()
        # The menu command targets the playhead, which has no drawing here.
        assert doc.state==baseline
        menu=t.drawing_track.context_menu(t.x_for(3.25))
        next(a for a in menu.actions() if a.data()=='cut').trigger(); menu.deleteLater()
        assert not doc.state.drawings and doc.state.segments==baseline.segments and doc.state.audio==baseline.audio
        menu=t.drawing_track.context_menu(t.x_for(30.25))
        next(a for a in menu.actions() if a.data()=='paste').trigger(); menu.deleteLater()
        assert [(k.start,k.end) for k in doc.state.drawings]==[(30,34)]
        win.undo(); win.undo(); assert doc.state==baseline
        for title,filename in [('Dessin','drawing-menu.png'),('Outils','tools-menu.png')]:
            menu=next(a.menu() for a in win.menuBar().actions() if a.menu() and a.menu().title()==tr(title))
            menu.popup(win.mapToGlobal(QPoint(30,30))); app.processEvents(); menu.grab().save(str(output/filename)); menu.close()
        win.compare_enabled.setChecked(False); win.viewer.setFocus(); win.seek(6)
        win.drawing.onion.setChecked(True); win.drawing.before.setValue(3); win.drawing.after.setValue(3)
        win.drawing.visible.setChecked(True); win.play_completed=False; win.transport.set_volume(0)
        from PySide6.QtGui import QPainter,QImage
        def draw_preview():
            size=win.viewer.image.size(); image=QImage(size,QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image); painter.translate(size.width()/2,size.height()/2)
            try: win.drawing.paint(painter,size)
            finally: painter.end()
            return image
        paused=draw_preview(); win.toggle_play(); assert win.transport.running
        playing=draw_preview(); assert paused==playing
        assert playing.pixelColor(int(playing.width()*.2),int(playing.height()*.3)).alpha()>0
        playing.save(str(output/'onion-playback.png')); win.pause()
        for ev in (-10,10):
            win.set_exposure(ev); assert win.exp_spin.value()==ev and doc.state.exposure==ev
            path=output/f'exposure-{ev}.cadence'; doc.save(path); assert Document.load(path).state.exposure==ev
        win.set_exposure(0)
        result={'system_microphone_mix':True,'wasapi_bundled':os.name=='nt','trimmed_panels':True,'context_workspace_mode':True,'organized_menus':True,'panel_context_menu':True,'reset_mirrors':True,'comparison_buttons':True,'compact_playback_layout':True,'clip_geometry':True,'workspace_modes':True,'text_auto_fit':True,'linked_drawings':True,'drawing_resize':True,'lasso':True,'text_move':True,'cut_paste':True,'draw_over':True,'drawing_save_export':True,'duplicate_media':True,'comparison_modes':len(MODES),'dual_preview':True,'loop_toggle':True,'status':'passed' ,'frozen':bool(getattr(sys,'frozen',False)),'import_frames':media['frames'],'export_frames':count,'undo_redo':True,'exposure_export':True,'preview_rendered':True,'ffmpeg_bundled':Path(ffmpeg()).exists()}
        result.update(drawing_clipboard_menu=True,drawing_clipboard_undo=True)
        result.update(comparison_cycle_shortcut=True,key_step_toggle=True)
        result.update(reference_sequence=True,reference_project_format=15,simple_media_boundaries=True)
        result.update(drawing_panel_visibility_preserved=True,automatic_tablet_pressure=True)
        result.update(single_click_numeric_input=True)
        result.update(onion_during_playback=True,exposure_range=[-10,10])
        win.timeline.hover_x=win.timeline.x_for(12.5); assert win.timeline.hover_frame()==12
        win.timeline.grab().save(str(output/'timeline-hover.png')); win.timeline.hover_x=None
        def readout_mouse(widget,kind,point,mods=Qt.KeyboardModifier.NoModifier):
            button=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
            buttons=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            app.sendEvent(widget,QMouseEvent(kind,point,QPointF(widget.mapToGlobal(point.toPoint())),button,buttons,mods))
        win.drawing.choose_tool('cursor'); win.timeline.reset_view()
        for simple in (True,False):
            win.workspaces.set_timeline_simple(simple); app.processEvents(); t=win.timeline
            start=QPointF(t.x_for(10.25),35 if simple else 60); end=QPointF(t.x_for(24.25),start.y())
            readout_mouse(t,QEvent.Type.MouseButtonPress,start)
            readout_mouse(t,QEvent.Type.MouseMove,end,Qt.KeyboardModifier.ShiftModifier)
            assert t.frame_indicator()[0]==24 and doc.state.position==24 and doc.state.selection==(10,25)
            t.grab().save(str(output/f'timeline-selection-{simple}.png'))
            readout_mouse(t,QEvent.Type.MouseButtonRelease,end)
            t.hover_x=t.x_for(60.5); assert t.hover_frame()==60 and doc.state.position==24
            t.grab().save(str(output/f'timeline-hover-highlight-{simple}.png'))
            units=t.units; t.set_units('time')
            assert t.tick_label(24)=='00:01.000'
            t.grab().save(str(output/f'timeline-timecode-{simple}.png')); t.set_units(units); t.hover_x=None
        win.seek(12); v=win.viewer; point=QPointF(v.width()/2,v.height()/2)
        readout_mouse(v,QEvent.Type.MouseButtonPress,point)
        try:
            readout_mouse(v,QEvent.Type.MouseMove,point+QPointF(v.scrub_pixels*6,0))
            assert doc.state.position==18 and t.frame_indicator()[0]==18
            t.grab().save(str(output/'timeline-during-video-scrub.png'))
        finally: readout_mouse(v,QEvent.Type.MouseButtonRelease,point)
        assert not t.external_scrubbing
        result.update(active_frame_readout=True,hover_frame_highlight=True,readout_only_on_timeline=True)
        win.session.checkpoint(wait=True)
        from session import read_session
        snapshot,recovered=read_session(win.session.path)
        assert recovered.state==win.doc.state and recovered.project_path==win.doc.project_path
        assert snapshot['view']['onion']==win.drawing.onion.isChecked()
        result.update(session_snapshot=True,hover_frame=True)
        result.update(live_timeline_selection=True,dynamic_shift=True,timeline_mode_context=True,native_4k=True,preview_480p=True,onion_opacity_default=100)
        result.update(vector_tools=True,vector_export=True,cursor_tool=True,simple_timeline_selection=True,key_navigation_buttons=True,key_navigation_menu=True,drawing_visibility_menu=True)
        result.update(rotated_vector_export=True,bundled_free_font_families=len(FAMILIES),language=language(),options_tabs=3,guide=True,default_shortcuts=sum(bool(key) for action,key in win.action_registry.values()))
        result.update(first_launch_read=True,first_edit_all_panels=True,selection_transform=True,clip_rotation_export=True,project_format=11)
        audio_doc=Document()
        audio_items=[prepare_media(output/(name+'.wav')) for name in ('ordinateur','microphone')]
        audio_doc.append_media(audio_items)
        assert all(seg.media is None for seg in audio_doc.state.segments)
        assert all(seg.media in audio_doc.media for seg in audio_doc.state.audio)
        audio_doc.save(output/'audio-only.cadence')
        assert Document.load(output/'audio-only.cadence').state==audio_doc.state
        export_video(audio_doc.state,audio_doc.media,audio_doc.fps,output/'audio-only.mp4')
        with av.open(str(output/'audio-only.mp4')) as check:
            assert check.streams.audio and next(check.decode(video=0)).to_ndarray(format='rgb24').max()==0
        from export_dialog import ExportDialog
        from model import sample_at
        audio_export_dialog=ExportDialog(win,audio_doc)
        assert audio_export_dialog.defaultSuffix()=='wav' and len(audio_export_dialog.nameFilters())==5
        from PySide6.QtWidgets import QFileDialog,QLineEdit,QComboBox
        audio_export_dialog.show(); app.processEvents()
        assert audio_export_dialog.labelText(QFileDialog.DialogLabel.FileType)==tr('Type de fichier :')
        format_combo=audio_export_dialog.findChild(QComboBox,'fileTypeCombo')
        QTest.keyClick(format_combo,Qt.Key.Key_Home)
        QTest.keyClick(format_combo,Qt.Key.Key_Down); QTest.keyClick(format_combo,Qt.Key.Key_Down); app.processEvents()
        assert audio_export_dialog.findChild(QLineEdit,'fileNameEdit').text()==Path(audio_export_dialog.selectedFiles()[0]).name
        audio_export_dialog.grab().save(str(output/'export-dialog.png'))
        audio_export_dialog.close(); audio_export_dialog.deleteLater()
        result.update(export_dialog_labels=True,export_filename_only=True)
        from capture import CaptureDialog
        capture_check=CaptureDialog(win)
        assert callable(capture_check.cursor) and capture_check.include_cursor.isChecked()
        assert not any(c.isChecked() for c in (capture_check.include_cadence,capture_check.include_keyboard,capture_check.include_clicks))
        capture_check.show(); app.processEvents(); capture_check.reject(); capture_check.deleteLater()
        assert 'Fichier/Enregistrer' in win.action_registry and 'Fichier/Enregistrer le projet' not in win.action_registry
        from sync3d_dialog import SyncDialog
        sync_dialog=SyncDialog(win.sync3d,win); sync_dialog.show(); app.processEvents()
        assert sync_dialog.windowTitle()==tr('Synchronisation 3D') and not win.sync3d.enabled
        assert (Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'integrations/cadence_bridge.py').is_file()
        assert (Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'integrations/cadence_autostart.py').is_file()
        from PySide6.QtWidgets import QPlainTextEdit
        assert win.sync3d.host is None and sync_dialog.host.currentData() is None
        assert not sync_dialog.findChildren(QPlainTextEdit) and sync_dialog.height()<750
        for name in ('cadence_drawings.py','cadence_drawings_maya.py','cadence_drawings_blender.py'):
            assert (Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'integrations'/name).is_file()
        sync_dialog.host.setCurrentIndex(sync_dialog.host.findData('maya'))
        assert sync_dialog.drawing_mode.currentData()=='blue_pencil'
        sync_dialog.host.setCurrentIndex(sync_dialog.host.findData('blender'))
        assert sync_dialog.drawing_mode.currentData()=='native'
        sync_dialog.host.setCurrentIndex(0)
        assert win.action_registry['Synchronisation 3D/Envoyer les dessins'][1]=='Ctrl+Alt+D'
        assert win.action_registry['Synchronisation 3D/Activer la synchronisation'][1]=='Ctrl+Alt+S'
        assert not hasattr(sync_dialog,'align') and hasattr(sync_dialog,'adapt_all')
        assert 'Synchronisation 3D/Adapter la cadence du média courant…' in win.action_registry
        sync_dialog.grab().save(str(output/'sync3d-dialog.png')); sync_dialog.close(); sync_dialog.deleteLater()
        result.update(sync3d_controls=True,capture_cursor_fixed=True,save_action_renamed=True,sync3d_no_default_host=True,sync3d_compact_dialog=True)
        result.update(capture_inclusion_controls=True,manual_rate_adaptation=True,drawing_transfer_controls=True)
        for extension in ('wav','mp3'):
            exported_audio=output/('audio-only.'+extension)
            export_video(audio_doc.state,audio_doc.media,audio_doc.fps,exported_audio)
            with av.open(str(exported_audio)) as check:
                assert len(check.streams.audio)==1 and not check.streams.video
                assert sum(frame.samples for frame in check.decode(audio=0))==sample_at(audio_doc.state.length,audio_doc.fps)
        result.update(wav_export=True,mp3_export=True,export_formats=5)
        popup=win.createPopupMenu()
        assert {'timeline_simple','units_time','units_frames','add_marker','delete_markers','delete_keys'} <= {a.data() for a in popup.actions() if isinstance(a.data(),str)}
        popup.deleteLater()
        options=ShortcutDialog(win.action_registry,win.preferences,win);options.show();options.show_key('Dessin/Ajouter un marqueur');app.processEvents()
        assert set(options.key_tables)=={key.split('/',1)[0] for key in win.action_registry}
        options.grab().save(str(output/'shortcut-categories.png'));options.reject();options.deleteLater()
        result.update(audio_only_import=True,audio_only_export=True,audio_project_format=13,shortcut_categories=True,expanded_timeline_context=True)
        doc.saved_signature=None; labels=[]
        def dismiss_save_prompt():
            box=app.activeModalWidget(); box.activateWindow(); app.processEvents(); button=box.buttons['no']
            labels.append(button.text()); box.grab().save(str(output/'save-prompt.png')); QTest.keyClick(box,Qt.Key.Key_N)
        QTimer.singleShot(20,dismiss_save_prompt)
        assert win.confirm_discard() and labels==['&'+tr('Non')]
        from dialogs import ConfirmationDialog
        restore=ConfirmationDialog(win,tr('Restaurer la dernière session'),tr('Retrouver la session précédente ?'),'Demonstration.mp4')
        def decline_restore():
            restore.activateWindow(); app.processEvents(); restore.grab().save(str(output/'restore-prompt.png')); QTest.keyClick(restore,Qt.Key.Key_N)
        QTimer.singleShot(20,decline_restore); assert restore.exec()==2; restore.deleteLater()
        from PySide6.QtWidgets import QFileDialog
        browser=QFileDialog(win,tr('Ouvrir des vidéos'),str(source.parent)); browser.show(); app.processEvents()
        from PySide6.QtWidgets import QListView
        from PySide6.QtCore import QStandardPaths,QUrl
        sidebar=browser.findChild(QListView,'sidebar'); desktop=QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation))
        assert any(sidebar.model().index(row,0).data(Qt.UserRole+1)==desktop and sidebar.model().index(row,0).data()==tr('Bureau') for row in range(sidebar.model().rowCount()))
        browser.grab().save(str(output/'file-dialog.png')); browser.reject(); browser.deleteLater()
        def close_mode_options():
            dialog=app.activeModalWidget(); dialog.activateWindow(); app.processEvents(); dialog.grab().save(str(output/'mode-options.png'))
            QTest.keyClick(dialog,Qt.Key.Key_A if language()=='fr' else Qt.Key.Key_C)
        QTimer.singleShot(20,close_mode_options); win.workspaces.configure()
        def close_guide_window():
            dialog=app.activeModalWidget(); dialog.activateWindow(); app.processEvents(); dialog.grab().save(str(output/'guide-window.png')); QTest.keyClick(dialog,Qt.Key.Key_F if language()=='fr' else Qt.Key.Key_C)
        QTimer.singleShot(20,close_guide_window); win.help()
        def close_about_window():
            dialog=app.activeModalWidget(); dialog.activateWindow(); app.processEvents(); dialog.grab().save(str(output/'about-window.png')); QTest.keyClick(dialog,Qt.Key.Key_O)
        QTimer.singleShot(20,close_about_window); win.about()
        result.update(check_timecode_overlay(win))
        result.update(check_native_render())
        result.update(check_cadence_change(win,output))
        result.update(check_preview_options(win,output))
        result.update(check_review_tools(win,output))
        result.update(check_native_import(output))
        (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    finally:
        doc.saved_signature=doc.signature(); win.close(); app.processEvents()


def check_native_import(output):
    from PySide6.QtWidgets import QApplication
    from media import run_ffmpeg,prepare_media,PreviewReader
    from model import Segment,TimelinePCM
    from audio_jobs import AudioJobs
    source=output/'mixed-rate.avi'
    run_ffmpeg(['-f','lavfi','-i','testsrc=size=64x48:rate=30:duration=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','ffv1','-c:a','pcm_s16le',str(source)])
    media=prepare_media(source,Fraction(24),defer_audio=True)
    assert media['proxy']==str(source) and media['frames']==24 and media['direct_frames']==30 and media['audio_pending']
    reader=PreviewReader(); pcm=TimelinePCM((Segment(media['id'],0,24),),{media['id']:media},Fraction(24))
    jobs=AudioJobs(); ready=[]; failures=[]; jobs.ready.connect(ready.append); jobs.failed.connect(failures.append)
    try:
        assert reader.read(media,23).shape==(48,64,3) and reader.read(media,0).shape==(48,64,3)
        jobs.set_media([media]); deadline=time.monotonic()+15
        while jobs.active and time.monotonic()<deadline: QApplication.processEvents(); time.sleep(.01)
        assert not jobs.active and not failures and len(ready)==1
        assert not ready[0]['audio_pending'] and any(pcm.read(0,48000))
    finally: jobs.stop(); reader.close(); pcm.close()
    return dict(native_mixed_rates=True,background_audio=True)


def check_review_tools(window,output):
    import numpy as np
    from ui_text import tr
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    from engine import Transport
    from model import State,Segment
    w=window; w.pause(); w.request_frame=lambda:None
    w.viewer.comparing=False; w.viewer.ev=0; w.viewer.flip_h=False; w.viewer.flip_v=False
    w.viewer.geometry_segment=None; w.viewer.geometry_aspect=None
    w.doc.state=State((Segment('tone',0,24),))
    w.doc.fps=Fraction(24); w.doc.media={'tone':{'audio':str(output/'audition.s16'),'path':str(output/'audition.s16'),'name':'Tone','frames':24,'width':640,'height':360}}
    t=w.transport; t.set_volume(.08); t.start(w.doc.state,w.doc.media,w.doc.fps,'loop',1)
    try:
        QTest.qWait(120); sink=t.sink; device=t.device; started=t.started
        w.set_loop(False); assert t.running and t.sink is sink and t.device is device and t.started==started
        before=t.clock()[0]; QTest.qWait(120); assert t.clock()[0]>=before
        w.set_loop(True); assert t.running and t.passes==0 and t.device.passes==0 and t.sink is sink
    finally: w.pause()
    w.viewer.set_frame(np.full((360,640,3),[31,83,149],np.uint8))
    w.drawing.visible.setChecked(False); w.drawing.panel.hide(); w.drawing.choose_tool('picker')
    original=w.doc.state; w.drawing.sample(QPointF(w.viewer.width()/2,w.viewer.height()/2))
    assert w.drawing.wheel.color()=='#1f5395' and w.doc.state is original and not w.drawing.panel.isVisible()
    assert w.drawing.tool_actions['picker'].shortcut().toString()=='P'
    w.timeline.simple=True; w.doc.state=replace(w.doc.state,selection=(2,22)); w.refresh()
    w.timeline.set_units('frames'); assert w.timeline.selection_label()=='20 '+tr('img')
    w.timeline.grab().save(str(output/'selection-count.png'))
    w.timeline.set_units('time'); assert w.timeline.selection_label()=='00:00.833'
    w.timeline.grab().save(str(output/'selection-duration.png'))
    return dict(loop_change_uninterrupted=True,color_sampler=True,selection_measurement=True)


def check_preview_options(window,output):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer,QEventLoop
    from preferences import ShortcutDialog
    from ui_style import set_tooltips_enabled
    from scrub_audio import ScrubAudio
    from model import State,Segment,RATE
    import numpy as np
    app=QApplication.instance()
    dialog=ShortcutDialog(window.action_registry,window.preferences,window)
    dialog.tooltips.setChecked(False);data=dialog.collect();assert not data['tooltips'];window.apply_preferences(data)
    assert not app.cadence_tooltips.enabled
    dialog.show();app.processEvents();dialog.grab().save(str(output/'preferences.png'));dialog.reject();dialog.deleteLater()
    set_tooltips_enabled(True)
    path=output/'audition.s16';samples=(np.sin(np.arange(RATE)*2*np.pi*440/RATE)*1000).astype('<i2')
    path.write_bytes(np.repeat(samples[:,None],2,axis=1).tobytes())
    state=State((Segment('tone',0,24),));media={'tone':{'audio':str(path)}};player=ScrubAudio();player.set_volume(.1)
    processed=[]
    try:
        for frame in range(6):
            player.request(state,media,Fraction(24),frame)
            loop=QEventLoop();QTimer.singleShot(55,loop.quit);loop.exec()
            if player.sink:
                assert player.sink.error().name=='NoError' and player.streaming
                processed.append(player.sink.processedUSecs())
        if processed:assert all(b>a for a,b in zip(processed,processed[1:])) and processed[-1]>150000
        player.set_volume(0);assert not player.streaming
    finally:player.close()
    return dict(tooltips_option=True,continuous_audition=True,audition_output_available=bool(processed))


def check_cadence_change(window,output):
    import threading,av,numpy as np
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from media import run_ffmpeg,prepare_media,export_video
    from model import Document,State,Segment
    from cadence_change import build_change
    from cadence_dialog import CadenceDialog
    source=output/'cadence-source.mkv'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','ffv1','-c:a','pcm_s16le',str(source)])
    original=prepare_media(source,Fraction(24)); key=original['id']; document=Document()
    state=State((Segment(key,0,48),));document.media={key:original};document.state=state
    converted,media=build_change(state,document.media,document.fps,[(0,48,key)],30,'speed',True,'native',lambda *a:None,threading.Event())
    document.media=media;document.commit('cadence',converted);assert converted.length==38 and document.fps==24
    document.save(output/'cadence-changed.cadence');assert Document.load(output/'cadence-changed.cadence').state==converted
    document.undo();assert document.state==state;document.redo();assert document.state==converted
    export_video(converted,media,document.fps,output/'cadence-changed.mp4',False)
    with av.open(str(output/'cadence-changed.mp4')) as c: assert sum(1 for _ in c.decode(video=0))==38
    previous=window.doc;window.install_doc(document)
    dialog=CadenceDialog(window,[(0,38,converted.segments[0].media)]);dialog.show();QApplication.processEvents();dialog.grab().save(str(output/'cadence-dialog.png'));dialog.close();dialog.deleteLater()
    window.drawing.choose_tool('cursor');window.viewer.set_frame(np.zeros((90,160,3),np.uint8));window.viewer.setFocus();window.transport.set_volume(0)
    window.toggle_play();assert window.transport.running
    pos=QPoint(window.viewer.width()//2,window.viewer.height()//2)
    QTest.mousePress(window.viewer,Qt.MouseButton.LeftButton,pos=pos);assert not window.transport.running
    QTest.mouseRelease(window.viewer,Qt.MouseButton.LeftButton,pos=pos);assert window.transport.running
    window.pause();window.install_doc(previous)
    gap=Document();gap.state=State((Segment(None,0,10),Segment('b',0,10),Segment('a',0,4)))
    assert gap.move_range(20,24,0,leave_gap=True) and gap.state.segments[2]==Segment('b',0,10)
    return dict(media_cadence=True,cadence_export=True,cadence_project_format=14,scrub_resumes_playback=True,gap_fill=True)


def capture_surface(surface):
    from PySide6.QtTest import QTest
    for _ in range(2):
        surface.update(); QTest.qWait(30)
    return surface.grabFramebuffer()


def run_gpu(directory,renderer='opengl'):
    import sys,numpy as np
    output=Path(directory).resolve(); output.mkdir(parents=True,exist_ok=True)
    if sys.platform=='win32': os.environ['QT_QPA_PLATFORM']='windows'
    else: os.environ.setdefault('QT_QPA_PLATFORM','xcb')
    os.environ['CADENCE_RENDERER']=renderer
    if renderer=='direct3d': os.environ['CADENCE_RENDER_READBACK']='1'
    os.environ['CADENCE_PREFS']=str(output/'preferences.json'); os.environ['CADENCE_CACHE']=str(output/'cache')
    from video_surface import configure_graphics
    configure_graphics()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from app import MainWindow,STYLE
    from model import State,Segment
    from drawing import DrawingKey,Mark
    app=QApplication.instance() or QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    win=MainWindow(); win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    win.request_frame=lambda:None
    win.set_panel('timecode',False)
    try:
        win.doc.media={'test':dict(id='test',name='test',path='test.mp4',width=640,height=360,frames=30,fps='24')}
        mark=Mark(points=((.5,.5,1.),),size=.2,color='#00ff00',pressure=False)
        win.doc.state=State((Segment('test',0,30),),drawings=(DrawingKey(0,1,(mark,)),))
        win.refresh(); win.viewer.set_frame(np.full((360,640,3),[255,50,20],dtype=np.uint8)); win.show()
        from PySide6.QtCore import QEventLoop,QTimer
        waiting=QEventLoop(); timeout=QTimer(); timeout.setSingleShot(True)
        win.viewer.graphics_startup.ready.connect(waiting.quit); timeout.timeout.connect(waiting.quit)
        timeout.start(20000); waiting.exec(); timeout.stop()
        surface=win.viewer.surface
        assert surface is not None and surface.isValid(),win.viewer.renderer
        assert win.viewer.renderer==renderer,win.viewer.renderer
        assert surface.format().swapInterval()==1
        image=capture_surface(surface); color=image.pixelColor(image.width()//2,image.height()//2)
        image.save(str(output/'gpu-drawing.png'))
        assert color.green()>220 and color.red()<30,(image.size(),color.getRgb())
        if renderer=='direct3d': assert surface.compositor.drawing_stats()['textures']>0
        win.drawing.visible.setChecked(False); QTest.qWait(100); image=capture_surface(surface)
        color=image.pixelColor(image.width()//2,image.height()//2); assert color.red()>240 and color.green()<70
        v=win.viewer; point=QPointF(v.width()/2,v.height()/2)
        def mouse(kind,position):
            button=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
            buttons=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            app.sendEvent(v,QMouseEvent(kind,position,QPointF(v.mapToGlobal(position.toPoint())),button,buttons,Qt.KeyboardModifier.NoModifier))
        mouse(QEvent.Type.MouseButtonPress,point)
        try:
            mouse(QEvent.Type.MouseMove,point+QPointF(v.scrub_pixels*12,0)); QTest.qWait(50)
            assert win.timeline.frame_indicator()[0]==12 and capture_surface(surface)==image
            win.timeline.grab().save(str(output/'timeline-during-gpu-scrub.png'))
        finally: mouse(QEvent.Type.MouseButtonRelease,point)
        assert not win.timeline.external_scrubbing
        QTest.qWait(50); assert capture_surface(surface)==image
        win.set_panel('timecode',True)
        surface.hide(); surface.show(); win.resize(1200,800); QTest.qWait(200)
        assert surface.isValid() and not capture_surface(surface).isNull()
        def wipe_mark(y): return Mark(points=((.05,y,1.),(.95,y,1.)),size=.08,color='#ffffff',pressure=False)
        win.doc.state=replace(win.doc.state,position=10,drawings=(DrawingKey(8,9,(wipe_mark(.3),)),DrawingKey(10,11,(wipe_mark(.5),)),DrawingKey(12,13,(wipe_mark(.7),))))
        win.drawing.visible.setChecked(True); win.drawing.onion.setChecked(True); win.drawing.before.setValue(3); win.drawing.after.setValue(3); win.drawing.ghost.setValue(100)
        v.comparing=True; v.compare_mode='wipe'; v.wipe_position=.5
        v.reference_rgb=np.full((360,640,3),[20,40,80],dtype=np.uint8)
        v.set_frame(np.full((360,640,3),[40,70,90],dtype=np.uint8))
        for swapped in (False,True):
            v.compare_swapped=swapped; v.apply_effect(); QTest.qWait(80); image=capture_surface(surface)
            size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); dpr=image.width()/v.width()
            for x in (.25,.75):
                for y in (.3,.5,.7):
                    color=image.pixelColor(round((v.width()/2+(x-.5)*size.width())*dpr),round((v.height()/2+(y-.5)*size.height())*dpr))
                    if (x>.5) if swapped else (x<.5): assert color.red()>100,color.getRgb()
                    else: assert color.getRgb()[:3]==(20,40,80),color.getRgb()
            image.save(str(output/f'gpu-wipe-{swapped}.png'))
        win.drawing.visible.setChecked(False); QTest.qWait(80); image=capture_surface(surface)
        center_x,center_y=image.width()//2,image.height()//2
        handle=image.copy(center_x-round(8*dpr),center_y-round(12*dpr),round(16*dpr),round(24*dpr))
        handle.save(str(output/'gpu-wipe-handle.png'))
        blended=sum(100<handle.pixelColor(x,y).green()<210 for x in range(handle.width()) for y in range(handle.height()))
        assert blended>8,blended
        v.compare_mode='overlay'; v.compare_opacity=.37; v.ev=1.; v.apply_effect(); QTest.qWait(80)
        reference=v.cpu_preview(); expected=reference.pixelColor(reference.width()//2,reference.height()//2)
        displayed=capture_surface(surface); actual=displayed.pixelColor(displayed.width()//2,displayed.height()//2)
        assert max(abs(a-b) for a,b in zip(actual.getRgb()[:3],expected.getRgb()[:3]))<=1
        displayed.save(str(output/'gpu-native-overlay.png'))
        v.comparing=False
        overlay_checks=check_timecode_overlay(win)
        capture_surface(surface).save(str(output/'gpu-timecode.png'))
        v.cursor_guard.boundary(True)
        assert v.cursor().shape()==Qt.CursorShape.ArrowCursor
        v.cursor_guard.boundary(False)
        win.viewer.clear(); QTest.qWait(100); capture_surface(surface).save(str(output/'gpu-welcome.png'))
        result=dict(status='passed',frozen=bool(getattr(sys,'frozen',False)),renderer=win.viewer.renderer,swap_interval=surface.format().swapInterval(),drawings=True,resize=True,active_frame_readout=True,wipe_drawings_clipped=True,wipe_handle_smooth=True)
        result.update(overlay_checks)
        result.update(gpu_drawing_layers=True,cursor_outside_reset=True)
        result.update(check_native_cursor(win))
        result.update(check_native_render())
        (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    finally:
        win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()


def check_native_cursor(window):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    guard=window.viewer.cursor_guard; native=guard.native
    if os.name!='nt':
        assert native is None
        previous=guard.desired
        try:
            guard.set_cursor(Qt.CursorShape.CrossCursor)
            guard.boundary(True); assert window.viewer.cursor().shape()==Qt.CursorShape.ArrowCursor
            guard.boundary(False); assert window.viewer.cursor().shape()==Qt.CursorShape.CrossCursor
        finally: guard.set_cursor(previous)
        return dict(qt_cursor_boundary=True,native_cursor_boundary=False)
    import ctypes
    from ctypes import wintypes
    from unittest.mock import patch
    assert native is not None
    user32=native.user32
    user32.GetCursor.argtypes=[]; user32.GetCursor.restype=wintypes.HANDLE
    user32.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user32.SendMessageW.restype=wintypes.LPARAM
    guard.boundary(True); window.setCursor(Qt.CursorShape.ArrowCursor)
    previous=user32.SetCursor(user32.LoadCursorW(None,32649))
    try:
        with patch.object(QApplication,'widgetAt',return_value=window):
            hwnd=int(window.winId())
            assert user32.SendMessageW(hwnd,0x0020,hwnd,1)==1
            assert user32.GetCursor()==native.arrow
    finally: user32.SetCursor(previous)
    return dict(native_cursor_boundary=True)


def check_native_render():
    import numpy as np
    import native_render
    from comparison import compose
    from media import exposure_lut
    from drawing import Mark,render_marks
    from drawing_cache import DrawingRasterCache
    assert native_render.available()
    rng=np.random.default_rng(140)
    a=rng.integers(0,256,(130,171,3),dtype=np.uint8)[:,::2]
    b=rng.integers(0,256,a.shape,dtype=np.uint8)
    for mode in ('overlay','difference'):
        image=native_render.rgb_image(a,b,ev=.7,mode=mode,opacity=.37,gain=2.2,flip_h=True)
        actual=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(a.shape)
        expected=compose(exposure_lut(.7)[a][:,::-1],exposure_lut(.7)[b][:,::-1],mode,.37,2.2)
        assert np.array_equal(actual,expected)
    mark=Mark(points=((.1,.2,.2),(.8,.6,.9),(.4,.7,.5)),size=.04,opacity=.7)
    eraser=replace(mark,tool='eraser',size=.02,opacity=.5)
    marks=(mark,eraser)
    image=render_marks(marks,320,180)
    previous=os.environ.get('CADENCE_NATIVE_RENDER')
    try:
        os.environ['CADENCE_NATIVE_RENDER']='0'
        assert image==render_marks(marks,320,180)
    finally:
        if previous is None: os.environ.pop('CADENCE_NATIVE_RENDER',None)
        else: os.environ['CADENCE_NATIVE_RENDER']=previous
    cache=DrawingRasterCache(320*180*4)
    assert cache.render(marks,320,180)==image
    assert cache.render(marks,320,180)==image and cache.bytes<=cache.budget
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    origin,region=cache.render_region(marks,320,180)
    restored=QImage(image.size(),image.format()); restored.fill(Qt.GlobalColor.transparent)
    painter=QPainter(restored); painter.drawImage(*origin,region); painter.end()
    assert restored==image and not native_render.alpha_bounds(region).isEmpty()
    return dict(native_pixels=True,native_strokes=True,drawing_raster_cache=True,drawing_region_cache=True)



def check_reference_sequence(window,media,output):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from model import Document,Segment
    from reference_sequence import restore
    w=window; original=w.doc.state; offset=w.compare_offset.value()
    w.doc.state=replace(original,segments=(Segment(media['id'],0,media['frames']),)*2,audio_segments=None,position=0,selection=None)
    w.refresh(); w.compare_offset.setValue(0)
    w.set_reference_sequence([media,media]); w.seek(media['frames']+8)
    end=time.time()+10
    while w.rendered_token!=w.token and time.time()<end: QApplication.processEvents(); QTest.qWait(15)
    assert w.rendered_token==w.token and w.reference_index.locate(Fraction(media['frames']+8,1)/w.doc.fps)[2]==8
    assert w.viewer.reference_rgb is not None
    w.doc.review=w.comparison_snapshot(); path=output/'reference-sequence.cadence'; w.doc.save(path)
    restored=Document.load(path); assert restored.format_version()==15
    restore(restored,'native',lambda *_:None,lambda:False)
    w.restore_comparison(restored); assert len(w.reference_entries())==2
    assert len(w.timeline.media_boundaries())==1
    w.library_tabs.setCurrentIndex(w.reference_tab); QApplication.processEvents()
    w.library.grab().save(str(output/'reference-list.png'))
    w.doc.state=original; w.set_reference_sequence([media]); w.compare_offset.setValue(offset); w.refresh()


def check_navigation_shortcuts(window):
    from comparison import MODES
    window.viewer.setFocus()
    cycle=window.action_registry['Comparaison/Mode de comparaison suivant'][0]
    toggle=window.action_registry['Lecture/Basculer le pas clé / image'][0]
    for entry in window.menuBar().actions():
        assert cycle not in entry.menu().actions() and toggle not in entry.menu().actions()
    assert cycle.shortcut().toString()=='Shift+X' and toggle.shortcut().toString()=='K'
    assert not window.key_step
    toggle.trigger(); assert window.key_step and window.next_key_btn.symbol=='last'
    toggle.trigger(); assert not window.key_step and window.next_key_btn.symbol=='last'
    for _,mode in MODES:
        cycle.trigger(); assert window.compare_enabled.isChecked() and window.compare_mode.currentData()==mode
    cycle.trigger(); assert not window.compare_enabled.isChecked()
    window.compare_mode.setCurrentIndex(0)


def check_timecode_overlay(window):
    from PySide6.QtCore import Qt,QPointF,QEvent,QTimer
    from PySide6.QtGui import QMouseEvent,QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDockWidget
    v=window.viewer; overlay=window.timecode_overlay
    assert not any(p.objectName()=='timecode_widget' for p in window.findChildren(QDockWidget))
    old=overlay.position(); shown=not overlay.isHidden(); locked=overlay.locked; overlay.set_locked(False)
    window.set_panel('timecode',True); overlay.set_position([.5,1]); QApplication.processEvents()
    assert not overlay.rect().isEmpty()
    original=overlay.rect(); view=(v.zoom,v.angle,QPointF(v.pan))
    v.zoom=.1; v.angle=75; v.pan=QPointF(4000,-4000)
    assert overlay.rect()==original
    v.zoom,v.angle,v.pan=view
    before=window.doc.state; start=overlay.rect().center(); end=start+QPointF(20,-40)
    QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=start.toPoint())
    QApplication.sendEvent(v,QMouseEvent(QEvent.Type.MouseMove,end,v.mapToGlobal(end.toPoint()),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=end.toPoint())
    assert overlay.anchor.y()<1 and window.doc.state==before
    grab=lambda:capture_surface(v.surface) if v.renderer in ('opengl','direct3d') else v.grab().toImage()
    QTest.qWait(50); displayed=grab(); window.set_panel('timecode',False); QTest.qWait(50)
    assert displayed!=grab()
    window.set_panel('timecode',True); window.toggle_fullscreen(); QTest.qWait(50)
    assert not overlay.rect().isEmpty()
    for expected in (False,True):
        chosen=[]
        def toggle_lock():
            menu=QApplication.activePopupWidget()
            try:
                action=next(a for a in menu.actions() if a.data()=='timecode_lock')
                chosen.append((action.isChecked(),action.text())); action.trigger()
            finally: menu.close()
        point=overlay.rect().center().toPoint(); QTimer.singleShot(30,toggle_lock)
        QApplication.sendEvent(v,QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,v.mapToGlobal(point)))
        from ui_text import language
        label='Lock timecode position' if language()=='en' else 'Verrouiller la position du code temporel'
        assert chosen==[(expected,label)] and overlay.locked!=expected and window.video_fullscreen
    window.toggle_fullscreen(); overlay.set_position(old); overlay.set_locked(locked); window.set_panel('timecode',shown)
    return dict(timecode_overlay=True,timecode_drag=True,timecode_fullscreen=True,timecode_viewport_anchor=True,timecode_lock=True)


def run_updates(directory):
    import ssl
    import sys
    from updates import read_json, RELEASES_URL, select_release
    from app import VERSION
    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    releases = read_json(RELEASES_URL)
    assert isinstance(releases, list)
    for installed in (False, True):
        for previews in (False, True):
            select_release(releases, VERSION, installed, previews)
    result = dict(status='passed', frozen=bool(getattr(sys, 'frozen', False)),
                  tls=ssl.OPENSSL_VERSION, certificate_verification=True,
                  github_release_count=len(releases), version=VERSION)
    (output/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
