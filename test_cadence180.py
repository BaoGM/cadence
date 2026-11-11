# SPDX-License-Identifier: GPL-3.0-only
import hashlib,json,threading
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import numpy as np
import pytest
from cadence_change import rate,settings,build_change,plan_ranges,change_ratio,rounded
from model import Document,State,Segment,sample_at
from drawing import Mark,DrawingKey
from media import prepare_media,run_ffmpeg,export_video,Cancelled
from test_drawing import application,window


@pytest.fixture
def fake_media(monkeypatch):
    media={key:dict(id=key,name=key,path=key,fps='24',original_fps='24',frames=240) for key in ('a','b')}
    def prepare(path,fps,progress,cancel,quality,cadence):
        original=media[path]; identity=hashlib.sha256(json.dumps(cadence,sort_keys=True).encode()).hexdigest()[:8]+path
        return dict(original,id=identity,cadence=cadence,frames=rounded(Fraction(240)/Fraction(cadence['speed'])))
    monkeypatch.setattr('media.prepare_media',prepare)
    return media


def change(state,media,target=12,mode='speed',ranges=None,pitch=True):
    ranges=ranges or plan_ranges(state,media,keys={'a'})
    return build_change(state,media,Fraction(24),ranges,target,mode,pitch,'native',lambda *a:None,threading.Event())


def test_timeline_remap_history_and_roundtrip(fake_media,tmp_path):
    m=Mark(points=((.5,.5,1),)); video=(Segment('b',0,24),Segment('a',12,60),Segment('b',24,48))
    audio=(Segment('b',0,40),Segment(None,0,8),Segment('a',36,60),Segment('b',24,48))
    old=State(video,audio_segments=audio,position=50,selection=(24,72),loop_range=(24,72),drawings=(DrawingKey(20,30,(m,)),DrawingKey(70,75,(m,))),frame_markers=(10,24,48,95))
    new,media=change(old,fake_media)
    assert new.length==144 and sum(s.length for s in new.audio)==144
    assert new.segments[0]==old.segments[0] and new.segments[-1]==old.segments[-1]
    assert (new.segments[1].start,new.segments[1].end)==(24,120)
    assert new.position==76 and new.selection==new.loop_range==(24,120)
    assert [(k.start,k.end) for k in new.drawings]==[(20,36),(116,123)]
    assert new.frame_markers==(10,24,72,143)
    d=Document();d.media=media;d.state=old;d.commit('cadence',new);d.undo();assert d.state==old;d.redo();assert d.state==new
    d.save(tmp_path/'rate.cadence');loaded=Document.load(tmp_path/'rate.cadence')
    assert loaded.fps==24 and loaded.state==new and loaded.to_data()['version']==14
    unlinked,_=change(replace(old,drawings_linked=False),fake_media)
    assert unlinked.drawings==old.drawings


def test_colliding_drawings_not_lost(fake_media,tmp_path):
    marks=tuple(Mark(points=((i/30,.5,1),)) for i in range(20))
    old=State((Segment('a',0,48),),drawings=tuple(DrawingKey(i,i+1,(m,)) for i,m in enumerate(marks)))
    new,media=change(old,fake_media,target=240)
    def leaves(items): return sum((leaves(m.children) if m.tool=='group' else [m] for m in items),[])
    assert leaves(tuple(m for k in new.drawings for m in k.marks))==list(marks)
    d=Document();d.media=media;d.state=new;d.save(tmp_path/'collision.cadence')
    assert Document.load(tmp_path/'collision.cadence').state==new


def test_multiple_instances_and_constant_duration(fake_media):
    old=State((Segment('a',0,48),Segment('b',0,48),Segment('a',60,108)))
    new,media=change(old,fake_media,target=30,mode='duration')
    assert new.length==old.length and new.segments[1]==old.segments[1]
    assert new.segments[0].media==new.segments[2].media!=old.segments[0].media
    assert media[new.segments[0].media]['cadence']==dict(rate='30',speed='1',preserve_pitch=True)
    new,media=change(old,fake_media,target=30)
    assert new.length==124 and new.segments[1]==old.segments[1]
    assert change_ratio(media[new.segments[0].media],12,'speed')==Fraction(5,2)
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled): build_change(old,fake_media,Fraction(24),[(0,48,'a')],12,'speed',True,'native',lambda *a:None,cancel)
    assert rate('29,97')==Fraction(30000,1001)
    for invalid in ('0','nan','241','-12'):
        with pytest.raises(ValueError): rate(invalid)


