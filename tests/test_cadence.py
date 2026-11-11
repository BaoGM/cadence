# SPDX-License-Identifier: GPL-3.0-only
import os,sys,time,tempfile
from pathlib import Path
from fractions import Fraction
from dataclasses import replace
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Document,State,Segment,slice_segments,locate,sample_at,TimelinePCM
from media import prepare_media,PreviewReader,export_video,exposure_lut,ffmpeg,exposure_filter


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch,tmp_path):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'))

def expanded(segments): return [i for s in segments for i in range(s.start,s.end)]

def test_edits_and_history():
    d=Document(); d.state=State((Segment('a',0,100),))
    d.select(20,30); d.copy(); d.delete()
    assert expanded(d.state.segments)==list(range(20))+list(range(30,100))
    d.state=replace(d.state,position=90); d.paste()
    assert expanded(d.state.segments)==list(range(20))+list(range(30,100))+list(range(20,30))
    d.undo(); d.clipboard=(Segment('a',90,95),); d.redo()
    assert expanded(d.state.segments)[-10:]==list(range(20,30))
    d.undo(); d.undo(); assert expanded(d.state.segments)==list(range(100))
    d.redo(); d.select(0,1); d.delete(); assert not d.redo_stack

@pytest.mark.parametrize('fps',[Fraction(24),Fraction(25),Fraction(30000,1001)])
def test_pcm_edit_boundaries(tmp_path,fps):
    total=sample_at(80,fps)
    data=np.repeat((np.arange(total,dtype=np.int64)%30000).astype('<i2')[:,None],2,axis=1)
    audio=tmp_path/'audio.s16'; audio.write_bytes(data.tobytes())
    segments=(Segment('a',0,7),Segment('a',20,30),Segment('a',3,8))
    pcm=TimelinePCM(segments,{'a':{'audio':str(audio)}},fps)
    result=np.frombuffer(pcm.read(0,pcm.samples),dtype='<i2').reshape(-1,2)
    assert len(result)==sample_at(22,fps)
    assert result[sample_at(7,fps),0]==data[sample_at(20,fps),0]
    assert result[sample_at(17,fps),0]==data[sample_at(3,fps),0]
    # Reading in arbitrary device blocks must be identical to a whole read.
    streamed=b''.join(pcm.read(i,337) for i in range(0,pcm.samples,337))
    assert streamed==result.tobytes(); pcm.close()

def test_exposure_identity():
    assert np.array_equal(exposure_lut(0),np.arange(256,dtype=np.uint8))
    assert exposure_lut(1)[100]>100 and exposure_lut(-1)[100]<100

def test_exposure_ffmpeg_parity(tmp_path):
    import subprocess
    rgb=np.repeat(np.arange(256,dtype=np.uint8)[:,None],3,axis=1).reshape(1,256,3)
    for ev in [-10,-2,-.25,1,2,10]:
        proc=subprocess.run([ffmpeg(),'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','256x1','-i','pipe:0','-vf',exposure_filter(ev),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],input=rgb.tobytes(),capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert proc.returncode==0,proc.stderr.decode()
        out=np.frombuffer(proc.stdout,dtype=np.uint8).reshape(rgb.shape)
        assert np.max(np.abs(out.astype(int)-exposure_lut(ev)[rgb].astype(int)))<=1

@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    root=tmp_path_factory.mktemp('media')
    os.environ['CADENCE_CACHE']=str(root/'cache')
    m=prepare_media(Path(__file__).resolve().parents[1]/'assets'/'Demonstration.mp4')
    return m,root

def test_import_and_precise_seek(prepared):
    m,_=prepared
    assert m['frames']==192
    assert Path(m['audio']).stat().st_size==sample_at(192,Fraction(24))*4
    reader=PreviewReader(); first=reader.read(m,0)
    last=reader.read(m,191); middle=reader.read(m,45)
    assert not np.array_equal(first,last) and not np.array_equal(first,middle)
    assert np.array_equal(first,reader.read(m,0)); reader.close()

def test_edited_export(prepared):
    import av
    m,root=prepared; fps=Fraction(24)
    state=State((Segment(m['id'],0,24),Segment(m['id'],48,72),Segment(m['id'],0,12)))
    target=root/'export.mp4'; export_video(state,{m['id']:m},fps,target,False)
    with av.open(str(target)) as c:
        frames=list(c.decode(video=0))
        assert len(frames)==60
        assert frames[0].width==960 and frames[0].height==540
    # Compare each splice with the corresponding source, allowing codec loss.
    with av.open(m['path']) as c: original=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    for out_index,src_index in [(0,0),(23,23),(24,48),(47,71),(48,0),(59,11)]:
        arr=frames[out_index].to_ndarray(format='rgb24')
        assert np.mean(np.abs(arr.astype(float)-original[src_index]))<3
    with av.open(str(target)) as c:
        a=c.streams.audio[0]
        duration=float(a.duration*a.time_base)
        assert abs(duration-2.5)<.025
        audio=np.concatenate([f.to_ndarray() for f in c.decode(audio=0)],axis=1)
        assert np.max(np.abs(audio))>.1

def test_project_roundtrip(prepared,tmp_path):
    m,_=prepared; d=Document(); d.media={m['id']:m}; d.state=State((Segment(m['id'],7,31),),1.25,8,(2,5))
    path=tmp_path/'edit.cadence'; d.save(path); loaded=Document.load(path)
    assert loaded.state==d.state and not loaded.dirty

def test_ui_smoke(prepared,tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    from PySide6.QtGui import QFontDatabase
    for font in ['segoeui.ttf','segoeuib.ttf','consola.ttf','consolab.ttf','seguisym.ttf']:
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    win=MainWindow(); win.show()
    m,_=prepared; doc=Document(); doc.media={m['id']:m}; doc.state=State((Segment(m['id'],0,192),)); doc.saved_signature=doc.signature(); win.install_doc(doc)
    try:
        deadline=time.time()+5
        while win.rendered_token!=win.token and time.time()<deadline: app.processEvents(); QTest.qWait(20)
        assert win.viewer.image is not None
        win.select(24,48); win.copy_selection(); win.delete_selection(); assert win.doc.state.length==168
        win.undo(); assert win.doc.state.length==192
        win.redo(); assert win.doc.state.length==168
        win.seek(168); win.paste_selection(); assert win.doc.state.length==192
        win.set_exposure(.75); assert win.doc.state.exposure==.75
        win.undo(); assert win.doc.state.exposure==0
        win.redo(); assert win.doc.state.exposure==.75
        win.seek(30)
        deadline=time.time()+5
        while win.rendered_token!=win.token and time.time()<deadline: app.processEvents(); QTest.qWait(20)
        assert win.rendered_token==win.token,getattr(win,'last_notice','')
        from media import PreviewReader
        reader=PreviewReader(); assert np.array_equal(win.viewer.rgb,reader.read(m,54)); reader.close()
        win.grab().save(str(tmp_path/'ui.png'))
        screenshot=Path(__file__).parent/'ui-preview.png'; win.grab().save(str(screenshot))
    finally:
        win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()

def test_pcm_repeat_device(prepared):
    from engine import PCMDevice
    m,_=prepared; pcm=TimelinePCM((Segment(m['id'],0,192),),{m['id']:m},Fraction(24))
    a,b,start=sample_at(24,Fraction(24)),sample_at(36,Fraction(24)),sample_at(30,Fraction(24))
    device=PCMDevice(pcm,start,a,b,3)
    actual=[]
    while not device.finished: actual.append(device.readData(1332))
    expected=pcm.read(start,b-start)+pcm.read(a,b-a)*2
    assert b''.join(actual)==expected
    device.close(); pcm.close()

def test_transport_count_and_pause(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from engine import Transport
    app=QApplication.instance() or QApplication([])
    m,_=prepared; state=State((Segment(m['id'],0,192),),loop_range=(0,6))
    t=Transport(); t.start(state,{m['id']:m},Fraction(24),'count',3)
    deadline=time.time()+4; saw_passes=set()
    try:
        QTest.qWait(100); app.processEvents(); before=t.clock(); t.hold(); QTest.qWait(130); t.resume()
        while time.time()<deadline:
            app.processEvents(); frame,passnum,done=t.clock(); saw_passes.add(passnum)
            if done: break
            QTest.qWait(10)
        assert done and passnum==3 and frame==5
        assert 2 in saw_passes
        print('audio_device=',t.has_audio_device,'passes=',saw_passes)
    finally: t.stop()

def test_silent_fractional_media(tmp_path):
    from media import run_ffmpeg
    import av
    path=tmp_path/'silent.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=size=160x90:rate=30000/1001:duration=2','-an','-c:v','libx264','-pix_fmt','yuv420p',str(path)])
    m=prepare_media(path); assert Fraction(m['fps'])==Fraction(30000,1001)
    assert not m['has_audio'] and not any(Path(m['audio']).read_bytes())
    state=State((Segment(m['id'],3,17),Segment(m['id'],21,43)),1)
    target=tmp_path/'fractional.mp4'; export_video(state,{m['id']:m},Fraction(m['fps']),target,True)
    with av.open(str(target)) as c: assert sum(1 for _ in c.decode(video=0))==36
    with av.open(str(target)) as c: assert abs(float(c.streams.audio[0].duration*c.streams.audio[0].time_base)-36/float(Fraction(m['fps'])))<.03

def test_audio_offset(tmp_path):
    from media import run_ffmpeg
    path=tmp_path/'offset.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=c=blue:size=160x90:rate=24:duration=2','-itsoffset','0.5','-f','lavfi','-i','sine=frequency=900:sample_rate=48000:duration=1','-c:v','libx264','-c:a','aac',str(path)])
    m=prepare_media(path)
    audio=np.fromfile(m['audio'],dtype='<i2').reshape(-1,2)
    assert np.max(np.abs(audio[:20000].astype(int)))<30
    assert np.max(np.abs(audio[30000:40000].astype(int)))>1000

