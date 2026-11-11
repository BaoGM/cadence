# SPDX-License-Identifier: GPL-3.0-only
import logging,math,time
import numpy as np
from PySide6.QtCore import QObject,QTimer,QIODevice
from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QMediaDevices
from model import RATE,sample_at,TimelinePCM


def audio_fragment(pcm,frame,fps):
    start=sample_at(frame,fps)
    count=min(round(RATE*.12),max(round(RATE*.08),sample_at(frame+1,fps)-start))
    samples=np.frombuffer(pcm.read(start,count),dtype='<i2').reshape(-1,2).copy()
    fade=min(round(RATE*.0015),len(samples)//2)
    if fade:
        ramp=np.linspace(0,1,fade)[:,None]
        samples[:fade]=(samples[:fade]*ramp).astype('<i2'); samples[-fade:]=(samples[-fade:]*ramp[::-1]).astype('<i2')
    return samples.tobytes()


class AuditionDevice(QIODevice):
    def __init__(self,parent=None):
        super().__init__(parent); self.data=b''; self.position=0
        self.open(QIODevice.OpenModeFlag.ReadOnly|QIODevice.OpenModeFlag.Unbuffered)
    def isSequential(self): return True
    def atEnd(self): return False
    def bytesAvailable(self): return max(4096,len(self.data)-self.position)+super().bytesAvailable()
    def replace(self,data):
        self.data=data; self.position=0
    def readData(self,maxlen):
        data=self.data[self.position:self.position+maxlen]; self.position+=len(data)
        return data+bytes(maxlen-len(data))
    def writeData(self,data): return -1


class ScrubAudio(QObject):
    def __init__(self,parent=None):
        super().__init__(parent); self.enabled=True; self.volume=.8
        self.sink=None; self.buffer=AuditionDevice(self); self.pcm=None; self.signature=None; self.streaming=False
        self.pending=None; self.last_request=None; self.last_played=0.
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.flush)
        self.idle_timer=QTimer(self); self.idle_timer.setSingleShot(True); self.idle_timer.timeout.connect(self.stop)
    def set_enabled(self,enabled):
        self.enabled=bool(enabled)
        if not self.enabled: self.close()
    def set_volume(self,volume):
        self.volume=max(0.,min(1.,volume))
        if self.sink: self.sink.setVolume(self.volume)
        if not self.volume: self.stop()
    def request(self,state,media,fps,frame):
        if not self.enabled or not self.volume or not state.length or not 0<=frame<=state.length: self.stop(); return
        frame=min(frame,state.length-1)
        paths=tuple((key,media.get(key,{}).get('audio')) for key in sorted({s.media for s in state.audio if s.media is not None and not s.muted}))
        signature=(state.audio,fps,paths); request=(signature,frame)
        if request==self.last_request and (self.pending is not None or time.monotonic()-self.last_played<.08): return
        self.last_request=request; self.pending=(state,media,fps,frame,signature)
        if not self.timer.isActive(): self.timer.start(max(0,math.ceil((.04-(time.monotonic()-self.last_played))*1000)))
    def _create_sink(self):
        fmt=QAudioFormat(); fmt.setSampleRate(RATE); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        output=QMediaDevices.defaultAudioOutput()
        if output.isNull() or not output.isFormatSupported(fmt):
            logging.warning('Audio audition unavailable: no compatible output device'); return False
        self.sink=QAudioSink(output,fmt,self); self.sink.setBufferSize(round(RATE*.02)*4)
        return True
    def flush(self):
        pending=self.pending; self.pending=None
        if not pending or not self.enabled or not self.volume: return
        state,media,fps,frame,signature=pending; self.last_played=time.monotonic()
        try:
            if signature!=self.signature:
                if self.pcm: self.pcm.close()
                self.pcm=None; self.signature=None
                self.pcm=TimelinePCM(state.audio,media,fps); self.signature=signature
            data=audio_fragment(self.pcm,frame,fps)
            self.buffer.replace(data)
            if not any(data) and not self.streaming: return
            if self.sink is None and not self._create_sink(): return
            self.sink.setVolume(self.volume)
            if not self.streaming:
                self.sink.start(self.buffer); self.streaming=True
            self.idle_timer.start(350)
            if self.sink.error().name not in ('NoError','UnderrunError'):
                logging.warning('Audio audition error: %s',self.sink.error().name); self.close()
        except (OSError,ValueError,KeyError) as error:
            self.stop(); logging.warning('Audio preview unavailable: %s',error)
    def stop(self):
        self.timer.stop(); self.idle_timer.stop(); self.pending=None; self.last_request=None
        if self.sink: self.sink.reset()
        self.streaming=False; self.buffer.replace(b'')
    def close(self):
        self.stop()
        if self.sink: self.sink.deleteLater(); self.sink=None
        if self.pcm: self.pcm.close(); self.pcm=None
        self.signature=None