@pytest.fixture
def real_media(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    source=tmp_path/'source.mkv'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','ffv1','-c:a','pcm_s16le',str(source)])
    return prepare_media(source,Fraction(24))


@pytest.mark.parametrize('target,mode,pitch,frames,hz',[(12,'duration',True,48,440),(30,'speed',True,38,440),(12,'speed',True,96,440),(30,'speed',False,38,550),(12,'speed',False,96,220)])
def test_actual_video_audio_and_export(real_media,tmp_path,target,mode,pitch,frames,hz):
    import av
    real_media['id']='a';original=Path(real_media['path']).read_bytes();old=State((Segment('a',0,48),))
    new,media=change(old,{'a':real_media},target,mode,pitch=pitch)
    key=new.segments[0].media;converted=media[key];assert new.length==frames
    data=np.fromfile(converted['audio'],dtype='<i2').reshape(-1,2)[:,0].astype(float)
    center=data[len(data)//4:len(data)*3//4];freq=np.fft.rfftfreq(len(center),1/48000)[np.argmax(abs(np.fft.rfft(center*np.hanning(len(center)))))]
    assert abs(freq-hz)<4
    assert len(data)==sample_at(converted['frames'],Fraction(24))
    output=tmp_path/'result.mp4';export_video(new,media,Fraction(24),output,False)
    with av.open(str(output)) as c:
        stream=c.streams.video[0];assert stream.average_rate==24
        exported=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(exported)==frames
    with av.open(converted['proxy']) as c: preview=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert max(np.mean(abs(a.astype(float)-b)) for a,b in zip(exported,preview))<8
    if mode=='duration':
        assert all(np.array_equal(preview[i],preview[i+1]) for i in range(0,46,2))
    assert Path(real_media['path']).read_bytes()==original
    reloaded=prepare_media(real_media['path'],Fraction(24),cadence=converted['cadence'])
    assert reloaded['id']==key


@pytest.mark.parametrize('surface',['viewer','simple','detailed','drawing'])
@pytest.mark.parametrize('running',[False,True])
def test_scrub_restores_play_state(window,application,monkeypatch,surface,running):
    from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    w=window;w.drawing.choose_tool('cursor');w.request_frame=lambda:None;w.scrub_audio.request=lambda *a:None
    w.transport.running=running;calls=[]
    def pause(*a,**kw):w.transport.running=False
    def play():w.transport.running=True;calls.append(1)
    monkeypatch.setattr(w,'pause',pause);monkeypatch.setattr(w,'toggle_play',play)
    if surface=='viewer':widget=w.viewer;start=QPoint(widget.width()//2,widget.height()//2);end=start+QPoint(40,0)
    else:
        widget=w.timeline;widget.simple=surface=='simple';y=32 if widget.simple else int(widget.track_y('drawing' if surface=='drawing' else 'video')+4)
        start=QPoint(int(widget.x_for(3)),y);end=QPoint(int(widget.x_for(10)),y)
    QTest.mousePress(widget,Qt.MouseButton.LeftButton,pos=start)
    assert not w.transport.running
    application.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(widget.mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(widget,Qt.MouseButton.LeftButton,pos=end)
    assert w.transport.running==running and len(calls)==int(running)
    QTest.mouseRelease(widget,Qt.MouseButton.LeftButton,pos=end);assert len(calls)==int(running)
    w.transport.running=False


def test_one_frame_conversion_and_separate_audio(real_media,tmp_path):
    source=tmp_path/'single.mkv'
    run_ffmpeg(['-i',real_media['path'],'-frames:v','1','-an','-c:v','ffv1',str(source)])
    one=prepare_media(source,Fraction(24));one['id']='a'
    result,media=change(State((Segment('a',0,1),)),{'a':one},240)
    assert result.length==1 and media[result.segments[0].media]['frames']>=1
    sound=tmp_path/'sound.wav';run_ffmpeg(['-i',real_media['path'],'-vn',str(sound)])
    audio=prepare_media(sound,Fraction(24));audio['id']='sound';real_media['id']='a'
    state=State((Segment('a',0,48),),audio_segments=(Segment('sound',0,48),))
    changed,media=change(state,{'a':real_media,'sound':audio},12)
    assert changed.length==96 and changed.audio[0].length==96
    assert media[changed.audio[0].media]['has_video'] is False


def test_dialog_apply_context_and_session(window,application,monkeypatch,tmp_path,fake_media):
    from cadence_dialog import CadenceDialog
    from PySide6.QtWidgets import QDialogButtonBox
    from PySide6.QtCore import QPoint
    from session import write_snapshot,read_session
    w=window;w.doc.media={key:dict(value,width=640,height=360) for key,value in fake_media.items()};w.request_frame=lambda:None
    w.doc.state=State((Segment('a',0,48),Segment('b',0,48)));w.refresh()
    menu=w.timeline.context_menu(QPoint(int(w.timeline.x_for(5)),int(w.timeline.track_y('video')+3)))
    action=next(a for a in menu.actions() if a.text().startswith('Changer la cadence'))
    assert action.isEnabled()
    captured=[]
    def dialog_exec(dialog):
        dialog.rate.setCurrentText('12');dialog.mode.setCurrentIndex(1)
        assert dialog.summary.text().endswith('2.000 s → 4.000 s')
        dialog.rate.setCurrentText('bad');assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.rate.setCurrentText('12');assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.show();application.processEvents();dialog.grab().save(str(tmp_path/'cadence-dialog.png'));captured.append(dialog.values());return 1
    monkeypatch.setattr(CadenceDialog,'exec',dialog_exec)
    monkeypatch.setattr(w,'begin_task',lambda title,fn,success:success(fn(lambda *a:None,threading.Event())))
    action.trigger();menu.deleteLater()
    assert captured and w.doc.state.length==144 and w.doc.fps==24 and len(w.doc.undo_stack)==1
    w.doc.review=dict(reference='a',reference_cadence=dict(rate='12',speed='1/2',preserve_pitch=True),reference_fps='24')
    path=tmp_path/'session.json';write_snapshot(path,(w.doc.state,w.doc.media,w.doc.fps,w.doc.review,None,True),{})
    payload,restored=read_session(path);assert restored.state==w.doc.state and restored.review==w.doc.review
    assert payload['document']['version']==14


def test_shift_scrub_and_resume_cancellation(window,application,monkeypatch):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    w=window;w.request_frame=lambda:None;w.scrub_audio.request=lambda *a:None;w.transport.running=True;calls=[]
    monkeypatch.setattr(w,'pause',lambda *a,**kw:setattr(w.transport,'running',False))
    monkeypatch.setattr(w,'toggle_play',lambda:calls.append(1))
    t=w.timeline;pos=QPoint(int(t.x_for(3))+1,int(t.track_y('video')+3))
    QTest.mousePress(t,Qt.MouseButton.LeftButton,pos=pos);t.update_range_drag(12,Qt.KeyboardModifier.ShiftModifier)
    assert w.doc.state.selection==(3,13) and w.doc.state.position==12 and not w.transport.running
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,pos=pos);assert calls==[1]
    w.transport.running=True;w.begin_scrub();w.doc=Document();w.end_scrub();assert calls==[1]


def test_real_transport_resumes_after_video_scrub(window,application,real_media):
    from PySide6.QtCore import Qt,QPoint,QEventLoop,QTimer
    from PySide6.QtTest import QTest
    w=window;doc=Document();doc.media={real_media['id']:real_media};doc.state=State((Segment(real_media['id'],0,48),))
    w.install_doc(doc);w.drawing.choose_tool('cursor');w.viewer.setFocus()
    loop=QEventLoop();poll=QTimer();poll.timeout.connect(lambda:loop.quit() if w.viewer.image is not None else None);poll.start(10)
    timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(3000);loop.exec();poll.stop();timeout.stop()
    assert w.viewer.image is not None
    w.transport.set_volume(0);w.toggle_play()
    assert w.transport.running
    v=w.viewer;pos=QPoint(v.width()//2,v.height()//2)
    QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=pos);assert not w.transport.running
    w.seek(12);QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=pos)
    assert w.transport.running
    w.pause();QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=pos);w.seek(16)
    QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=pos);assert not w.transport.running


def test_english_dialog(window,application,monkeypatch,tmp_path):
    from cadence_dialog import CadenceDialog
    from PySide6.QtWidgets import QLabel,QDialogButtonBox
    import ui_text
    monkeypatch.setattr(ui_text,'_language','en')
    dialog=CadenceDialog(window,[(0,30,'a')]);dialog.show();application.processEvents()
    assert dialog.windowTitle()=='Change frame rate'
    assert dialog.mode.itemText(0)=='Keep duration' and dialog.pitch.text()=='Preserve audio pitch'
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).text()=='&Cancel'
    assert all('cadence' not in label.text().casefold() and 'durée' not in label.text().casefold() for label in dialog.findChildren(QLabel))
    dialog.grab().save(str(tmp_path/'cadence-dialog-en.png'));dialog.close();dialog.deleteLater()