def test_export_cancellation_preserves_destination(prepared,tmp_path):
    import threading
    from media import Cancelled
    m,_=prepared; target=tmp_path/'existing.mp4'; target.write_bytes(b'previous-output')
    cancel=threading.Event(); cancel.set()
    with pytest.raises(Cancelled): export_video(State((Segment(m['id'],0,192),)),{m['id']:m},Fraction(24),target,cancel=cancel)
    assert target.read_bytes()==b'previous-output'


def test_progress_completion_reentrant():
    """Modal QProgressDialog.setValue can dispatch completion synchronously."""
    from types import SimpleNamespace
    from app import MainWindow
    events=[]
    window=SimpleNamespace(dialog=None)
    class CompletingDialog:
        def setLabelText(self,text):
            assert window.dialog is self
            events.append(('label',text))
        def setValue(self,value):
            events.append(('value',value))
            window.dialog=None
    window.dialog=CompletingDialog()
    MainWindow.task_progress(window,1.0,'Terminé')
    assert events==[('label','Terminé'),('value',100)]
    MainWindow.task_progress(window,1.0,'Signal tardif')
    assert len(events)==2


def test_multi_source_rate_audio_and_flip_export(prepared,tmp_path):
    import av
    from media import run_ffmpeg
    m,_=prepared
    second=tmp_path/'second.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=size=320x240:rate=30:duration=1','-f','lavfi','-i','sine=frequency=1200:sample_rate=48000:duration=1','-c:v','libx264','-c:a','aac',str(second)])
    m2=prepare_media(second,Fraction(24)); assert m2['frames']==24
    doc=Document(); doc.append_media([m,m2]); assert doc.state.length==216
    doc.undo(); assert doc.state.length==0
    doc.redo(); assert doc.state.length==216
    doc.state=replace(doc.state,segments=(Segment(m['id'],0,6),Segment(m2['id'],0,24)),audio_segments=None,flip_h=True,flip_v=True)
    project=tmp_path/'multi.cadence'; doc.save(project); assert Document.load(project).state==doc.state
    pcm=TimelinePCM(doc.state.segments,doc.media,doc.fps)
    assert pcm.read(12000,48000)==Path(m2['audio']).read_bytes(); pcm.close()
    output=tmp_path/'multi.mp4'; export_video(doc.state,doc.media,doc.fps,output,False)
    with av.open(str(output)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(frames)==30 and frames[-1].shape==(540,960,3)
    with av.open(m['path']) as c: original=next(c.decode(video=0)).to_ndarray(format='rgb24')
    assert np.mean(np.abs(frames[0].astype(float)-original[::-1,::-1]))<3
    # The appended source is visibly different and pillarboxed to the first source canvas.
    assert np.mean(np.abs(frames[6].astype(float)-frames[5]))>20
    with av.open(str(output)) as c:
        assert abs(float(c.streams.audio[0].duration*c.streams.audio[0].time_base)-1.25)<.03


def test_view_controls_and_scrub(prepared,tmp_path):
    from PySide6.QtWidgets import QApplication,QPushButton
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QPoint
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE)
    win=MainWindow(); win.show(); m,_=prepared
    doc=Document(); doc.append_media([m]); win.install_doc(doc)
    original_scrub=win.viewer.scrub_pixels
    try:
        deadline=time.time()+5
        while win.rendered_token!=win.token and time.time()<deadline: app.processEvents(); QTest.qWait(10)
        assert win.viewer.image is not None
        assert not any(b.text() in ('Copier','Coller','Supprimer','↶ Annuler','↷ Rétablir') for b in win.findChildren(QPushButton))
        win.set_panel('header',True); app.processEvents()
        width=win.viewer.width(); height=win.viewer.height()
        win.panel_actions['header'].trigger(); win.timeline_action.trigger(); app.processEvents()
        assert win.viewer.width()>=width and win.viewer.height()>height
        win.timeline.set_units('frames'); assert win.timeline.tick_label(24)=='24'
        win.timeline.set_units('time'); assert win.timeline.tick_label(24)=='00:01.000'
        win.apply_preferences(dict(win.preferences,scrub_pixels=10)); assert win.viewer.scrub_pixels==10
        win.viewer.position=10; moves=[]; win.viewer.scrub.connect(moves.append)
        QTest.mousePress(win.viewer,Qt.MouseButton.LeftButton,pos=QPoint(100,100))
        QTest.mouseMove(win.viewer,QPoint(160,100)); QTest.mouseRelease(win.viewer,Qt.MouseButton.LeftButton,pos=QPoint(160,100))
        assert moves[-1]==16
        win.toggle_flip('flip_h'); assert doc.state.flip_h
        assert win.viewer.image.pixelColor(0,0).red()==int(win.viewer.rgb[0,-1,0])
        win.undo(); assert not doc.state.flip_h
        win.toggle_fullscreen(); app.processEvents(); assert win.isFullScreen() and win.transport_widget.isHidden()
        # Shortcuts must stay active even with menus hidden.
        QTest.keyClick(win,Qt.Key.Key_Escape); app.processEvents()
        assert not win.video_fullscreen and win.header.isHidden() and win.timeline_panel.isHidden()
        win.panel_actions['header'].trigger(); win.timeline_action.trigger(); app.processEvents()
        win.grab().save(str(Path(__file__).parent/'ui-preview.png'))
    finally:
        win.viewer.scrub_pixels=original_scrub; win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()


def test_append_through_async_ui(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); errors=[]; win.error=errors.append
    m,_=prepared
    try:
        win.append_paths([m['path'],m['path']])
        deadline=time.time()+15
        while win.job and time.time()<deadline: app.processEvents(); QTest.qWait(20)
        assert win.job is None and not errors,errors
        assert win.doc.state.length==384
        win.undo(); assert win.doc.state.length==0
        win.redo(); assert win.doc.state.length==384
    finally:
        if win.job: win.job.cancel.set(); win.job.wait(); app.processEvents()
        win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()


def test_reorder_independent_tracks_and_history(prepared,tmp_path):
    m,_=prepared; key=m['id']; d=Document(); d.media={key:m}
    d.state=State((Segment(key,0,12),Segment(key,24,36),Segment(key,48,60)))
    before=d.state
    assert d.move_range(0,12,36,'audio')
    assert expanded(d.state.segments)==expanded(before.segments)
    assert expanded(d.state.audio)==list(range(24,36))+list(range(48,60))+list(range(12))
    moved=d.state; d.undo(); assert d.state==before; d.redo(); assert d.state==moved
    d.select(0,6); d.copy(); copied_audio=d.audio_clipboard; d.delete(); assert d.state.length==30 and sum(s.length for s in d.state.audio)==30
    d.state=replace(d.state,position=30); d.paste()
    assert expanded(d.state.audio)[-6:]==expanded(copied_audio)
    d.move_range(0,6,36,'video'); assert sum(s.length for s in d.state.audio)==36
    p=tmp_path/'independent.cadence'; d.save(p); assert Document.load(p).state==d.state
    d=Document(); d.state=before; d.move_range(0,12,36,'linked')
    assert expanded(d.state.segments)==expanded(d.state.audio)
    assert not d.move_range(0,12,5)


