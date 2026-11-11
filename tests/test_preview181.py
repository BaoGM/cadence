# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from types import SimpleNamespace
import av
import numpy as np
import pytest
from PySide6.QtCore import QEvent,QPoint,QObject
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QWidget
from cache_ram import FrameCache
from media import PreviewReader,frame_cache_key
from scrub_audio import ScrubAudio,AuditionDevice,audio_fragment
from test_preview110 import audio_timeline,source4k
from test_drawing import application,window


def test_decoded_cache_obeys_shared_budget_and_releases():
    frame=av.VideoFrame(64,32,'yuv420p');size=sum(p.buffer_size for p in frame.planes)
    cache=FrameCache(size*8)
    for i in range(25):
        cache.put(('rgb',i),np.zeros((32,64,3),np.uint8));cache.put_decoded(i,frame)
        assert cache.bytes<=cache.budget and cache.raw_bytes<=cache.budget//4
    assert cache.get_decoded(24) is frame
    cache.set_budget(size);assert cache.bytes<=size and not cache.raw
    cache.clear();assert cache.bytes==cache.raw_bytes==0 and not cache.frames


def test_reuse_decoded_frame_across_preview_qualities(source4k):
    from media import probe
    source=probe(source4k);stat=source4k.stat()
    media=dict(source,proxy=str(source4k),size=stat.st_size,mtime_ns=stat.st_mtime_ns,direct_start='0',preview_quality='native',proxy_width=3840,proxy_height=2160)
    reader=PreviewReader(budget=256*1024**2,retain_decoded=True)
    reference=PreviewReader(budget=0)
    try:
        native=reader.read(media,2)
        smaller=dict(media,proxy_width=854,proxy_height=480,preview_quality='480p')
        identity=(media['proxy'],media['size'],media['mtime_ns'])
        assert reader.cache.get_decoded((identity,1)) is not None
        decoder=reader.decoders[identity]
        actual=reader.read(smaller,1)
        assert reader.decoders[identity] is decoder and reader.positions[identity]==2
        assert actual.shape==(480,854,3) and np.array_equal(actual,reference.read(smaller,1))
        assert native.shape==(2160,3840,3)
        assert reader.cache.get(frame_cache_key(smaller,1)) is actual
    finally:reader.close();reference.close()


def test_prefetch_prioritizes_direction(application):
    from engine import Decoder
    owner=QObject();owner.frame_cache=FrameCache(1000);decoder=Decoder(owner)
    media=dict(proxy='a');other=dict(proxy='b')
    ahead=[(media,i) for i in (9,8,11,12)]+[(other,0)]
    decoder.request(1,media,10,ahead)
    assert [i for _,i in decoder.prefetch]==[11,12,0]
    decoder.request(2,media,9,[(media,i) for i in (7,8,10,11)])
    assert [i for _,i in decoder.prefetch]==[8,7]
    decoder.request(3,media,9,[(media,i) for i in (7,8,10,11)])
    assert [i for _,i in decoder.prefetch]==[8,7]


def test_audio_stream_replaces_unread_fragment_and_then_silence(application):
    stream=AuditionDevice()
    stream.replace(b'abcdefgh');assert bytes(stream.read(4))==b'abcd'
    stream.replace(b'WXYZ');assert bytes(stream.read(8))==b'WXYZ'+bytes(4)
    assert bytes(stream.read(8))==bytes(8) and not stream.atEnd()
    stream.close()


def test_audio_does_not_restart_between_frames(application,audio_timeline):
    state,media,_=audio_timeline
    class Sink:
        starts=0;resets=0
        def setVolume(self,value):self.volume=value
        def start(self,device):self.starts+=1;self.device=device
        def reset(self):self.resets+=1
        def error(self):return SimpleNamespace(name='NoError',value=0)
        def deleteLater(self):pass
    player=ScrubAudio();sink=Sink()
    def create():player.sink=sink;return True
    player._create_sink=create
    try:
        for frame in (0,1,2,3,4,18,19,20,21,22,23,24):
            player.request(state,media,Fraction(24),frame);player.timer.stop();player.flush()
            assert sink.starts==1 and sink.resets==0
            assert player.buffer.data==audio_fragment(player.pcm,min(frame,23),Fraction(24))
        player.last_played-=1;player.request(state,media,Fraction(24),24)
        assert player.pending is not None
        player.stop();assert sink.resets==1 and not player.streaming and not player.buffer.data
        player.set_volume(0);player.request(state,media,Fraction(24),0);assert player.pending is None
        player.set_volume(.5);player.request(state,media,Fraction(24),0);player.timer.stop();player.flush()
        assert sink.starts==2 and sink.volume==.5
        player.set_enabled(False);assert player.pcm is None and player.sink is None
    finally:player.close()


def test_tooltip_filter_covers_new_widgets_and_retains_text(application):
    from ui_style import set_tooltips_enabled
    class Target(QWidget):
        tips=0
        def event(self,event):
            if event.type()==QEvent.Type.ToolTip:self.tips+=1;return True
            return super().event(event)
    set_tooltips_enabled(False);widget=Target();widget.setToolTip('Aide')
    try:
        def send():application.sendEvent(widget,QHelpEvent(QEvent.Type.ToolTip,QPoint(1,1),QPoint(1,1)))
        send();assert widget.tips==0 and widget.toolTip()=='Aide'
        set_tooltips_enabled(True);send();assert widget.tips==1
        set_tooltips_enabled(False);send();assert widget.tips==1
    finally:set_tooltips_enabled(True);widget.deleteLater()


def test_tooltip_preference_roundtrip(window,tmp_path,monkeypatch):
    from preferences import ShortcutDialog,defaults,validate,load_preferences
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'))
    registry=window.action_registry;data=defaults(registry)
    assert data['tooltips'] and validate(dict(data,tooltips=False),registry)['tooltips'] is False
    dialog=ShortcutDialog(registry,data,window)
    try:
        dialog.tooltips.setChecked(False);dialog.accept()
        assert not dialog.result_data['tooltips'] and not load_preferences(registry)['tooltips']
        window.apply_preferences(dialog.result_data)
        from PySide6.QtWidgets import QApplication
        assert not QApplication.instance().cadence_tooltips.enabled
    finally:
        from ui_style import set_tooltips_enabled
        set_tooltips_enabled(True);dialog.deleteLater()
