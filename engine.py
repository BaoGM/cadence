# SPDX-License-Identifier: GPL-3.0-only
"""Qt audio transport and latest-request-wins preview decoding."""
import threading, time, logging
from PySide6.QtCore import QThread, Signal, QIODevice
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from model import RATE, sample_at, TimelinePCM
from media import PreviewReader, Cancelled, DecodeSuperseded, frame_cache_key

def preview_source(media):
    return media.get('proxy') or media.get('path') or media.get('id') or id(media)

class Task(QThread):
    progress = Signal(float,str)
    result = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    def __init__(self,fn,parent=None):
        super().__init__(parent); self.fn=fn; self.cancel=threading.Event()
    def run(self):
        try:
            value=self.fn(lambda p,m:self.progress.emit(p,m),self.cancel)
            if self.cancel.is_set(): self.cancelled.emit()
            else: self.result.emit(value)
        except Cancelled: self.cancelled.emit()
        except Exception as e:
            logging.exception('Media task failed'); self.failed.emit(str(e).strip() or type(e).__name__)

class Decoder(QThread):
    ready=Signal(int,object)
    failed=Signal(int,str)
    def __init__(self,parent=None):
        super().__init__(parent); self.cache=getattr(parent,'frame_cache',None); self.condition=threading.Condition(); self.requested=None; self.prefetch=[]; self.stopping=False; self.generation=0; self.last_target=None; self.backwards=False
    def request(self,token,media,index,ahead=()):
        cached=self.cache.get(frame_cache_key(media,index)) if self.cache is not None and 'proxy' in media else None
        with self.condition:
            self.generation+=1
            self.requested=(token,media,index) if cached is None else None
            source=preview_source(media)
            if self.last_target is None or self.last_target[0]!=source: self.backwards=False
            elif index!=self.last_target[1]: self.backwards=index<self.last_target[1]
            self.last_target=(source,index)
            same=[entry for entry in ahead if preview_source(entry[0])==source and (entry[1]<index if self.backwards else entry[1]>index)]
            other=[entry for entry in ahead if preview_source(entry[0])!=source]
            same.sort(key=lambda item:abs(item[1]-index))
            self.prefetch=same+other; self.condition.notify()
        if cached is not None: self.ready.emit(token,cached)
    def run(self):
        reader=PreviewReader(cache=self.cache,retain_decoded=True) if self.cache is not None else PreviewReader(retain_decoded=True)
        try:
            while True:
                with self.condition:
                    while self.requested is None and not self.prefetch and not self.stopping: self.condition.wait()
                    if self.stopping: break
                    if self.requested is not None:
                        token,media,index=self.requested; self.requested=None
                    else:
                        media,index=self.prefetch.pop(0); token=None
                    generation=self.generation
                try:
                    arr=reader.read(media,index,lambda:self.stopping or generation!=self.generation)
                    if token is not None: self.ready.emit(token,arr)
                except DecodeSuperseded: continue
                except Exception as e:
                    logging.exception('Frame decoding failed at %s in %s',index,media.get('path'))
                    if token is not None: self.failed.emit(token,str(e).strip() or type(e).__name__)
        finally: reader.close()
    def stop(self):
        with self.condition:
            self.stopping=True; self.condition.notify()
        self.wait()

class PCMDevice(QIODevice):
    def __init__(self,pcm,start,a,b,passes,parent=None):
        super().__init__(parent)
        self.pcm=pcm; self.start=start; self.a=a; self.b=b; self.passes=passes
        self.position=start; self.pass_number=1; self.total_read=0
        self.finished=False
        self.open(QIODevice.OpenModeFlag.ReadOnly)
    def isSequential(self): return True
    def atEnd(self): return self.finished
    def bytesAvailable(self): return (0 if self.finished else 65536)+super().bytesAvailable()
    def readData(self,maxlen):
        remaining=maxlen//4
        chunks=[]
        while remaining>0 and not self.finished:
            n=min(remaining,self.b-self.position)
            if n:
                chunks.append(self.pcm.read(self.position,n)); self.position+=n; self.total_read+=n; remaining-=n
            if self.position>=self.b:
                if self.passes and self.pass_number>=self.passes: self.finished=True
                else: self.position=self.a; self.pass_number+=1
        return b''.join(chunks)
    def writeData(self,data): return -1