def test_independent_audio_export(prepared,tmp_path):
    import av
    m,_=prepared; k=m['id']; state=State((Segment(k,0,24),),audio_segments=(Segment(k,24,48),))
    target=tmp_path/'separate.mp4'; export_video(state,{k:m},Fraction(24),target,False)
    pcm=TimelinePCM(state.audio,{k:m},Fraction(24)); expected=np.frombuffer(pcm.read(0,48000),dtype='<i2').reshape(-1,2)[:,0]/32768.; pcm.close()
    with av.open(str(target)) as c: actual=np.concatenate([f.to_ndarray() for f in c.decode(audio=0)],axis=1)[0,:48000]
    assert np.corrcoef(expected,actual)[0,1]>.95
    with av.open(str(target)) as c: assert sum(1 for _ in c.decode(video=0))==24


def test_timeline_gestures_and_numeric_scrub(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QPoint
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show()
    m,_=prepared; d=Document(); d.media={m['id']:m}; d.state=State((Segment(m['id'],0,24),Segment(m['id'],48,72)))
    win.install_doc(d)
    try:
        app.processEvents(); t=win.timeline
        def drag(a,b,y,modifier=Qt.KeyboardModifier.NoModifier):
            QTest.mousePress(t,Qt.MouseButton.LeftButton,modifier,QPoint(round(t.x_for(a)),y))
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QEvent,QPointF
            point=QPointF(round(t.x_for(b)),y)
            QApplication.sendEvent(t,QMouseEvent(QEvent.Type.MouseMove,point,QPointF(t.mapToGlobal(point.toPoint())),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,modifier))
            QTest.mouseRelease(t,Qt.MouseButton.LeftButton,modifier,QPoint(round(t.x_for(b)),y))
            app.processEvents()
        drag(2,20,60); assert abs(d.state.position-20)<=1 and d.state.selection is None
        drag(3,15,60,Qt.KeyboardModifier.ShiftModifier); assert d.state.selection and d.state.selection[1]-d.state.selection[0]>=12
        win.clear_selection(); win.link_tracks.setChecked(False)
        audio_before=d.state.audio
        drag(5,48,60,Qt.KeyboardModifier.AltModifier)
        assert expanded(d.state.segments)==list(range(48,72))+list(range(24))
        assert d.state.audio==audio_before
        win.undo(); win.clear_selection()
        drag(5,48,106,Qt.KeyboardModifier.AltModifier)
        assert expanded(d.state.audio)==list(range(48,72))+list(range(24))
        for name in ('header','transport'):
            if win.panel_actions[name].isChecked(): win.panel_actions[name].trigger()
            assert win.panel_widgets()[name].isHidden()
        win.toggle_fullscreen(); win.escape()
        assert win.header.isHidden() and win.transport_widget.isHidden()
        edit=win.exp_spin.lineEdit(); before=len(d.undo_stack)
        QTest.mousePress(edit,Qt.MouseButton.LeftButton,pos=QPoint(10,10))
        QTest.mouseMove(edit,QPoint(50,10)); QTest.mouseRelease(edit,Qt.MouseButton.LeftButton,pos=QPoint(50,10))
        assert d.state.exposure==1 and len(d.undo_stack)==before+1
    finally:
        d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_association_command_quotes():
    from association import registration_values
    values=registration_values('C:/Program Files/Cadence Studio/CadenceStudio.exe')
    command=values[r'Software\Classes\CadenceStudio.Project\shell\open\command'][0]
    assert command.startswith('"') and command.endswith('" "%1"')


def test_gaps_move_snap_and_project(prepared,tmp_path):
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}
    d.state=State((Segment(k,0,12),Segment(k,24,36),Segment(k,48,60)))
    assert d.snap_destination(15)==12 and d.snap_destination(22)==24
    assert d.move_range(0,12,35,leave_gap=True)
    assert d.state.length==48 and d.state.segments[0].media is None
    assert d.state.segments[-1]==Segment(k,0,12)
    assert d.state.audio==d.state.segments
    moved=d.state; d.undo(); assert d.state.length==36; d.redo(); assert d.state==moved
    d.state=replace(d.state,position=6); d.insert_gap(5); assert d.state.length==53
    assert d.state.segments[0].media is None and d.state.segments[0].length==17
    path=tmp_path/'gaps.cadence'; d.save(path); assert Document.load(path).state==d.state
    d.move_range(17,29,53,'video',True)
    assert sum(s.length for s in d.state.audio)==d.state.length


def test_black_silence_export(prepared,tmp_path):
    import av
    m,_=prepared; k=m['id']; state=State((Segment(k,0,6),Segment(None,0,12),Segment(k,12,18)))
    target=tmp_path/'black.mp4'; export_video(state,{k:m},Fraction(24),target)
    with av.open(str(target)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(frames)==24
    for frame in frames[6:18]: assert frame.max()<=2
    assert frames[5].max()>100 and frames[18].max()>100
    pcm=TimelinePCM(state.audio,{k:m},Fraction(24)); assert pcm.read(12000,24000)==bytes(24000*4); pcm.close()
    with av.open(str(target)) as c: audio=np.concatenate([f.to_ndarray() for f in c.decode(audio=0)],axis=1)
    assert np.max(np.abs(audio[:,14000:34000]))<.002
    # A project containing only a gap still produces a finite, black video.
    blank=tmp_path/'only-black.mp4'; export_video(State((Segment(None,0,7),)),{k:m},Fraction(24),blank)
    with av.open(str(blank)) as c:
        frames=list(c.decode(video=0)); assert len(frames)==7 and frames[0].to_ndarray(format='rgb24').max()<=2


def test_drag_visual_and_gap_preview(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); win=MainWindow(); win.show()
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}; d.state=State((Segment(k,0,24),Segment(k,48,72),Segment(k,96,120)))
    win.install_doc(d)
    try:
        app.processEvents(); t=win.timeline
        assert t.boundary_for(t.x_for(30))==24
        assert t.boundary_for(t.x_for(43))==48
        QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,QPoint(round(t.x_for(5)),60))
        QTest.mouseMove(t,QPoint(round(t.x_for(65)),60)); QTest.qWait(150)
        assert t.drop_frame==72 and t.ghost_x is not None
        deadline=time.monotonic()+2
        while abs(t.animated_x-t.x_for(72))>=1 and time.monotonic()<deadline: QTest.qWait(20)
        assert abs(t.animated_x-t.x_for(72))<1
        win.grab().save(str(Path(__file__).parent/'drag-preview.png'))
        QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,QPoint(round(t.x_for(65)),60))
        assert d.state.segments[-1]==Segment(k,0,24)
        win.leave_gap.setChecked(True); win.move_section(0,24,72,'video')
        win.seek(1); assert win.viewer.image.pixelColor(0,0).red()==0
        assert win.rendered_token==win.token
    finally:
        d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_track_delete_selection_and_history(prepared,tmp_path):
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}; d.state=State((Segment(k,0,24),Segment(k,48,72)))
    original=d.state
    assert d.delete_track_range(6,30,'video')
    assert d.state.length==48 and d.state.audio==original.audio
    assert slice_segments(d.state.segments,6,30)==(Segment(None,0,24),)
    d.undo(); assert d.state==original; d.redo()
    assert d.delete_track_range(3,40,'audio')
    assert d.state.length==48 and sum(s.length for s in d.state.audio)==48
    pcm=TimelinePCM(d.state.audio,d.media,d.fps); assert pcm.read(6000,74000)==bytes(74000*4); pcm.close()
    path=tmp_path/'deleted.cadence'; d.save(path); assert Document.load(path).state==d.state


def test_timeline_context_menu_track(prepared):
    from PySide6.QtWidgets import QApplication,QMenu
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtCore import QTimer,QPoint
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.workspaces.switch('edit'); win.show()
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}; d.state=State((Segment(k,0,24),Segment(k,48,72)),selection=(4,10)); win.install_doc(d)
    try:
        t=win.timeline; app.processEvents()
        assert t.context_target(t.x_for(6),60)==(4,10,'video')
        assert t.context_target(t.x_for(30),t.track_y('audio')+9)==(24,48,'audio')
        assert t.context_target(t.x_for(6),20) is None
        def choose():
            menu=app.activePopupWidget(); assert isinstance(menu,QMenu)
            try:
                action=next(a for a in menu.actions() if a.text()=='Supprimer l’audio'); action.trigger()
            finally: menu.close()
        QTimer.singleShot(50,choose)
        point=QPoint(round(t.x_for(6)),t.track_y('audio')+9)
        t.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,t.mapToGlobal(point)))
        assert d.state.segments==(Segment(k,0,24),Segment(k,48,72))
        assert any(s.media is None and s.length==6 for s in d.state.audio)
        win.undo(); assert d.state.audio==d.state.segments
    finally:
        d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_video_only_clipboard_and_opt_in(prepared):
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}; d.state=State((Segment(k,0,24),),position=12,selection=(3,6))
    d.copy(False); before=d.state; d.paste(False)
    assert d.state.length==27
    assert slice_segments(d.state.audio,12,15)==(Segment(None,0,3),)
    assert slice_segments(d.state.segments,12,15)==(Segment(k,3,6),)
    d.undo(); assert d.state==before; d.redo(); assert d.state.length==27
    d.undo(); d.copy(True); d.paste(True)
    assert slice_segments(d.state.audio,12,15)==(Segment(k,3,6),)


