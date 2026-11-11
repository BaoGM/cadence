# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
from dataclasses import replace
from fractions import Fraction
import json
import numpy as np
import pytest
from test_drawing import application,window
from media import prepare_media,run_ffmpeg,PreviewReader
from model import Document,State,Segment,TimelinePCM,RATE
from scrub_audio import ScrubAudio,audio_fragment
from preferences import ShortcutDialog,defaults,validate


@pytest.fixture(scope='module')
def source4k(tmp_path_factory):
    root=tmp_path_factory.mktemp('source4k'); path=root/'4k.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=red:s=3840x2160:r=12:d=0.25','-c:v','libx264','-preset','ultrafast',str(path)])
    return path


def test_native_presets_and_decoder_quality_change(tmp_path,monkeypatch,source4k):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    reader=PreviewReader(); ids=set()
    try:
        for quality,width,height in [('720p',1280,720),('native',3840,2160),('480p',854,480),('1080p',1920,1080),('4k',3840,2160)]:
            m=prepare_media(source4k,quality=quality); ids.add(m['id'])
            assert m['preview_quality']==quality and m['proxy_height']==height and abs(m['proxy_width']-width)<=2
            assert m['frames']==3
            # Projects retain their media IDs when rebuilding only their previews.
            m['id']='same-project-media'
            assert reader.read(m,0).shape[:2]==(m['proxy_height'],m['proxy_width'])
        assert len(ids)==5
        small=prepare_media(Path(__file__).resolve().parents[1]/'assets/Demonstration.mp4',quality='4k')
        assert (small['proxy_width'],small['proxy_height'])==(960,540)
    finally: reader.close()


def test_changing_open_preview_keeps_edits_and_reference(window,application,tmp_path,monkeypatch,source4k):
    w=window; monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(source4k,quality='720p'); doc=Document(Fraction(12)); doc.media={media['id']:media}
    doc.state=State((Segment(media['id'],0,3),)); doc.saved_signature=doc.signature(); w.install_doc(doc)
    w.select(1,2); w.copy_selection(); w.use_reference(media)
    old=doc.state; old_clip=doc.clipboard; old_saved=doc.saved_signature
    def task(title,fn,success): success(fn(lambda *args:None,None))
    monkeypatch.setattr(w,'begin_task',task)
    w.preferences['preview_quality']='720p'
    prefs=dict(w.preferences,preview_quality='native'); w.apply_preferences(prefs)
    assert doc.state==old and doc.clipboard==old_clip and doc.saved_signature==old_saved
    assert doc.media[media['id']]['proxy_width']==3840 and w.compare_media['proxy_width']==3840
    assert w.compare_media['id']==media['id'] and w.compare_enabled.isChecked()


def test_preview_preferences_are_not_shortcut_settings(window,monkeypatch,tmp_path):
    from PySide6.QtWidgets import QFileDialog,QMessageBox
    w=window; data=defaults(w.action_registry)
    assert data['preview_quality']=='native' and data['scrub_audio']
    assert validate(dict(data,preview_quality=[]),w.action_registry)['preview_quality']=='native'
    dialog=ShortcutDialog(w.action_registry,data,w)
    try:
        assert [dialog.preview_quality.itemData(i) for i in range(dialog.preview_quality.count())]==['native','480p','720p','1080p','4k']
        dialog.preview_quality.setCurrentIndex(2); dialog.scrub_audio.setChecked(False)
        source=tmp_path/'keys.json'; source.write_text(json.dumps(data),encoding='utf-8')
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(source),'')); dialog.import_file()
        assert dialog.collect()['preview_quality']=='720p' and not dialog.collect()['scrub_audio']
        monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:QMessageBox.StandardButton.Yes); dialog.reset_all()
        assert dialog.collect()['preview_quality']=='720p' and not dialog.collect()['scrub_audio']
        target=tmp_path/'exported.json'; monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),'')); dialog.export_file()
        exported=json.loads(target.read_text(encoding='utf-8')); assert 'preview_quality' not in exported and 'scrub_audio' not in exported
        dialog.accept(); assert dialog.result_data['preview_quality']=='720p' and not dialog.result_data['scrub_audio']
    finally: dialog.deleteLater()


