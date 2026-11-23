# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import json
import time

import av
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from model import Document,Segment,with_tracks,TimelinePCM
from composite_media import LayerFrame,MixedPCM,frame_layers,canvas_size,decode_layers
from media import run_ffmpeg,prepare_media,PreviewReader,export_video


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def clips(tmp_path_factory):
    root=tmp_path_factory.mktemp('layers')
    entries=[]
    for color,frequency in [('red',440),('blue',880)]:
        path=root/(color+'.mp4')
        run_ffmpeg(['-f','lavfi','-i',f'color=c={color}:size=160x90:rate=24:duration=2',
                    '-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=48000:duration=2',
                    '-c:v','libx264','-c:a','aac',str(path)])
        entries.append(prepare_media(path))
    return entries


def document(clips):
    doc=Document(); doc.append_media([clips[0]])
    doc.add_media_track(); doc.append_media([clips[1]])
    return doc


def test_composition_order_transparency_and_export(application,clips,tmp_path):
    doc=document(clips)
    upper,lower=doc.state.tracks
    upper=replace(upper,segments=(replace(upper.segments[0],end=24,placement=(0.,0.,.5,.5)),),audio_segments=(Segment(None,0,24),))
    doc.state=with_tracks(doc.state,(upper,lower))
    reader=PreviewReader()
    try:
        first=decode_layers(reader,frame_layers(doc.state,doc.media,0),canvas_size(doc.state,doc.media),None).compose()
        later=decode_layers(reader,frame_layers(doc.state,doc.media,30),canvas_size(doc.state,doc.media),None).compose()
    finally: reader.close()
    assert first[20,20,0]>200 and first[70,130,2]>200
    assert later[20,20,2]>200
    output=tmp_path/'layers.mp4'
    export_video(doc.state,doc.media,doc.fps,output)
    with av.open(str(output)) as container:
        frames=[frame.to_ndarray(format='rgb24') for frame in container.decode(video=0)]
    assert len(frames)==48
    assert np.abs(frames[0].astype(int)-first.astype(int)).mean()<5
    assert np.abs(frames[30].astype(int)-later.astype(int)).mean()<5
    doc.reorder_media_track(lower.info.id,-1)
    reader=PreviewReader()
    try: front=decode_layers(reader,frame_layers(doc.state,doc.media,0),canvas_size(doc.state,doc.media),None).compose()
    finally: reader.close()
    assert front[20,20,2]>200 and front[20,20,0]<20


def test_audio_mix_and_export(clips,tmp_path):
    doc=document(clips)
    parts=[]
    for track in doc.state.tracks:
        pcm=TimelinePCM(track.audio,doc.media,doc.fps)
        try: parts.append(np.frombuffer(pcm.read(0,96000),dtype='<i2').astype(np.int32))
        finally: pcm.close()
    expected=np.clip(parts[0]+parts[1],-32768,32767).astype('<i2')
    mixed=MixedPCM(doc.state,doc.media,doc.fps)
    try: assert np.array_equal(np.frombuffer(mixed.read(0,96000),dtype='<i2'),expected)
    finally: mixed.close()
    output=tmp_path/'mix.wav'; export_video(doc.state,doc.media,doc.fps,output)
    with av.open(str(output)) as container:
        samples=np.concatenate([frame.to_ndarray().reshape(-1) for frame in container.decode(audio=0)])
    assert np.array_equal(samples,expected)


def test_tracks_reference_volume_and_dialog(application,clips,tmp_path,monkeypatch):
    from app import MainWindow,STYLE
    path=tmp_path/'preferences.json'
    path.write_text(json.dumps(dict(format='cadence-shortcuts',version=1,video_renderer='software',video_renderer_version=2)))
    monkeypatch.setenv('CADENCE_PREFS',str(path))
    application.setStyleSheet(STYLE)
    window=MainWindow(); window.workspaces.switch('edit'); window.show()
    doc=document(clips); window.install_doc(doc)
    def rendered():
        deadline=time.monotonic()+8
        while window.token!=window.rendered_token and time.monotonic()<deadline:
            application.processEvents(); QTest.qWait(10)
        assert window.token==window.rendered_token
    try:
        rendered(); timeline=window.timeline
        first,second=doc.state.tracks
        upper,lower=(y+8 for _,y,_ in timeline.media_rows())
        folded=timeline.height()
        assert folded==timeline.media_height()
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.NoModifier,QPoint(40,upper))
        assert doc.selected_track_ids==(first.info.id,)
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.ControlModifier,QPoint(40,lower))
        assert set(doc.selected_track_ids)=={first.info.id,second.info.id}
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.NoModifier,QPoint(9,lower))
        assert doc.state.second_track.info.audio_expanded
        assert timeline.height()>folded and timeline.height()==timeline.media_height()
        doc.exposure(1.)
        doc.select_track(first); doc.exposure(0.)
        doc.select_track(second,extend=True)
        window.refresh(); window.set_exposure(0.)
        assert [t.exposure for t in doc.state.tracks]==[0.,0.]
        window.use_track_reference(second.info.id); rendered()
        assert window.viewer.reference_rgb[40,80,2]>200
        assert window.viewer.rgb[40,80,0]>200
        assert window.comparison_snapshot()['reference_track']==second.info.id
        window.expand_media_audio(second.info.id,False)
        old=window.volume.value(); window.volume.setValue(50)
        event=QWheelEvent(QPointF(20,20),QPointF(window.viewer.mapToGlobal(QPoint(20,20))),QPoint(),QPoint(0,120),Qt.NoButton,Qt.ControlModifier,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(window.viewer,event)
        assert window.volume.value()==55
        window.sync3d.show_dialog(); dialog=window.sync3d.dialog
        application.processEvents(); dialog.resize(1,1); application.processEvents()
        assert dialog.width()>=dialog.minimumSizeHint().width()
        assert dialog.height()>=dialog.minimumSizeHint().height()
        for widget in (dialog.camera,dialog.drawing_mode,dialog.onion,dialog.send,dialog.remove):
            assert widget.isVisible() and widget.height()>=widget.minimumSizeHint().height()
        assert dialog.camera.mapTo(dialog,dialog.camera.rect().bottomLeft()).y()<dialog.drawing_mode.mapTo(dialog,QPoint()).y()
        assert dialog.drawing_mode.mapTo(dialog,dialog.drawing_mode.rect().bottomLeft()).y()<dialog.onion.mapTo(dialog,QPoint()).y()
        dialog.hide()
        window.edit_track_structure(doc.remove_media_track,second.info.id)
        assert not window.comparison_active()
        rendered()
    finally:
        doc.saved_signature=doc.signature(); window.close(); application.processEvents()


def test_global_drawings_overlay_both_tracks(application,clips,tmp_path):
    from drawing import DrawingKey,Mark
    doc=document(clips)
    mark=Mark(tool='brush',points=((.1,.5,1.),(.9,.5,1.)),size=.15,color='#00ff00')
    doc.state=replace(doc.state,drawings=(DrawingKey(0,48,(mark,)),))
    output=tmp_path/'drawn.mp4'
    export_video(doc.state,doc.media,doc.fps,output)
    with av.open(str(output)) as container:
        frame=next(container.decode(video=0)).to_ndarray(format='rgb24')
    assert frame[45,80,1]>180 and frame[45,80,0]<60