def test_ui_clipboard_default_silent(prepared):
    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); m,_=prepared
    d=Document(); d.media={m['id']:m}; d.state=State((Segment(m['id'],0,24),)); win.install_doc(d)
    try:
        assert not win.copy_audio.isChecked()
        win.select(2,3); win.copy_selection(); win.seek(24); win.paste_selection()
        assert d.state.segments[-1]==Segment(m['id'],2,3)
        assert d.state.audio[-1]==Segment(None,0,1)
        win.undo(); win.copy_audio.setChecked(True); win.select(4,5); win.copy_selection(); win.seek(24); win.paste_selection()
        assert d.state.audio[-1]==Segment(m['id'],4,5)
    finally:
        d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_split_mute_delete_and_save(prepared,tmp_path):
    m,_=prepared; k=m['id']; d=Document(); d.media={k:m}; d.state=State((Segment(k,0,48),))
    assert d.split_at(24); assert len(d.state.segments)==2 and len(d.state.audio)==2
    d.select(2,3); d.copy(); d.state=replace(d.state,position=48); d.paste()
    assert any(s.cut_before for s in d.state.segments)
    d.undo(); assert d.mute_range(0,24,'video'); assert d.state.segments[0].muted and not d.state.audio[0].muted
    assert d.mute_range(0,24,'video'); assert not d.state.segments[0].muted
    d.mute_range(24,48,'audio'); pcm=TimelinePCM(d.state.audio,d.media,d.fps); assert pcm.read(48000,48000)==bytes(48000*4); pcm.close()
    path=tmp_path/'mute.cadence'; d.save(path); assert Document.load(path).state==d.state
    d.delete_track_range(0,24,'video'); assert d.state.segments[0].media is None and d.state.segments[1].start==24
    d.undo(); assert len(d.state.segments)==2


def test_muted_export(prepared,tmp_path):
    import av
    m,_=prepared; k=m['id']; state=State((Segment(k,0,6,True),Segment(k,6,12)),audio_segments=(Segment(k,0,12,True),))
    target=tmp_path/'muted.mp4'; export_video(state,{k:m},Fraction(24),target)
    with av.open(str(target)) as c: frames=list(c.decode(video=0)); assert len(frames)==12
    assert frames[0].to_ndarray(format='rgb24').max()<=2 and frames[-1].to_ndarray(format='rgb24').max()>100
    with av.open(str(target)) as c: audio=np.concatenate([f.to_ndarray() for f in c.decode(audio=0)],axis=1)
    assert np.max(np.abs(audio))<.001


def test_selection_playback_auto(prepared):
    from PySide6.QtWidgets import QApplication
    from engine import Transport
    app=QApplication.instance() or QApplication([]); m,_=prepared
    state=State((Segment(m['id'],0,192),),position=0,selection=(24,30))
    t=Transport()
    try:
        t.start(state,{m['id']:m},Fraction(24),'once',1)
        assert (t.a,t.b,t.start_frame)==(24,30,24)
    finally: t.stop()


def test_navigation_library_and_volume(prepared,tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint,QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); m,_=prepared
    d=Document(); d.append_media([m]); win.install_doc(d)
    def wheel(widget,x):
        pos=QPointF(x,60); event=QWheelEvent(pos,pos,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False); widget.wheelEvent(event)
    try:
        deadline=time.time()+5
        while win.rendered_token!=win.token and time.time()<deadline: app.processEvents(); QTest.qWait(10)
        wheel(win.viewer,150); assert win.viewer.zoom>1
        QTest.mousePress(win.viewer,Qt.MouseButton.MiddleButton,pos=QPoint(100,100)); QTest.mouseMove(win.viewer,QPoint(150,120)); QTest.mouseRelease(win.viewer,Qt.MouseButton.MiddleButton,pos=QPoint(150,120)); assert win.viewer.pan.x()==50
        QTest.mousePress(win.viewer,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.ShiftModifier,QPoint(100,100)); QTest.mouseMove(win.viewer,QPoint(100,150)); QTest.mouseRelease(win.viewer,Qt.MouseButton.MiddleButton,pos=QPoint(100,150)); assert win.viewer.angle==25
        win.viewer.reset_view(); assert win.viewer.zoom==1 and win.viewer.angle==0 and win.viewer.pan.x()==0
        t=win.timeline; wheel(t,400); assert t.zoom>1
        start=t.view_start
        QTest.mousePress(t,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.ControlModifier,QPoint(400,60)); QTest.mouseMove(t,QPoint(350,60)); QTest.mouseRelease(t,Qt.MouseButton.MiddleButton,pos=QPoint(350,60)); assert t.view_start>start
        assert abs(t.raw_frame(t.x_for(100))-100)<.001
        assert win.media_list.count()==1 and win.playlist.count()==1
        win.volume.setValue(25); assert win.transport.volume==.25
        win.volume.setMuted(True); assert win.transport.volume==0
        win.volume.setMuted(False); assert win.transport.volume==.25
        win.library_tabs.setCurrentIndex(1); win.media_list.setCurrentRow(0); win.remove_library_media(); assert win.doc.state.length==0 and win.media_list.count()==0
        win.undo(); assert win.doc.state.length==192 and win.media_list.count()==1
        win.library.show();
        deadline=time.time()+5
        while win.rendered_token!=win.token and time.time()<deadline: app.processEvents(); QTest.qWait(10)
        win.grab().save(str(Path(__file__).parent/'ui-preview.png'))
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_parallel_import_order_cache_and_cancel(prepared):
    from media import prepare_batch,Cancelled
    import threading
    m,_=prepared; updates=[]
    result=prepare_batch([m['path'],m['path']],Fraction(24),lambda v,msg:updates.append(v))
    assert len(result)==2 and result[0]['id']==result[1]['id'] and updates==sorted(updates)
    cancel=threading.Event(); cancel.set()
    with pytest.raises(Cancelled): prepare_batch([m['path']],Fraction(24),cancel=cancel)


def test_batch_concurrency_and_order(monkeypatch,tmp_path):
    import media,threading,time
    barrier=threading.Barrier(2); active=[0,0]; lock=threading.Lock()
    def fake(path,fps,progress,cancel,quality='native',defer_audio=False):
        with lock: active[0]+=1; active[1]=max(active[0],active[1])
        barrier.wait(timeout=3)
        time.sleep(.04 if path.endswith('first.mp4') else .01)
        progress(1,'ok')
        with lock: active[0]-=1
        return {'path':path}
    monkeypatch.setattr(media,'prepare_media',fake)
    paths=[str(tmp_path/'first.mp4'),str(tmp_path/'second.mp4')]
    result=media.prepare_batch(paths,Fraction(24))
    assert [m['path'] for m in result]==paths and active[1]==2


def test_canvas_ctrl_zoom_shift_vertical_and_scroll(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); m,_=prepared
    d=Document(); d.append_media([m]); win.install_doc(d)
    try:
        viewer=win.viewer
        def drag(mod,a,b):
            QTest.mousePress(viewer,Qt.MouseButton.MiddleButton,mod,a); QTest.mouseMove(viewer,b); QTest.mouseRelease(viewer,Qt.MouseButton.MiddleButton,mod,b)
        drag(Qt.KeyboardModifier.ControlModifier,QPoint(100,100),QPoint(160,100)); assert viewer.zoom>1 and viewer.pan.x()==0
        drag(Qt.KeyboardModifier.ShiftModifier,QPoint(100,100),QPoint(150,100)); assert viewer.angle==0
        drag(Qt.KeyboardModifier.ShiftModifier,QPoint(100,100),QPoint(100,150)); assert viewer.angle==25
        t=win.timeline; t.zoom=4; t.clamp_view(); app.processEvents()
        assert not win.timeline_scroll.isHidden() and win.timeline_scroll.maximum()==144
        win.timeline_scroll.setValue(50); assert t.view_start==50
        t.reset_view(); assert win.timeline_scroll.isHidden()
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_movable_panels_and_unified_open(monkeypatch):
    from PySide6.QtWidgets import QApplication,QDockWidget,QFileDialog,QPushButton
    from PySide6.QtCore import Qt
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show()
    try:
        win.layout_action.trigger()
        for key in ('header','transport','timeline'):
            dock=win.panel_widgets()[key]; assert isinstance(dock,QDockWidget)
            assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable
            dock.setFloating(True); app.processEvents(); assert dock.isFloating()
            dock.setFloating(False)
        calls=[]; monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *a,**k:(['a.mp4','b.mov'],'')); win.append_paths=lambda paths:calls.append(paths)
        win.open_video(); assert calls==[['a.mp4','b.mov']]
        assert not any('Retirer la sélection' in b.text() for b in win.findChildren(QPushButton))
    finally: win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()


