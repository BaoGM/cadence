# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace
import wave,subprocess,time
import numpy as np
import av
from PySide6.QtCore import QRect
from test_drawing import application,window
from capture import CaptureDialog
from capture_audio import mux_audio,AudioTrack
from media import ffmpeg

def test_capture_options_default_sources_folder_and_region(window,application,tmp_path):
    d=CaptureDialog(window)
    assert not d.system_audio.isChecked() and not d.microphone.isChecked()
    assert d.full.isChecked() and d.folder.isEnabled() and d.browse.isEnabled() and not hasattr(d,'custom')
    d.region=QRect(40,60,120,90); d.update_region_ui(); application.processEvents()
    assert d.outline.isVisible() and d.zone.isChecked() and not d.full.isChecked()
    assert d.outline.geometry().width()==126
    d.folder.setText(str(tmp_path)); d.system_audio.setChecked(True); d.microphone.setChecked(True); d.save_settings(); d.reject()
    second=CaptureDialog(window)
    assert second.region==QRect(40,60,120,90) and second.folder.text()==str(tmp_path)
    assert second.system_audio.isChecked() and second.microphone.isChecked()
    second.format.setCurrentText('GIF'); assert not second.system_audio.isEnabled() and not second.microphone.isEnabled() and not second.audio_note.isHidden()
    second.reset_region(); assert second.full.isChecked() and second.outline.isVisible() and second.outline.full_screen
    second.reject(); d.deleteLater(); second.deleteLater()

def test_mix_sources_time_offsets_and_video_frames(tmp_path):
    video=tmp_path/'video.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=blue:s=64x48:r=12:d=2','-c:v','libx264',str(video)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    tracks=[]
    for name,freq,first in [('system',440,100.),('mic',880,100.5)]:
        path=tmp_path/(name+'.wav'); rate=48000
        data=(np.sin(np.arange(rate*2)/rate*2*np.pi*freq)*5000).astype('<i2')
        with wave.open(str(path),'wb') as f: f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(data.tobytes())
        tracks.append(SimpleNamespace(path=path,first_time=first,error=None))
    neighbour=tmp_path/'video-avec-son.mp4'; neighbour.write_bytes(b'previous recording')
    mux_audio(video,tracks,100.)
    with av.open(str(video)) as f:
        assert len(f.streams.audio)==1 and sum(1 for _ in f.decode(video=0))==24
    with av.open(str(video)) as f:
        resample=av.AudioResampler(format='fltp',layout='mono',rate=48000)
        samples=np.concatenate([a.to_ndarray().ravel() for frame in f.decode(audio=0) for a in resample.resample(frame)])
    def energy(a,b,freq):
        y=samples[round(a*48000):round(b*48000)]; spectrum=abs(np.fft.rfft(y)); frequencies=np.fft.rfftfreq(len(y),1/48000)
        return spectrum[abs(frequencies-freq)<10].max()
    assert energy(.1,.4,440)>energy(.1,.4,880)*10
    assert energy(.7,1.3,880)>100 and energy(.7,1.3,440)>100
    assert abs(len(samples)/48000-2)<.05 and neighbour.read_bytes()==b'previous recording'
    assert not list(tmp_path.glob('cadence-mux-*.mp4'))

def test_loopback_silence_gap_keeps_timing(tmp_path):
    # Exercise the callback's gap handling without accessing a microphone.
    track=AudioTrack.__new__(AudioTrack); track.path=tmp_path/'gap.wav'; track.rate=48000; track.channels=1; track.frames=0; track.first_time=None; track.error=None; track.stream=None; track.clock_offset=1000.
    track.file=wave.open(str(track.path),'wb'); track.file.setnchannels(1); track.file.setsampwidth(2); track.file.setframerate(track.rate)
    block=np.full(1024,1000,dtype='<i2').tobytes()
    track.callback(block,1024,{'input_buffer_adc_time':1,'current_time':1},0)
    track.callback(block,1024,{'input_buffer_adc_time':2,'current_time':2},0); track.stop()
    with wave.open(str(track.path)) as f: data=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
    assert len(data)==49024 and np.all(data[1024:48000]==0) and np.all(data[48000:]==1000)

def test_audio_finalize_error_always_releases_dialog(window,monkeypatch,tmp_path):
    import capture_audio
    d=CaptureDialog(window); calls=[]
    def fail(): raise OSError('Périphérique déconnecté')
    def close(): calls.append('closed'); raise OSError('Fermeture audio')
    d.audio=SimpleNamespace(stop=fail,close=close,tracks=[]); d.path=tmp_path/'silent.mp4'
    d.path.write_bytes(b'video intacte'); d.finish_audio(100.)
    assert d.mux_done.is_set() and d.audio is None and calls==['closed']
    assert 'déconnecté' in d.mux_error and d.path.read_bytes()==b'video intacte'
    d.reject(); d.deleteLater()