@pytest.fixture
def audio_timeline(tmp_path):
    data=np.repeat((np.arange(RATE,dtype=np.int32)%20000+1000).astype('<i2')[:,None],2,axis=1)
    path=tmp_path/'audio.s16'; path.write_bytes(data.tobytes())
    media={'a':{'audio':str(path)}}
    state=State((Segment('a',0,24),),audio_segments=(Segment('a',12,18),Segment(None,0,6),Segment('a',0,6,muted=True),Segment('a',6,12)))
    return state,media,data


def test_audio_fragments_follow_edited_audio_gaps_and_muting(audio_timeline):
    state,media,data=audio_timeline; pcm=TimelinePCM(state.audio,media,Fraction(24))
    try:
        heard=np.frombuffer(audio_fragment(pcm,0,Fraction(24)),dtype='<i2').reshape(-1,2)
        assert 0.079<len(heard)/RATE<.081
        assert np.array_equal(heard[100:200],data[24100:24200])
        assert np.all(heard[0]==0) and np.all(heard[-1]==0)
        assert not any(audio_fragment(pcm,7,Fraction(24))) and not any(audio_fragment(pcm,13,Fraction(24)))
        assert len(audio_fragment(pcm,23,Fraction(24)))==2000*4
    finally: pcm.close()


def test_audio_preview_replaces_pending_request_and_respects_volume(application,audio_timeline,monkeypatch):
    state,media,_=audio_timeline; heard=[]
    class Sink:
        def error(self):
            from types import SimpleNamespace
            return SimpleNamespace(value=0,name='NoError')
        def reset(self): pass
        def setVolume(self,value): self.volume=value
        def start(self,buffer): heard.append((self.volume,buffer.data))
        def deleteLater(self): pass
    player=ScrubAudio()
    def create(): player.sink=Sink(); return True
    monkeypatch.setattr(player,'_create_sink',create)
    try:
        player.set_volume(.35)
        player.request(state,media,Fraction(24),0); player.request(state,media,Fraction(24),20)
        player.timer.stop(); player.flush()
        assert len(heard)==1 and heard[0][0]==.35
        assert heard[0][1]==audio_fragment(player.pcm,20,Fraction(24))
        player.request(state,media,Fraction(24),20); assert player.pending is None
        player.request(state,media,Fraction(24),21); player.set_volume(0)
        assert not player.timer.isActive() and player.pending is None
        player.request(state,media,Fraction(24),22); player.flush(); assert len(heard)==1
        player.set_volume(.5); player.set_enabled(False); player.request(state,media,Fraction(24),0)
        assert player.pending is None and player.pcm is None
    finally: player.close()


def test_navigation_calls_audio_without_starting_playback(window,monkeypatch):
    w=window; w.request_frame=lambda:None; calls=[]
    monkeypatch.setattr(w.scrub_audio,'request',lambda state,media,fps,frame:calls.append(frame))
    w.step(1); assert calls[-1]==1 and not w.transport.running
    w.timeline_seek(8); assert calls[-1]==8
    w.select(2,13,12); assert calls[-1]==12 and w.doc.state.selection==(2,13)
    w.viewer.scrub.emit(5); assert calls[-1]==5
    w.volume.setMuted(True); assert w.scrub_audio.volume==0
    w.volume.setMuted(False); assert w.scrub_audio.volume==w.volume.value()/100
    w.scrub_audio.pending=('pending',); w.pause(); assert w.scrub_audio.pending is None


def test_onion_defaults_and_source_relative_labels(window):
    from PySide6.QtWidgets import QLabel
    d=window.drawing
    assert d.ghost.value()==100
    labels=[label.text() for label in d.panel.findChildren(QLabel)]
    assert 'Images précédentes' in labels and 'Images suivantes' in labels
    assert not any(' · bleu' in text or ' · rouge' in text for text in labels)