def test_library_right_click_and_delete_both(prepared):
    from PySide6.QtWidgets import QApplication,QMenu
    from PySide6.QtCore import QTimer,Qt
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); win.library.show(); m,_=prepared
    d=Document(); d.append_media([m,m]); win.install_doc(d)
    try:
        for index in (0,1):
            win.library_tabs.setCurrentIndex(index); app.processEvents(); listing=win.playlist if index==0 else win.media_list
            def choose():
                menu=app.activePopupWidget()
                try:
                    assert isinstance(menu,QMenu); assert menu.actions()[0].text()=='Supprimer'; menu.actions()[0].trigger()
                finally:
                    if menu: menu.close()
            QTimer.singleShot(50,choose)
            win.library_context(listing,listing.visualItemRect(listing.item(0)).center())
            assert d.state.length==(192 if index==0 else 0)
        win.undo(); assert d.state.length==192
        win.delete_media_range(10,20); assert d.state.length==182 and sum(s.length for s in d.state.audio)==182
        assert all(s.media is not None for s in d.state.segments)
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_volume_bars_context_and_drag(tmp_path):
    from PySide6.QtWidgets import QApplication,QPushButton
    from PySide6.QtCore import Qt,QPoint,QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); win=MainWindow(); win.show()
    try:
        v=win.volume; app.processEvents()
        QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=QPoint(7,20)); QTest.mouseMove(v,QPoint(52,20)); QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=QPoint(52,20))
        assert v.value()==50 and win.transport.volume==.5
        for expected in ('Couper le son','Réactiver le son'):
            def choose(label=expected):
                menu=app.activePopupWidget()
                try: assert menu.actions()[0].text()==label; menu.actions()[0].trigger()
                finally: menu.close()
            QTimer.singleShot(30,choose); point=QPoint(50,20); v.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,v.mapToGlobal(point)))
            if expected=='Couper le son':
                assert v.muted and win.transport.volume==0
                v.grab().save(str(tmp_path/'muted.png'))
            else: assert not v.muted and v.value()==50 and win.transport.volume==.5
        assert not any(b.text() in ('Son','Muet') for b in win.findChildren(QPushButton))
        v.grab().save(str(tmp_path/'active.png'))
    finally: win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()

def test_preferences_persistence_and_conflicts(tmp_path,monkeypatch):
    import copy,json
    from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog
    from PySide6.QtGui import QKeySequence
    from app import MainWindow
    from preferences import defaults,validate,load_preferences,ShortcutDialog
    app=QApplication.instance() or QApplication([]); win=MainWindow()
    try:
        base=validate(defaults(win.action_registry),win.action_registry)
        key='Lecture/Lecture / pause'; other='Lecture/Image suivante'
        changed=copy.deepcopy(base); changed['shortcuts'][key]='Ctrl+K'; changed['scrub_pixels']=9.5; changed['canvas']['zoom']['invert_x']=True
        dialog=ShortcutDialog(win.action_registry,changed,win)
        dialog.accept(); assert dialog.result_data==load_preferences(win.action_registry)
        win.apply_preferences(dialog.result_data); assert win.action_registry[key][0].shortcut()==QKeySequence('Ctrl+K'); assert win.viewer.scrub_pixels==9.5
        second=MainWindow()
        try: assert second.preferences==dialog.result_data and second.viewer.controls['zoom']['invert_x']
        finally: second.close()
        duplicate=copy.deepcopy(changed); duplicate['shortcuts'][other]='Ctrl+K'
        with pytest.raises(ValueError,match='Conflit'): validate(duplicate,win.action_registry)
        prefix=copy.deepcopy(changed); prefix['shortcuts'][other]='Ctrl+K, A'
        with pytest.raises(ValueError,match='Conflit'): validate(prefix,win.action_registry)
        duplicate=copy.deepcopy(changed); duplicate['canvas']['rotate']['modifiers']='Ctrl'
        with pytest.raises(ValueError,match='différente'): validate(duplicate,win.action_registry)
        path=tmp_path/'export.json'; monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(path),'')); dialog.export_file()
        exported=json.loads(path.read_text(encoding='utf-8'))
        assert not {'language','clear_cache_on_exit'} & exported.keys()
        assert validate(exported,win.action_registry)==dialog.collect()
        monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:QMessageBox.StandardButton.No); dialog.reset_all(); assert dialog.collect()['scrub_pixels']==9.5
        monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:QMessageBox.StandardButton.Yes); dialog.reset_key(key); assert dialog.collect()['shortcuts'][key]=='Space'
        dialog.reset_all(); assert dialog.collect()==base
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(path),'')); dialog.import_file(); assert dialog.collect()==changed
        path.write_text('{"format":"wrong"}',encoding='utf-8'); dialog.import_file(); assert dialog.collect()==changed
    finally: win.close(); app.processEvents()


def test_canvas_custom_axes_and_inversion():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from widgets import Viewer
    app=QApplication.instance() or QApplication([]); v=Viewer(); v.show()
    def drag(mod,end):
        QTest.mousePress(v,Qt.MouseButton.MiddleButton,mod,QPoint(100,100)); QTest.mouseMove(v,end); QTest.mouseRelease(v,Qt.MouseButton.MiddleButton,mod,end)
    try:
        drag(Qt.KeyboardModifier.ControlModifier,QPoint(100,150)); assert v.zoom==1
        drag(Qt.KeyboardModifier.ControlModifier,QPoint(150,100)); assert v.zoom>1
        v.reset_view(); v.controls['zoom']['invert_x']=True
        drag(Qt.KeyboardModifier.ControlModifier,QPoint(150,100)); assert v.zoom<1
        v.controls['rotate']['invert_y']=True; drag(Qt.KeyboardModifier.ShiftModifier,QPoint(100,150)); assert v.angle==-25
        v.controls['pan']['modifiers']='Alt'; v.controls['pan']['invert_x']=True; v.controls['pan']['invert_y']=True
        drag(Qt.KeyboardModifier.AltModifier,QPoint(150,130)); assert v.pan.x()==-50 and v.pan.y()==-30
        v.controls['zoom']['axis']='y'; v.reset_view(); drag(Qt.KeyboardModifier.ControlModifier,QPoint(100,150)); assert v.zoom>1
    finally: v.close()


def test_multi_delete_single_undo():
    d=Document(); d.state=State((Segment('a',0,10),Segment('b',0,20),Segment('c',0,30)),audio_segments=(Segment('c',0,30),Segment('b',0,20),Segment('a',0,10)))
    before=d.state; d.remove_media_keys(['a','c']); assert d.state.length==20 and d.state.audio==(Segment('b',0,20),)
    assert len(d.undo_stack)==1; d.undo(); assert d.state==before
    d.delete_ranges([(0,10),(30,60)]); assert d.state.segments==(Segment('b',0,20),) and sum(s.length for s in d.state.audio)==20
    d.undo(); assert d.state==before


