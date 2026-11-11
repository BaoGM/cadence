# SPDX-License-Identifier: GPL-3.0-only
import json,logging,subprocess,tempfile,threading,time,uuid
from pathlib import Path
from fractions import Fraction
from model import RATE,sample_at

_locks={}
_guard=threading.Lock()


def create_audio_file(path,size):
    with Path(path).open('wb') as out:
        import os
        if os.name=='nt':
            import ctypes,msvcrt
            returned=ctypes.c_ulong()
            ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(out.fileno())),0x900c4,None,0,None,0,ctypes.byref(returned),None)
        out.truncate(size)


def write_manifest(data):
    path=Path(data['audio']).with_name('media.json')
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(dict(data,id=path.parent.name),ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_audio(data,progress=None,cancel=None):
    from media import ffmpeg,Cancelled,ensure_waveform
    from cadence_change import audio_filter
    progress=progress or (lambda value,message:None)
    cancel=cancel or threading.Event()
    path=Path(data['audio']); expected=sample_at(data['frames'],Fraction(data['fps']))*4
    progress(0.,'Préparation de l’audio synchronisé')
    from PySide6.QtCore import QLockFile
    file_lock=QLockFile(str(path.with_name('audio.lock')))
    with _guard: lock=_locks.setdefault(str(path),threading.Lock())
    while not lock.acquire(timeout=.1):
        if cancel.is_set(): raise Cancelled()
    try:
        while not file_lock.tryLock(100):
            if cancel.is_set(): raise Cancelled()
            if file_lock.error()!=QLockFile.LockError.LockFailedError: raise OSError('Verrouillage du cache audio impossible.')
        if cancel.is_set(): raise Cancelled()
        try:
            cached=json.loads(path.with_name('media.json').read_text(encoding='utf-8'))
            if not cached.get('audio_pending') and path.stat().st_size==expected:
                return dict(data,audio_pending=False,waveform=cached['waveform'])
        except (OSError,ValueError,KeyError): pass
        started=time.perf_counter(); samples=expected//4
        af=f'asetpts=PTS-{data.get("video_start",0):.12f}/TB,aresample={RATE}:async=1:first_pts=0'+audio_filter(data.get('cadence'))+f',apad,atrim=end_sample={samples}'
        args=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-copyts','-i',data['path'],'-map','0:a:0','-vn','-af',af,'-ar',str(RATE),'-ac','2','-c:a','pcm_s16le','-f','s16le','pipe:1']
        with tempfile.TemporaryFile(mode='w+b') as errors:
            proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            stopped=threading.Event()
            def watch():
                while not stopped.wait(.1):
                    if cancel.is_set():
                        try: proc.kill()
                        except OSError: pass
                        return
            watcher=threading.Thread(target=watch,daemon=True); watcher.start()
            count=0; reported=0.
            try:
                # Keep the mapped file size stable while playback reads the decoded prefix.
                with path.open('r+b',buffering=0) as out:
                    while True:
                        chunk=proc.stdout.read(65536)
                        if cancel.is_set(): raise Cancelled()
                        if not chunk: break
                        if count+len(chunk)>expected: raise ValueError('Durée audio décodée incorrecte.')
                        out.write(chunk); count+=len(chunk)
                        now=time.monotonic()
                        if now-reported>=.2:
                            reported=now; progress(count/expected,'Préparation de l’audio synchronisé')
                code=proc.wait()
                if cancel.is_set(): raise Cancelled()
                if code:
                    errors.seek(0); raise RuntimeError(errors.read().decode('utf-8',errors='replace')[-3500:] or f'FFmpeg : erreur {code}')
                if count!=expected: raise ValueError('Durée audio décodée incorrecte.')
            finally:
                stopped.set()
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdout.close(); watcher.join()
        result=dict(data,audio_pending=False)
        ensure_waveform(result,cancel); write_manifest(result)
        logging.info('Media audio %.3fs, samples=%s: %s',time.perf_counter()-started,samples,data['path'])
        progress(1.,'Audio prêt')
        return result
    finally:
        if file_lock.isLocked(): file_lock.unlock()
        lock.release()
