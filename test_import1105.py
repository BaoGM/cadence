# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from pathlib import Path
import json,subprocess,threading
import numpy as np
import pytest
from media import prepare_media,run_ffmpeg,ffmpeg,PreviewReader,Cancelled,export_video
from model import TimelinePCM,Segment,State,sample_at
from audio_prepare import prepare_audio
from test_drawing import application,window


@pytest.mark.parametrize('source_rate,target',[('30','24'),('24','12'),('12','30'),('24000/1001','24'),('24','24000/1001')])
def test_direct_rate_matches_ffmpeg(tmp_path,monkeypatch,source_rate,target):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    source=tmp_path/'source.avi'
    run_ffmpeg(['-f','lavfi','-i',f'testsrc=size=64x48:rate={source_rate}:duration=2','-c:v','ffv1',str(source)])
    rate=Fraction(target); native=prepare_media(source); media=prepare_media(source,rate)
    assert media['proxy']==str(source) and native['proxy']==str(source)
    expected=subprocess.check_output([ffmpeg(),'-v','error','-i',str(source),'-vf',f'setpts=PTS-STARTPTS,fps={rate}','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    expected=np.frombuffer(expected,np.uint8).reshape(-1,48,64,3)
    assert media['frames']==len(expected)
    reader=PreviewReader(retain_decoded=True)
    try:
        for frame in [*range(media['frames']),*range(media['frames']-1,-1,-3)]:
            reader.read(native,min(frame,native['frames']-1))
            assert np.array_equal(reader.read(media,frame),expected[frame]),frame
    finally: reader.close()


def test_deferred_audio_updates_mapped_playback_and_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    assert media['audio_pending'] and 'waveform' not in media
    pcm=TimelinePCM((Segment(media['id'],0,media['frames']),),{media['id']:media},Fraction(media['fps']))
    try:
        assert not any(pcm.read(0,48000))
        result=prepare_audio(media)
        assert not result['audio_pending'] and any(pcm.read(0,48000))
        assert Path(result['audio']).stat().st_size==sample_at(result['frames'],Fraction(result['fps']))*4
        cached=prepare_media(media['path'],defer_audio=True)
        assert not cached['audio_pending'] and Path(cached['waveform']).is_file()
    finally: pcm.close()


def test_audio_cancel_is_not_a_valid_completed_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    cancel=threading.Event(); cancel.set()
    with pytest.raises(Cancelled): prepare_audio(media,cancel=cancel)
    assert json.loads(Path(media['audio']).with_name('media.json').read_text(encoding='utf-8'))['audio_pending']
    result=prepare_media(media['path'])
    assert not result['audio_pending'] and Path(result['waveform']).is_file()


def test_audio_interrupted_write_retries_without_replacing_mapped_file(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    cancel=threading.Event()
    pcm=TimelinePCM((Segment(media['id'],0,media['frames']),),{media['id']:media},Fraction(media['fps']))
    try:
        with pytest.raises(Cancelled): prepare_audio(media,lambda value,message:cancel.set() if value>0 else None,cancel)
        cached=prepare_media(media['path'],defer_audio=True); assert cached['audio_pending']
        result=prepare_audio(cached)
        assert pcm.read(0,48000)==Path(result['audio']).read_bytes()[:48000*4]
    finally: pcm.close()


def test_export_finishes_pending_audio(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    state=State((Segment(media['id'],0,24),)); output=tmp_path/'export.mp4'
    export_video(state,{media['id']:media},Fraction(media['fps']),output)
    assert not json.loads(Path(media['audio']).with_name('media.json').read_text(encoding='utf-8'))['audio_pending']
    audio=subprocess.check_output([ffmpeg(),'-v','error','-i',str(output),'-map','0:a:0','-f','s16le','pipe:1'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert any(audio)


def test_background_audio_arrives_without_pausing_window(tmp_path,monkeypatch,window,application):
    from model import Document
    import time
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    doc=Document(Fraction(media['fps'])); doc.append_media([media]); window.install_doc(doc)
    calls=[]; monkeypatch.setattr(window,'pause',lambda *args,**kwargs:calls.append('pause'))
    stop=time.monotonic()+15
    while window.audio_jobs.active and time.monotonic()<stop:
        application.processEvents(); time.sleep(.01)
    assert not window.audio_jobs.active and not calls
    assert not doc.media[media['id']]['audio_pending'] and media['id'] in window.timeline.wave
    assert window.audio_progress.isHidden()


def test_export_waits_for_shared_background_audio(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    writing=threading.Event(); release=threading.Event(); waiting=threading.Event()
    def progress(value,message):
        if value>0 and not writing.is_set():
            writing.set(); assert release.wait(10)
    state=State((Segment(media['id'],0,24),)); output=tmp_path/'shared.mp4'
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker=pool.submit(prepare_audio,media,progress)
        try:
            assert writing.wait(10)
            export=pool.submit(export_video,state,{media['id']:media},Fraction(media['fps']),output,progress=lambda *args:waiting.set())
            assert waiting.wait(10) and not export.done()
        finally: release.set()
        assert not worker.result(timeout=15)['audio_pending']
        assert export.result(timeout=15)==str(output)
    audio=subprocess.check_output([ffmpeg(),'-v','error','-i',str(output),'-map','0:a:0','-f','s16le','pipe:1'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert any(audio)


def test_background_queue_cancels_removed_media_and_retries(tmp_path,monkeypatch,application):
    import time
    from audio_jobs import AudioJobs
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',defer_audio=True)
    entered=threading.Event(); calls=[]; real=prepare_audio
    def prepare(data,progress,cancel):
        calls.append(data['id'])
        if len(calls)==1:
            entered.set(); assert cancel.wait(10); raise Cancelled()
        return real(data,progress,cancel)
    monkeypatch.setattr('audio_jobs.prepare_audio',prepare)
    jobs=AudioJobs(); ready=[]; failed=[]; jobs.ready.connect(ready.append); jobs.failed.connect(failed.append)
    def wait(predicate):
        end=time.monotonic()+15
        while not predicate() and time.monotonic()<end: application.processEvents(); time.sleep(.01)
        assert predicate()
    try:
        jobs.set_media([media]); wait(entered.is_set)
        jobs.set_media([]); wait(lambda:jobs.active is None)
        assert not ready and not failed
        jobs.set_media([media]); wait(lambda:jobs.active is None)
        assert len(ready)==1 and not ready[0]['audio_pending'] and not failed
    finally: jobs.stop()


def test_audio_worker_can_be_destroyed_before_application_exit(tmp_path):
    import sys,os
    script='''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
from smoke import check_native_import
app=QApplication([]); window=QWidget(); window.show(); app.processEvents()
assert check_native_import(Path(sys.argv[1]))['background_audio']
window.close(); app.processEvents()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',CADENCE_CACHE=str(tmp_path/'cache'))
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=Path(__file__).parent,env=env,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