def test_library_multiple_selection_and_locked_clean_layout(prepared,monkeypatch):
    from PySide6.QtWidgets import QApplication,QDockWidget,QLabel,QMenu,QAbstractItemView
    from PySide6.QtCore import Qt,QTimer
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); win=MainWindow(); win.show(); m,_=prepared
    d=Document(); d.append_media([m,m,m]); win.install_doc(d); win.library.show(); app.processEvents()
    try:
        assert 'hint' not in win.panel_widgets() and 'status' not in win.panel_widgets()
        assert not any('LECTURE PRÉCISE' in label.text() or 'I / O : bornes' in label.text() for label in win.findChildren(QLabel))
        for panel in win.panel_widgets().values():
            if isinstance(panel,QDockWidget): assert panel.features()==QDockWidget.DockWidgetFeature.NoDockWidgetFeatures and panel.titleBarWidget().height()==0
        assert win.timecode_overlay.parent() is win.viewer
        win.layout_action.trigger(); assert win.timeline_panel.features()&QDockWidget.DockWidgetFeature.DockWidgetMovable
        win.timeline_panel.setFloating(True); win.layout_action.trigger(); app.processEvents(); assert not win.timeline_panel.isFloating()
        for listing in (win.playlist,win.media_list): assert listing.selectionMode()==QAbstractItemView.SelectionMode.ExtendedSelection
        win.playlist.item(0).setSelected(True); win.playlist.item(2).setSelected(True); before=d.state; count=len(d.undo_stack)
        def choose():
            menu=app.activePopupWidget()
            try:
                assert len(win.playlist.selectedItems())==2
                menu.actions()[0].trigger()
            finally: menu.close()
        QTimer.singleShot(30,choose); win.library_context(win.playlist,win.playlist.visualItemRect(win.playlist.item(2)).center())
        assert d.state.length==192 and len(d.undo_stack)==count+1
        win.undo(); assert d.state==before
        # Follow external scrub, keep manual scroll until the playhead actually moves.
        t=win.timeline; t.zoom=4; t.clamp_view(); win.seek(350)
        assert t.view_start<=350<t.view_start+t.span() and win.timeline_scroll.value()==round(t.view_start)
        win.timeline_scroll.setValue(0); assert t.view_start==0
        win.seek(351); assert t.view_start>0
        win.seek(10); assert t.view_start<=10<t.view_start+t.span()
        win.library.hide(); win.grab().save(str(Path(__file__).parent/'ui-preview.png'))
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()


def test_volume_no_outline_no_cross():
    from PySide6.QtWidgets import QApplication
    from widgets import VolumeBars
    from app import STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); v=VolumeBars(); v.show(); v.setValue(100)
    try:
        v.clearFocus(); app.processEvents(); unfocused=v.grab().toImage()
        v.setFocus(); app.processEvents(); focused=v.grab().toImage()
        assert focused==unfocused
        v.setMuted(True); app.processEvents(); muted=v.grab().toImage()
        # No pale cross: all painted pixels remain within the dark grey palette.
        assert max(muted.pixelColor(x,y).red() for x in range(v.width()) for y in range(v.height()))<150
        assert muted!=focused
    finally: v.close()

def test_timeline_ruler_context_units():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtCore import QPoint,QTimer
    from widgets import Timeline
    app=QApplication.instance() or QApplication([]); timeline=Timeline(); timeline.show()
    try:
        for label in ('Images','Code temporel'):
            def choose(expected=label):
                menu=app.activePopupWidget()
                try:
                    assert [a.text() for a in menu.actions()][:2]==['Code temporel','Images']
                    assert any(a.data()=='timeline_simple' for a in menu.actions())
                    next(a for a in menu.actions() if a.text()==expected).trigger()
                finally: menu.close()
            QTimer.singleShot(30,choose); point=QPoint(150,20); timeline.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,timeline.mapToGlobal(point)))
            assert timeline.units==('frames' if label=='Images' else 'time')
    finally: timeline.close()

def test_compact_timeline_when_panels_hidden(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from app import MainWindow,STYLE
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); win=MainWindow(); win.workspaces.switch('edit'); win.show(); m,_=prepared
    doc=Document(); doc.append_media([m]); win.install_doc(doc)
    try:
        app.processEvents(); before=win.viewer.height(); timeline_height=win.timeline_panel.height()
        for key in ('header','transport'): win.set_panel(key,False)
        win.resize(1600,1000); app.processEvents()
        assert win.viewer.height()>before
        assert win.timeline.height()==100 and win.timeline_panel.height()==timeline_height
        assert 99<=win.timeline_panel.height()<=102
        for control in (win.copy_audio,win.leave_gap,win.link_tracks):
            assert win.header.isAncestorOf(control) and not win.timeline_panel.isAncestorOf(control)
        win.timeline.zoom=4; win.timeline.clamp_view(); app.processEvents()
        assert win.timeline_scroll.isVisible() and win.timeline_scroll.geometry().bottom()<win.timeline_panel.widget().height()
        assert win.timeline_panel.height()>timeline_height
        win.timeline.reset_view(); app.processEvents(); assert win.timeline_panel.height()==timeline_height
        win.layout_action.trigger(); app.processEvents(); assert win.timeline_panel.height()<=timeline_height+26
    finally: doc.saved_signature=doc.signature(); win.close(); app.processEvents()


def test_locked_library_compact_timecode_and_fullscreen(prepared):
    from PySide6.QtWidgets import QApplication,QMainWindow
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); app.processEvents()
    try:
        assert not win.layout_editable and win.library_action.isEnabled()
        win.library_action.trigger(); app.processEvents(); assert win.library.isVisible()
        win.library_action.trigger(); app.processEvents(); assert win.library.isHidden()
        assert not win.timecode_overlay.isHidden() and win.timecode_overlay.rect().isEmpty()
        assert not (win.dockOptions()&QMainWindow.DockOption.AnimatedDocks)
        size=win.size(); margins=win.centralWidget().layout().contentsMargins(); heights={k:w.height() for k,w in win.panel_widgets().items() if k!='timecode'}
        win.toggle_fullscreen(); app.processEvents(); win.toggle_fullscreen(); app.processEvents()
        assert win.size()==size and win.centralWidget().layout().contentsMargins()==margins
        assert abs(win.transport_widget.height()-heights['transport'])<=1
        assert win.library_action.isEnabled()
        playback=next(a.menu() for a in win.menuBar().actions() if a.text()=='Lecture')
        assert not any(a.text() in ('Marquer entrée','Marquer sortie') for a in playback.actions())
    finally: win.close(); app.processEvents()


def test_decoder_warms_next_media_without_extra_display(monkeypatch):
    import threading
    import engine
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    calls=[]; warmed=threading.Event()
    class Reader:
        def __init__(self,retain_decoded=False): assert retain_decoded
        def read(self,media,index,cancel=None):
            calls.append((media['id'],index))
            if media['id']=='next': warmed.set()
            return np.zeros((2,2,3),dtype=np.uint8)
        def close(self): pass
    monkeypatch.setattr(engine,'PreviewReader',Reader)
    app=QApplication.instance() or QApplication([]); worker=engine.Decoder(); displayed=[]; worker.ready.connect(lambda token,arr:displayed.append(token)); worker.start()
    try:
        worker.request(7,{'id':'current'},10,[({'id':'next'},0)])
        assert warmed.wait(2)
        QTest.qWait(30); app.processEvents()
        assert calls==[('current',10),('next',0)] and displayed==[7]
    finally: worker.stop()

def test_comparison_pixel_math_and_aspect_fit():
    from PySide6.QtWidgets import QApplication
    from comparison import compose,fit_reference
    app=QApplication.instance() or QApplication([])
    a=np.full((4,6,3),40,np.uint8); b=np.full((4,6,3),140,np.uint8)
    assert np.all(compose(a,a,'difference')==0)
    assert np.all(compose(a,b,'difference')==100)
    assert np.all(compose(a,b,'difference',gain=3)==255)
    assert np.all(compose(a,b,'overlay',.25)==65)
    assert np.array_equal(compose(a,b,'overlay',0),a) and np.array_equal(compose(a,b,'overlay',1),b)
    assert compose(a,b,'horizontal').shape==(4,12,3)
    assert compose(a,b,'vertical').shape==(8,6,3)
    assert np.array_equal(compose(a,b,'front',swapped=True),b)
    assert np.all(compose(a,b,'horizontal',swapped=True)[:,:6]==140)
    fitted=fit_reference(np.full((6,2,3),255,np.uint8),6,4)
    assert fitted.shape==a.shape and fitted[:,0].max()==0 and fitted.max()==255