class Transport:
    def __init__(self,parent=None):
        self.parent=parent; self.sink=None; self.device=None; self.pcm=None; self.running=False; self.suspended=False; self.volume=.8
    def start(self,state,media,fps,mode,passes):
        self.stop()
        a,b=state.selection or state.loop_range or (0,state.length)
        if b<=a: return
        self.a,self.b,self.fps=a,b,fps
        self.start_frame=state.position if a<=state.position<b else a
        self.passes=0 if mode=='loop' else (passes if mode=='count' else 1)
        self.started=time.perf_counter()
        self.running=True
        self.pcm=TimelinePCM(state.audio,media,fps)
        self.device=PCMDevice(self.pcm,sample_at(self.start_frame,fps),sample_at(a,fps),sample_at(b,fps),self.passes)
        fmt=QAudioFormat(); fmt.setSampleRate(RATE); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        output=QMediaDevices.defaultAudioOutput()
        self.has_audio_device=not output.isNull() and output.isFormatSupported(fmt)
        if self.has_audio_device:
            self.sink=QAudioSink(output,fmt,self.parent)
            self.sink.setBufferSize(19200); self.sink.setVolume(self.volume); self.sink.start(self.device)
            self.has_audio_device=self.sink.error().value==0
            if not self.has_audio_device: self.sink.reset(); self.sink.deleteLater(); self.sink=None
    def clock(self):
        if not self.running: return self.start_frame,1,True
        elapsed=self.sink.processedUSecs()/1e6 if self.sink else time.perf_counter()-self.started
        consumed=int(elapsed*RATE)
        first=sample_at(self.b,self.fps)-sample_at(self.start_frame,self.fps)
        full=sample_at(self.b,self.fps)-sample_at(self.a,self.fps)
        total=first+(self.passes-1)*full if self.passes else None
        done=total is not None and consumed>=total
        if self.sink and self.device.finished and self.sink.state().name=='IdleState': done=True
        if done: return self.b-1,max(1,self.passes),True
        if consumed<first:
            frame=self.start_frame+int(consumed*float(self.fps)/RATE); p=1
        else:
            left=consumed-first
            p=2+left//full; frame=self.a+int((left%full)*float(self.fps)/RATE)
        return min(self.b-1,frame),p,False
    def set_loop(self,enabled):
        if not (self.running or self.suspended): return
        if self.suspended:
            elapsed=self.sink.processedUSecs()/1e6 if self.sink else self.held_at-self.started
            consumed=int(elapsed*RATE)
            first=sample_at(self.b,self.fps)-sample_at(self.start_frame,self.fps)
            full=sample_at(self.b,self.fps)-sample_at(self.a,self.fps)
            current=1 if consumed<first else 2+(consumed-first)//full
        else: current=self.clock()[1]
        self.passes=0 if enabled else current
        if self.device:
            self.device.passes=self.passes
            if enabled and self.device.finished:
                self.device.finished=False
                self.device.readyRead.emit()
    def hold(self):
        self.held_at=time.perf_counter()
        if self.sink: self.sink.suspend()
        self.running=False; self.suspended=True
    def resume(self):
        self.started += time.perf_counter()-self.held_at
        if self.sink: self.sink.resume()
        self.running=True; self.suspended=False
    def stop(self):
        self.running=False; self.suspended=False
        if self.sink: self.sink.reset(); self.sink.deleteLater(); self.sink=None
        if self.device: self.device.close(); self.device=None
        if self.pcm: self.pcm.close(); self.pcm=None
    def set_volume(self,value):
        self.volume=value
        if self.sink: self.sink.setVolume(value)
