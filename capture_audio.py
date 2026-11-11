# SPDX-License-Identifier: GPL-3.0-only
"""Optional Windows output-loopback / microphone capture and timed MP4 muxing."""
import subprocess, tempfile, time, wave, logging
from pathlib import Path
import pyaudiowpatch as pa
from media import ffmpeg

class AudioTrack:
    def __init__(self,manager,device,path):
        self.path=Path(path); self.rate=round(device['defaultSampleRate']); self.channels=int(device['maxInputChannels'])
        if self.channels<1: raise RuntimeError('Périphérique audio sans entrée disponible.')
        self.file=wave.open(str(path),'wb'); self.file.setnchannels(self.channels); self.file.setsampwidth(2); self.file.setframerate(self.rate)
        self.frames=0; self.first_time=None; self.error=None; self.stream=None
        try:
            self.stream=manager.open(format=pa.paInt16,channels=self.channels,rate=self.rate,input=True,input_device_index=device['index'],
                frames_per_buffer=1024,stream_callback=self.callback,start=False)
        except Exception: self.file.close(); raise
    def silence(self,frames):
        while frames>0:
            count=min(frames,8192); self.file.writeframesraw(bytes(count*self.channels*2)); self.frames+=count; frames-=count
    def callback(self,data,count,timing,status):
        try:
            adc=timing.get('input_buffer_adc_time',0); now=timing.get('current_time',0)
            offset=getattr(self,'clock_offset',None)
            stamp=adc+offset if offset is not None and adc>0 else time.time()+(adc-now if adc>0 and now>0 and abs(adc-now)<10 else -count/self.rate)
            if self.first_time is None: self.first_time=stamp
            expected=round((stamp-self.first_time)*self.rate)
            # WASAPI may stop delivering buffers while the output is silent.
            if expected-self.frames>1024: self.silence(expected-self.frames)
            self.file.writeframesraw(data); self.frames+=len(data)//(self.channels*2)
            return (None,pa.paContinue)
        except Exception as e:
            logging.exception('Audio capture callback failed'); self.error=str(e) or type(e).__name__; return (None,pa.paAbort)
    def start(self):
        self.started=time.time()
        try: self.clock_offset=self.started-self.stream.get_time()
        except OSError: self.clock_offset=None
        self.stream.start_stream()
    def stop(self):
        if self.stream is not None:
            stream=self.stream; self.stream=None
            try:
                if stream.is_active(): stream.stop_stream()
            except Exception as e: logging.exception('Audio capture stop failed'); self.error=self.error or str(e)
            finally:
                try: stream.close()
                except Exception as e: logging.exception('Audio capture close failed'); self.error=self.error or str(e)
        if self.file is not None:
            if self.first_time is None:
                self.first_time=getattr(self,'started',time.time()); self.silence(max(1,round((time.time()-self.first_time)*self.rate)))
            self.file.close(); self.file=None

class AudioCapture:
    def __init__(self,system=False,microphone=False):
        self.tracks=[]; self.manager=None; self.temp=tempfile.TemporaryDirectory(prefix='cadence-audio-')
        try:
            self.manager=pa.PyAudio(); host=self.manager.get_host_api_info_by_type(pa.paWASAPI)
            if system:
                device=self.manager.get_default_wasapi_loopback()
                self.tracks.append(AudioTrack(self.manager,device,Path(self.temp.name)/'ordinateur.wav'))
            if microphone:
                index=host.get('defaultInputDevice',-1)
                device=self.manager.get_device_info_by_index(index) if index>=0 else self.manager.get_default_input_device_info()
                if device.get('isLoopbackDevice'): raise RuntimeError('Aucun microphone par défaut disponible.')
                self.tracks.append(AudioTrack(self.manager,device,Path(self.temp.name)/'microphone.wav'))
        except Exception as e:
            self.close(); raise RuntimeError('Impossible d’ouvrir la source sonore sélectionnée. Vérifiez le périphérique de sortie / microphone Windows.\n'+str(e)) from e
    def start(self):
        for track in self.tracks: track.start()
    def stop(self):
        for track in self.tracks: track.stop()
    def close(self):
        try: self.stop()
        finally:
            try:
                if self.manager is not None: self.manager.terminate(); self.manager=None
            finally: self.temp.cleanup()

def mux_audio(video,tracks,video_start):
    import av
    video=Path(video)
    with av.open(str(video)) as source:
        stream=source.streams.video[0]
        duration=float(stream.duration*stream.time_base) if stream.duration is not None else source.duration/1_000_000
    args=[ffmpeg(),'-v','error','-y','-i',str(video)]; filters=[]; names=[]
    for index,track in enumerate(tracks,1):
        if track.error: raise RuntimeError('Capture audio interrompue : '+track.error)
        args+=['-i',str(track.path)]; offset=track.first_time-video_start
        trim=max(0,-offset); delay=max(0,round(offset*48000))
        filters.append(f'[{index}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start={trim:.9f},asetpts=PTS-STARTPTS,adelay={delay}S:all=1,apad,atrim=duration={duration:.9f}[a{index}]')
        names.append(f'[a{index}]')
    filters.append(''.join(names)+f'amix=inputs={len(names)}:duration=longest:normalize=0,alimiter=limit=0.95:level=false:latency=1[a]')
    # Reserve our own file so failure cleanup cannot remove an existing recording.
    with tempfile.NamedTemporaryFile(prefix='cadence-mux-',suffix='.mp4',dir=video.parent,delete=False) as temporary:
        output=Path(temporary.name)
    try:
        args+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-t',f'{duration:.9f}','-movflags','+faststart',str(output)]
        result=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode: raise RuntimeError(result.stderr.decode('utf-8',errors='replace')[-2000:])
        output.replace(video)
    finally:
        if output.exists(): output.unlink()