def test_comparison_playback_modes_sync_and_save(prepared,tmp_path,monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QFileDialog
    from PySide6.QtTest import QTest
    from app import MainWindow,STYLE
    from comparison import MODES
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE); win=MainWindow(); win.show(); m,_=prepared
    d=Document(); d.append_media([m]); win.install_doc(d); errors=[]; win.error=errors.append
    def rendered():
        end=time.time()+5
        while win.rendered_token!=win.token and time.time()<end: app.processEvents(); QTest.qWait(10)
        assert win.rendered_token==win.token and not errors,errors
    try:
        win.compare_cycle_btn.click(); assert win.comparison_panel.isVisible() and not win.compare_swap_btn.isEnabled()
        win.seek(24); win.use_reference(m); rendered(); assert win.viewer.comparing; assert win.reference_combo.currentData()==m['id']
        assert win.windowTitle().startswith('● Cadence -')
        win.workspaces.switch('read'); app.processEvents(); assert win.compare_cycle_btn.isVisible()
        win.compare_enabled.setChecked(False); win.comparison_panel.hide()
        for index,(_,mode) in enumerate(MODES):
            QTest.mouseClick(win.compare_cycle_btn,Qt.MouseButton.LeftButton); rendered()
            assert win.compare_mode.currentData()==mode and win.viewer.comparing and win.comparison_panel.isHidden()
            image=win.viewer.cpu_preview(); h,w=win.viewer.rgb.shape[:2]
            assert (image.width(),image.height())==((w*2,h) if mode=='horizontal' else (w,h*2) if mode=='vertical' else (w,h))
            if mode=='difference': assert image.pixelColor(w//2,h//2).red()==0
        win.compare_swap_btn.click(); assert win.viewer.compare_swapped and win.compare_cycle_btn.symbol=='front_b'
        win.compare_swap_btn.click(); assert not win.viewer.compare_swapped and win.compare_swap_btn.symbol=='ab'
        win.compare_cycle_btn.click(); rendered(); assert not win.viewer.comparing and win.compare_cycle_btn.symbol=='off'
        assert not win.compare_swap_btn.isEnabled() and win.viewer.image.width()==w
        win.compare_cycle_btn.click(); rendered(); assert win.viewer.compare_mode=='horizontal' and win.viewer.comparing
        win.workspaces.switch('edit'); win.comparison_panel.show()
        win.compare_offset.setValue(5); rendered()
        assert not np.array_equal(win.viewer.rgb,win.viewer.reference_rgb)
        win.swap_comparison(); assert win.viewer.compare_swapped
        win.compare_mode.setCurrentIndex(2); win.compare_opacity.setValue(35); win.compare_gain.setValue(2)
        win.toggle_fullscreen(); app.processEvents(); assert win.comparison_panel.isHidden() and win.viewer.comparing
        win.swap_comparison(); win.toggle_fullscreen(); app.processEvents(); assert win.comparison_panel.isVisible()
        path=tmp_path/'review.cadence'; monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(path),'')); assert win.save_project()
        saved=Document.load(path); assert saved.review['reference']==m['path'] and saved.review['offset']==5 and saved.review['opacity']==35
        # Reload through the actual async project preparation, retaining reference metadata.
        win.open_project(str(path)); end=time.time()+10
        while win.job and time.time()<end: app.processEvents(); QTest.qWait(15)
        assert not win.job and win.compare_media is not None and win.compare_offset.value()==5
        assert win.compare_cycle_btn.symbol=='overlay' and win.compare_swap_btn.symbol=='ab'
        rendered()
        # A negative offset produces a deliberate black B, never the previous reference frame.
        win.compare_offset.setValue(-1000); rendered(); assert not win.viewer.reference_rgb.any()
        win.compare_offset.setValue(0); win.compare_mode.setCurrentIndex(3); win.seek(0); rendered()
        win.toggle_play(); end=time.time()+.4
        while time.time()<end: app.processEvents(); QTest.qWait(10)
        win.pause(); assert win.doc.state.position>0 and win.viewer.comparing
        assert np.array_equal(win.viewer.rgb,win.viewer.reference_rgb)
        win.compare_enabled.setChecked(False); rendered(); assert not win.viewer.comparing
        assert win.viewer.image.width()==win.viewer.rgb.shape[1]
    finally: win.doc.saved_signature=win.doc.signature(); win.close(); app.processEvents()


def test_comparison_different_fps_and_stale_pair(prepared):
    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); m,_=prepared; d=Document(); d.append_media([m]); win.install_doc(d)
    calls=[]
    try:
        win.reference_decoder.request=lambda token,media,index,ahead=():calls.append((token,index))
        win.set_reference_sequence([dict(m,fps='12')]); win.seek(24)
        assert calls[-1][1]==12  # one second in both sources
        win.compare_media['frames']=96; win.rebuild_reference_index(); win.seek(191); assert calls[-1][1]==95  # last frame stays visible until the real end
        win.seek(24)
        token=win.token; a=np.full((2,2,3),10,np.uint8); b=np.full((2,2,3),20,np.uint8)
        win.frame_ready(token,a); assert win.comparison_pending['a'] is a
        win.reference_ready(token-1,b); assert win.comparison_pending['b'] is None
        win.reference_ready(token,b); assert win.rendered_token==token and win.viewer.reference_rgb is b
        win.seek(30); assert win.token>token; win.reference_ready(token,b); assert win.comparison_pending['b'] is None
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()

def test_vector_transport_loop_toggle():
    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    from widgets import TransportButton
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show()
    try:
        assert win.loop_btn.symbol=='once' and not win.loop_btn.isChecked()
        win.loop_btn.click(); assert win.playback_mode=='loop' and win.loop_btn.symbol=='loop' and win.loop_btn.isChecked()
        win.loop_btn.click(); assert win.playback_mode=='once' and not win.loop_btn.isChecked()
        win.set_loop(True); assert win.loop_btn.isChecked()
        playback=[b for b in win.transport_widget.findChildren(TransportButton) if type(b) is TransportButton]
        assert len(playback)==6
        for b in playback: assert (b.width(),b.height())==(36,34) and not b.text()
    finally: win.close(); app.processEvents()

def test_waveform_peaks_and_visual_normalization(tmp_path):
    from media import waveform_peaks,display_waveform,ensure_waveform
    path=tmp_path/'audio.s16'; audio=np.zeros((12000,2),dtype='<i2')
    audio[17,0]=300; audio[2222,1]=-32768; audio[6001,0]=-200
    path.write_bytes(audio.tobytes()); before=path.read_bytes()
    peaks=waveform_peaks(path,points=12)
    assert len(peaks)==12 and peaks.max()==1 and np.count_nonzero(peaks)==3
    quiet=np.array([0,.001,.002,.003,.004],np.float32); visual=display_waveform(quiet)
    assert visual[0]==0 and visual[-1]==1 and visual[1]>.2
    assert not display_waveform(np.zeros(10)).any()
    info=ensure_waveform({'audio':str(path),'has_audio':True}); assert Path(info['waveform']).exists()
    cached=np.load(info['waveform']); assert cached.max()==1
    assert path.read_bytes()==before

def test_duplicate_both_tracks_preserves_clipboard_and_history():
    d=Document(); d.state=State((Segment('a',0,12),Segment('a',12,24)),audio_segments=(Segment('b',0,12,True),Segment('b',12,24)))
    before=d.state; d.clipboard=(Segment('x',0,1),); d.audio_clipboard=(Segment('y',0,1),)
    assert d.duplicate_range(0,12)
    assert d.state.length==36 and len(d.state.segments)==3
    assert expanded(d.state.segments)==list(range(12))*2+list(range(12,24))
    assert d.state.audio[1].media=='b' and d.state.audio[1].muted
    assert d.clipboard==(Segment('x',0,1),) and d.audio_clipboard==(Segment('y',0,1),)
    d.undo(); assert d.state==before; d.redo(); assert d.state.length==36
    d.undo(); d.duplicate_range(0,12,21) # snaps after last video section
    assert expanded(d.state.segments)==list(range(24))+list(range(12))
    assert d.state.selection==(24,36)


def test_duplicate_context_and_alt_shift_drag(prepared):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPoint,QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); m,_=prepared; key=m['id']
    d=Document(); d.media={key:m}; d.state=State((Segment(key,0,24),Segment(key,48,72)),selection=(4,10)); win.install_doc(d); app.processEvents()
    try:
        assert not win.copy_audio.isChecked(); win.link_tracks.setChecked(False); win.leave_gap.setChecked(True)
        t=win.timeline; before=d.state
        def duplicate():
            menu=app.activePopupWidget()
            try: next(a for a in menu.actions() if a.text()=='Dupliquer le média').trigger()
            finally: menu.close()
        QTimer.singleShot(30,duplicate); point=QPoint(round(t.x_for(6)),t.track_y('audio')+9)
        t.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,t.mapToGlobal(point)))
        assert d.state.length==72 and d.state.selection==(24,48)
        assert expanded(d.state.audio)==expanded(d.state.segments)==list(range(24))*2+list(range(48,72))
        win.undo(); assert d.state==before
        mod=Qt.KeyboardModifier.AltModifier|Qt.KeyboardModifier.ShiftModifier
        QTest.mousePress(t,Qt.MouseButton.LeftButton,mod,QPoint(round(t.x_for(6)),60)); QTest.mouseMove(t,QPoint(round(t.x_for(48)),60))
        assert t.gesture=='copy' and t.drop_frame==48
        QTest.mouseRelease(t,Qt.MouseButton.LeftButton,mod,QPoint(round(t.x_for(48)),60))
        assert d.state.length==72 and expanded(d.state.audio)==expanded(d.state.segments)==list(range(24))+list(range(48,72))+list(range(24))
        win.undo(); assert d.state==before
    finally: d.saved_signature=d.signature(); win.close(); app.processEvents()


@pytest.mark.parametrize('first_rate,second_rate',[(12,30),(30,12)])
def test_mixed_frame_rates_preserve_time_and_export(tmp_path,monkeypatch,first_rate,second_rate):
    from media import run_ffmpeg,prepare_batch
    import av
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    paths=[]
    for rate in (first_rate,second_rate):
        path=tmp_path/f'source-{rate}.mp4'
        run_ffmpeg(['-f','lavfi','-i',f'testsrc2=size=160x90:rate={rate}:duration=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)])
        paths.append(str(path))
    media=prepare_batch(paths)
    assert [m['original_fps'] for m in media]==[str(first_rate),str(second_rate)]
    assert all(m['fps']==str(first_rate) and m['frames']==first_rate*2 for m in media)
    d=Document(Fraction(first_rate)); d.append_media(media)
    assert d.state.length==first_rate*4
    for m in media: assert Path(m['audio']).stat().st_size==2*48000*4
    out=tmp_path/'mixed.mp4'; export_video(d.state,d.media,d.fps,out)
    with av.open(str(out)) as c:
        assert c.streams.video[0].average_rate==first_rate
        assert sum(1 for _ in c.decode(video=0))==first_rate*4
    with av.open(str(out)) as c:
        audio=c.streams.audio[0]; assert abs(float(audio.duration*audio.time_base)-4)<.03


def test_default_panels_match_requested_layout():
    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.show(); app.processEvents()
    try:
        for key in ('timeline','transport','timecode'): assert not win.panel_widgets()[key].isHidden() and win.panel_actions[key].isChecked()
        for key in ('header','comparison','drawing'): assert win.panel_widgets()[key].isHidden() and not win.panel_actions[key].isChecked()
        assert not {'inspector','meta','status'} & win.panel_widgets().keys()
        assert win.library.isHidden() and not win.layout_editable and not win.layout_action.isChecked()
    finally: win.close(); app.processEvents()

def test_continuous_drag_wrap_has_no_jumps_and_restores_cursor():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF,QRect
    from drag import ContinuousDrag
    app=QApplication.instance() or QApplication([]); warps=[]
    drag=ContinuousDrag(QPointF(800,200),'x',warp=warps.append,screen_rect=QRect(0,0,1000,800))
    assert drag.move(QPointF(998,200)).x()==198 and warps[-1].x()==499
    assert drag.move(QPointF(997,200)).x()==198 # queued event from the old edge is ignored
    assert drag.move(QPointF(499,200)).x()==198 # warp itself contributes no distance
    assert drag.move(QPointF(799,200)).x()==498
    assert drag.move(QPointF(998,200)).x()==697
    assert drag.move(QPointF(499,200)).x()==697
    assert drag.move(QPointF(99,200)).x()==297
    drag.finish(); assert warps[-1].x()==800 and warps[-1].y()==200
    count=len(warps); drag.finish(); assert len(warps)==count
    both=ContinuousDrag(QPointF(500,400),'xy',warp=warps.append,screen_rect=QRect(0,0,1000,800))
    assert both.move(QPointF(998,798))==QPointF(498,398)
    assert both.move(QPointF(499,399))==QPointF(498,398)
    assert both.move(QPointF(600,500))==QPointF(599,499)


def test_continuous_numeric_and_video_scrub_use_accumulated_distance(monkeypatch):
    import widgets
    from drag import ContinuousDrag
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPointF,QRect
    from PySide6.QtGui import QMouseEvent
    app=QApplication.instance() or QApplication([]); warps=[]
    monkeypatch.setattr(widgets,'ContinuousDrag',lambda point,axes='x':ContinuousDrag(point,axes,warps.append,QRect(0,0,1000,800)))
    def event(kind,global_x,button=Qt.MouseButton.NoButton):
        return QMouseEvent(kind,QPointF(20,20),QPointF(global_x,200),button,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    from PySide6.QtCore import QEvent
    spin=widgets.ScrubDoubleSpinBox(); spin.setRange(-10000,10000); spin.setSingleStep(1)
    viewer=widgets.Viewer(); viewer.loaded=True; viewer.scrub_pixels=4; frames=[]; viewer.scrub.connect(frames.append)
    try:
        spin.eventFilter(spin.lineEdit(),event(QEvent.Type.MouseButtonPress,800,Qt.MouseButton.LeftButton))
        for x in (998,499,799): spin.eventFilter(spin.lineEdit(),event(QEvent.Type.MouseMove,x))
        assert spin.value()==49.8
        spin.eventFilter(spin.lineEdit(),event(QEvent.Type.MouseButtonRelease,799,Qt.MouseButton.LeftButton))
        assert warps[-1].x()==800
        viewer.mousePressEvent(event(QEvent.Type.MouseButtonPress,800,Qt.MouseButton.LeftButton))
        for x in (998,499,799): viewer.mouseMoveEvent(event(QEvent.Type.MouseMove,x))
        assert frames==[49,49,124]
        viewer.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease,799,Qt.MouseButton.LeftButton))
        assert warps[-1].x()==800
    finally: spin.close(); viewer.close()


def test_reference_offset_has_no_context_menu():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow()
    try:
        assert win.compare_offset.contextMenuPolicy()==Qt.ContextMenuPolicy.NoContextMenu
        assert win.compare_offset.lineEdit().contextMenuPolicy()==Qt.ContextMenuPolicy.NoContextMenu
    finally: win.close()

@pytest.mark.parametrize('selection,include_audio',[(None,False),((2,7),True),((0,10),False)])
def test_cut_single_range_all_and_history(selection,include_audio):
    d=Document(); d.state=State((Segment('a',0,5),Segment('b',20,25)),position=3,selection=selection)
    original=d.state; a,b=selection or (3,4)
    assert d.cut(include_audio)==b-a
    assert d.clipboard==slice_segments(original.segments,a,b)
    assert d.state.length==10-(b-a) and sum(s.length for s in d.state.audio)==d.state.length
    assert d.audio_clipboard==(slice_segments(original.audio,a,b) if include_audio else (Segment(None,0,b-a),))
    assert len(d.undo_stack)==1 and d.undo_stack[0][0]=='Couper les images'
    after=d.state; d.undo(); assert d.state==original; d.redo(); assert d.state==after
    d.state=replace(d.state,position=a); d.paste(include_audio)
    assert expanded(d.state.segments)==expanded(original.segments)
    if include_audio: assert expanded(d.state.audio)==expanded(original.audio)
    d.state=replace(d.state,selection=None,position=d.state.length)
    clipboard=d.clipboard; history=len(d.undo_stack)
    assert d.cut()==0 and d.clipboard==clipboard and len(d.undo_stack)==history


def test_cut_shortcut_timeline_and_text(prepared):
    from PySide6.QtWidgets import QApplication,QLineEdit
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QPoint
    from app import MainWindow
    app=QApplication.instance() or QApplication([]); win=MainWindow(); win.workspaces.switch('edit'); m,_=prepared
    d=Document(); d.media={m['id']:m}; d.state=State((Segment(m['id'],0,24),)); win.install_doc(d); win.show(); win.activateWindow(); app.processEvents()
    try:
        field=win.drawing.hex; win.drawing.panel.show(); app.processEvents(); field.setText('ABCDEF'); field.setFocus(); field.selectAll()
        QTest.keyClick(field,Qt.Key.Key_X,Qt.KeyboardModifier.ControlModifier); assert field.text()=='' and d.state.length==24
        # A timeline click must relinquish text-edit focus and route Ctrl+X to the montage.
        QTest.mouseClick(win.timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(win.timeline.x_for(3)),60)); app.processEvents()
        assert win.timeline.hasFocus()
        win.select(3,7)
        QTest.keyClick(win.timeline,Qt.Key.Key_X,Qt.KeyboardModifier.ControlModifier)
        assert d.state.length==20 and sum(s.length for s in d.clipboard)==4
        assert win.action_registry['Édition/Couper les images'][1]=='Ctrl+X'
        win.seek(20); win.paste_selection(); assert d.state.length==24 and d.state.audio[-1].media is None
    finally:
        d.saved_signature=d.signature(); win.close(); app.processEvents()
