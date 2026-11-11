# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, os, subprocess, tempfile, threading, uuid, time, logging
from cache_ram import FrameCache
from collections import OrderedDict
from progress_values import FFmpegProgress
from fractions import Fraction
from pathlib import Path
import numpy as np
from model import RATE, sample_at, TimelinePCM

class Cancelled(Exception): pass

PREVIEW_SIZES={'480p':(854,480),'720p':(1280,720),'1080p':(1920,1080),'4k':(3840,2160)}

def ffmpeg(): return str(Path(__file__).parent/'vendor'/'ffmpeg.exe')

def cache_root():
    root = Path(os.environ.get('CADENCE_CACHE',Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'CadenceStudio'/'cache'))
    root.mkdir(parents=True,exist_ok=True)
    return root

def run_ffmpeg(args, progress=None, cancel=None, duration=0):
    progress = progress or (lambda value,message:None)
    with tempfile.TemporaryFile(mode='w+b') as err:
        proc = subprocess.Popen([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',*args,'-progress','pipe:1'],stdout=subprocess.PIPE,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        stopped = threading.Event()
        def watch():
            while not stopped.wait(.1):
                if cancel and cancel.is_set():
                    try: proc.kill()
                    except OSError: pass
                    return
        watcher = threading.Thread(target=watch,daemon=True)
        watcher.start()
        last_progress=0.0; progress_values=FFmpegProgress(duration)
        try:
            for raw in proc.stdout:
                line = raw.decode('utf-8',errors='replace').strip()
                if line.startswith('out_time_us='):
                    now=time.monotonic()
                    if now-last_progress>=.1:
                        last_progress=now
                        progress(progress_values.update(line.split('=',1)[1]),'Traitement des médias')
            code = proc.wait()
            if cancel and cancel.is_set(): raise Cancelled()
            if code:
                err.seek(0)
                raise RuntimeError(err.read().decode('utf-8',errors='replace')[-3500:] or f'FFmpeg : erreur {code}')
            progress(1.,'Traitement des médias')
        finally:
            stopped.set()
            if proc.poll() is None: proc.kill(); proc.wait()
            proc.stdout.close()


def probe(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.video or (Path(path).suffix.lower() in ('.wav','.mp3') and container.streams.audio):
            if not container.streams.audio: raise ValueError('Ce média ne contient aucune piste audio ou vidéo.')
            a=container.streams.audio[0]
            duration=float(a.duration*a.time_base) if a.duration else float(container.duration or 0)/1e6
            return dict(fps='24',width=1280,height=720,duration=duration,video_start=0,has_audio=True,has_video=False,hdr=False,frames=0,codec=a.codec_context.name,container=container.format.name)
        v = container.streams.video[0]
        fps = Fraction(v.average_rate or v.guessed_rate or 24).limit_denominator(1001000)
        if not 1 <= fps <= 240 and v.codec_context.name=='gif':
            # GIF can merge static frames into long holds. Normalize the preview
            # rate, while FFmpeg retains their timestamps and full duration.
            guessed=Fraction(v.guessed_rate or 24)
            fps=guessed if 1<=guessed<=240 else Fraction(24)
        if not 1 <= fps <= 240: raise ValueError('Cadence non prise en charge (1 à 240 images/s).')
        duration = float(v.duration*v.time_base) if v.duration else float(container.duration or 0)/1e6
        start = float((v.start_time or 0)*v.time_base)
        hdr = str(v.codec_context.color_trc) in ('16','18')
        return {'fps':str(fps),'width':v.width,'height':v.height,'duration':duration,'video_start':start,'has_audio':bool(container.streams.audio),'hdr':hdr,'frames':v.frames,'codec':v.codec_context.name,'container':container.format.name}


def waveform_peaks(path,points=6000,cancel=None):
    """Peak envelope, bounded memory; includes both stereo channels and every sample."""
    if not Path(path).stat().st_size: return np.zeros(1,np.float32)
    data=np.memmap(path,dtype='<i2',mode='r')
    try:
        step=max(1,(len(data)+points-1)//points)
        peaks=np.zeros((len(data)+step-1)//step,np.float32)
        for i,start in enumerate(range(0,len(data),step)):
            if i%64==0 and cancel and cancel.is_set(): raise Cancelled()
            peaks[i]=np.abs(data[start:start+step].astype(np.int32)).max()/32768
        return peaks
    finally: data._mmap.close()

def ensure_waveform(data,cancel=None):
    path=Path(data['audio']).with_name('waveform-v1.npy')
    valid=False
    if path.exists():
        try:
            values=np.load(path,allow_pickle=False); valid=values.ndim==1 and 0<len(values)<=6000 and np.isfinite(values).all()
        except (OSError,ValueError): pass
    if not valid:
        values=waveform_peaks(data['audio'],cancel=cancel) if data.get('has_audio',True) else np.zeros(1,np.float32)
        tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with tmp.open('wb') as f: np.save(f,values,allow_pickle=False)
        tmp.replace(path)
    data['waveform']=str(path)
    return data

def display_waveform(values):
    values=np.maximum(np.asarray(values,dtype=np.float32),0)
    audible=values[values>0]
    if not len(audible): return values
    # Robust visual gain avoids a single transient flattening the rest of the clip.
    scale=max(float(np.percentile(audible,95)),1/32768)
    return np.clip(values/scale,0,1)


def direct_preview(source,info,fps,quality,cancel=None):
    import av
    source_fps=Fraction(info['fps'])
    if not info['frames'] or info['codec']=='gif': return None
    if not any(name in info['container'].split(',') for name in ('mov','mp4','avi')): return None
    if abs(info['duration']*float(source_fps)-info['frames'])>.1: return None
    started=time.perf_counter()
    with av.open(str(source)) as container:
        stream=container.streams.video[0]
        if stream.sample_aspect_ratio not in (None,Fraction(1)): return None
        first=None
        for index,frame in enumerate(container.decode(video=0)):
            if cancel and cancel.is_set(): raise Cancelled()
            if frame.pts is None or getattr(frame,'rotation',0): return None
            stamp=Fraction(frame.pts)*frame.time_base
            if first is None: first=stamp
            if abs((stamp-first)*source_fps-index)>Fraction(1,100): return None
            if index>=min(15,info['frames']-1): break
        if first is None: raise ValueError('Aucune image décodable dans ce fichier.')
    width,height=info['width'],info['height']
    if quality!='native':
        mw,mh=PREVIEW_SIZES[quality]; ratio=min(1,mw/width,mh/height)
        width=max(2,int(width*ratio)//2*2); height=max(2,int(height*ratio)//2*2)
    logging.info('Direct preview validation %.3fs: %s',time.perf_counter()-started,source)
    return {'start':str(first),'size':(width,height)}


def prepare_media(path, fps=None, progress=None, cancel=None, quality='native',cadence=None,defer_audio=False):
    from cadence_change import settings,video_filter,audio_filter
    cadence=settings(cadence)
    import av
    progress = progress or (lambda value,message:None)
    started=time.perf_counter()
    source = Path(path).resolve()
    stat = source.stat()
    info = probe(source)
    logging.info('Media metadata %.3fs: %s',time.perf_counter()-started,source)
    if info['hdr']: raise ValueError('Cadence accepte les médias SDR. Convertissez ce média HDR en SDR avant import.')
    fps = Fraction(fps or info['fps'])
    duration=info['duration']/float(Fraction(cadence['speed'])) if cadence else info['duration']
    if quality not in ('native',*PREVIEW_SIZES): raise ValueError('Qualité d’aperçu inconnue.')
    variant='|cadence-v1-'+json.dumps(cadence,sort_keys=True) if cadence else ''
    key = hashlib.sha256(f'{source}|{stat.st_size}|{stat.st_mtime_ns}|{fps}|proxy-v6-{quality}{variant}'.encode()).hexdigest()[:24]
    root = cache_root()/key
    root.mkdir(parents=True,exist_ok=True)
    manifest = root/'media.json'
    cached=None
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if Path(data['proxy']).is_file() and Path(data['audio']).stat().st_size == sample_at(data['frames'],fps)*4:
                cached=data
        except (ValueError,KeyError,TypeError,OSError): pass
    if cached is not None:
        if cached.get('audio_pending'):
            if not defer_audio:
                from audio_prepare import prepare_audio
                cached=prepare_audio(cached,progress,cancel)
        else: ensure_waveform(cached,cancel)
        progress(1,'Aperçu retrouvé dans le cache')
        return cached
    proxy = root/'preview.avi'
    audio = root/'audio.s16'
    if info.get('has_video') is False:
        effect=audio_filter(cadence)
        run_ffmpeg(['-i',str(source),'-map','0:a:0','-vn',*(['-af','aresample=48000'+effect] if effect else []),'-ar',str(RATE),'-ac','2','-c:a','pcm_s16le','-f','s16le',str(audio)],lambda p,m:progress(p*.95,'Préparation de l’audio'),cancel,duration)
        import math
        frames=math.ceil(Fraction(audio.stat().st_size//4,RATE)*fps)
        if not frames: raise ValueError('Aucun échantillon audio décodable dans ce fichier.')
        with audio.open('r+b') as out: out.truncate(sample_at(frames,fps)*4)
        data=dict(id=key,path=str(source),name=source.name,size=stat.st_size,mtime_ns=stat.st_mtime_ns,fps=str(fps),original_fps=str(fps),frames=frames,width=1280,height=720,proxy_width=1280,proxy_height=720,proxy=str(source),audio=str(audio),has_audio=True,has_video=False,preview_quality=quality)
        if cadence: data['cadence']=cadence
        ensure_waveform(data,cancel); manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        progress(1,'Média prêt'); logging.info('Audio preparation %.3fs: %s',time.perf_counter()-started,source)
        return data
    try: direct=None if cadence else direct_preview(source,info,fps,quality,cancel)
    except av.error.FFmpegError:
        logging.exception('Direct decoder unavailable; preparing FFmpeg preview: %s',source)
        direct=None
    progress(0,'Préparation de la vidéo image par image')
    if direct:
        from cadence_change import rounded
        proxy=source; frames=max(1,rounded(Fraction(info['frames'])*fps/Fraction(info['fps']))); pw,ph=direct['size']
    else:
        if quality=='native': scale='scale=iw:ih'
        else:
            width,height=PREVIEW_SIZES[quality]
            scale=f'scale=w=min({width}\\,iw):h=min({height}\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2'
        vf = video_filter(fps,cadence)+f',{scale},setsar=1'
        run_ffmpeg(['-i',str(source),'-map','0:v:0','-vf',vf,'-an','-c:v','mjpeg','-q:v','3','-threads',str(min(4,os.cpu_count() or 2)),'-pix_fmt','yuvj420p',str(proxy)],lambda p,m:progress(p*.8,'Préparation de l’aperçu'),cancel,duration)
        with av.open(str(proxy)) as c:
            v = c.streams.video[0]
            frames = v.frames
            pw,ph = v.width,v.height
            if not frames: frames = sum(1 for _ in c.decode(video=0))
    if not frames: raise ValueError('Aucune image décodable dans ce fichier.')
    samples = sample_at(frames,fps)
    from audio_prepare import create_audio_file,prepare_audio,write_manifest
    create_audio_file(audio,samples*4)
    data = {'id':key,'path':str(source),'name':source.name,'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'fps':str(fps),'original_fps':info['fps'],'frames':frames,'width':info['width'],'height':info['height'],'proxy_width':pw,'proxy_height':ph,'proxy':str(proxy),'audio':str(audio),'has_audio':info['has_audio']}
    data['preview_quality']=quality
    data['video_start']=info['video_start']
    data['audio_pending']=bool(info['has_audio'])
    if cadence: data['cadence']=cadence
    if direct: data.update(direct_start=direct['start'],direct_fps=info['fps'],direct_frames=info['frames'])
    write_manifest(data)
    if info['has_audio']:
        if not defer_audio: data=prepare_audio(data,lambda p,m:progress(.8+p*.19,m),cancel)
    else:
        ensure_waveform(data,cancel); write_manifest(data)
    progress(1,'Média prêt')
    logging.info('Media preparation %.3fs, direct=%s, duration=%.3fs, source=%s',time.perf_counter()-started,bool(direct),info['duration'],source)
    return data


def validate_media(info):
    path = Path(info['path'])
    if not path.is_file(): raise FileNotFoundError(f'Média source introuvable : {path}')
    st = path.stat()
    if st.st_size != info['size'] or st.st_mtime_ns != info['mtime_ns']:
        raise ValueError(f'Le média source a changé depuis l’import : {path.name}. Réimportez-le dans un nouveau projet.')


def exposure_lut(ev):
    values = np.arange(256,dtype=np.float64)/255
    linear = np.where(values <= .04045,values/12.92,((values+.055)/1.055)**2.4)
    linear = np.clip(linear * (2**float(ev)),0,1)
    encoded = np.where(linear <= .0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
    return np.clip(np.floor(encoded*255+.5),0,255).astype(np.uint8)


def exposure_filter(ev):
    gain = 2**float(ev)
    linear = 'if(lte(val/255,0.04045),val/255/12.92,pow((val/255+0.055)/1.055,2.4))'
    exposed = f'clip(({linear})*{gain:.12f},0,1)'
    result = f'floor(255*if(lte({exposed},0.0031308),12.92*{exposed},1.055*pow({exposed},1/2.4)-0.055)+0.5)'
    return "lutrgb=r='"+result+"':g='"+result+"':b='"+result+"'"

class DecodeSuperseded(Exception):
    pass


def prefetch_frames(media,index,start,end,budget,backward=True):
    size=max(1,media.get('proxy_width',media.get('width',1280))*media.get('proxy_height',media.get('height',720))*3)
    radius=max(1,min(48,int(budget)//size//4))
    ahead=[(media,i) for i in range(index+1,min(end,index+radius+1))]
    if not backward: return ahead
    behind=[(media,i) for i in range(index-1,max(start,index-radius)-1,-1)]
    return ahead[:2]+behind+ahead[2:]


def preview_frame_index(media,index):
    if 'direct_fps' not in media: return index
    value=Fraction(2*index+1,2)*Fraction(media['direct_fps'])/Fraction(media['fps'])
    return max(0,min(media['direct_frames']-1,-(-value.numerator//value.denominator)-1))


def frame_cache_key(media,index):
    return (media['proxy'],media.get('size'),media.get('mtime_ns'),media.get('preview_quality','native'),preview_frame_index(media,index))


class PreviewReader:
    def __init__(self, budget=None, cache=None, max_containers=8, retain_decoded=False):
        self.containers = OrderedDict(); self.decoders={}; self.positions={}; self.pending={}; self.targets={}
        self.max_containers=max(1,int(max_containers))
        self.cache = cache if cache is not None else FrameCache(budget)
        self.owns_cache = cache is None
        self.retain_decoded=retain_decoded
        self.hardware=set(); self.hardware_failed=set(); self.hardware_reformatters={}
    def pixels(self,frame,media):
        return frame.to_ndarray(format='rgb24',width=media.get('proxy_width',frame.width),height=media.get('proxy_height',frame.height))
    def read(self, media, index, superseded=None):
        if media.get('has_video') is False: return np.zeros((media['proxy_height'],media['proxy_width'],3),np.uint8)
        identity=(media['proxy'],media.get('size'),media.get('mtime_ns'))
        try: return self._read(media,index,superseded)
        except DecodeSuperseded: raise
        except Exception:
            if identity not in self.hardware: raise
            logging.warning('Hardware preview failed at frame %s; retrying software: %s',index,media['proxy'],exc_info=True)
            self.hardware.discard(identity); self.hardware_failed.add(identity)
            self.hardware_reformatters.pop(identity,None)
            self.cache.discard_decoded_source(identity)
            container=self.containers.pop(identity,None)
            if container is not None: container.close()
            self.decoders.pop(identity,None); self.positions.pop(identity,None); self.pending.pop(identity,None); self.targets.pop(identity,None)
            return self._read(media,index,superseded)
    def _read(self, media, index, superseded=None):
        if media.get('has_video') is False: return np.zeros((media['proxy_height'],media['proxy_width'],3),np.uint8)
        import av
        identity=(media['proxy'],media.get('size'),media.get('mtime_ns'))
        key = frame_cache_key(media,index)
        index=preview_frame_index(media,index)
        cached = self.cache.get(key)
        if cached is not None: return cached
        if self.retain_decoded:
            decoded=self.cache.get_decoded((identity,index))
            if decoded is not None:
                if superseded is not None and superseded(): raise DecodeSuperseded()
                arr=self.pixels(decoded,media); self.cache.put(key,arr); return arr
        path = media['proxy']
        if identity not in self.containers:
            while len(self.containers)>=self.max_containers:
                old,container=self.containers.popitem(last=False)
                self.decoders.pop(old,None); self.positions.pop(old,None); self.pending.pop(old,None); self.targets.pop(old,None); container.close()
                self.hardware.discard(old)
                self.hardware_reformatters.pop(old,None)
            from hardware_decode import open_preview
            container,hardware=open_preview(path,identity in self.hardware_failed)
            self.containers[identity]=container
            if hardware: self.hardware.add(identity)
        self.containers.move_to_end(identity)
        c = self.containers[identity]
        v = c.streams.video[0]
        fps = Fraction(media.get('direct_fps',media['fps']))
        origin=Fraction(media.get('direct_start','0'))
        previous=self.positions.get(identity,-1000)
        resume=identity in self.pending and previous<=index<=max(previous,self.targets.get(identity,previous))+32
        if identity not in self.decoders or not (resume or previous<index<=previous+32):
            ts = int((Fraction(index,1)/fps+origin)/v.time_base)
            c.seek(ts,stream=v,backward=True)
            self.decoders[identity]=c.decode(video=0)
            self.pending.pop(identity,None); self.positions.pop(identity,None); self.targets[identity]=index
        arr = None
        retained=min(48,self.cache.budget//4//max(1,media.get('width',3840)*media.get('height',2160)*3)) if self.retain_decoded else 0
        while True:
            frame=self.pending.pop(identity,None)
            if frame is None:
                try: frame=next(self.decoders[identity])
                except StopIteration: break
            if frame.pts is None: continue
            if identity in self.hardware:
                planar={'nv12':'yuv420p','p010le':'yuv420p10le'}.get(frame.format.name)
                if planar:
                    if identity not in self.hardware_reformatters: self.hardware_reformatters[identity]=av.video.reformatter.VideoReformatter()
                    frame=self.hardware_reformatters[identity].reformat(frame,format=planar)
            current = round((Fraction(frame.pts)*frame.time_base-origin)*fps)
            self.positions[identity]=current
            if superseded is not None and superseded():
                self.pending[identity]=frame
                raise DecodeSuperseded()
            if self.retain_decoded and index-retained<=current<=index:
                self.cache.put_decoded((identity,current),frame)
            if current >= index:
                if current != index: raise RuntimeError(f'Image {index} non trouvée dans l’aperçu ({current}).')
                arr = self.pixels(frame,media)
                break
        if arr is None: raise RuntimeError(f'Image {index} indisponible.')
        self.cache.put(key,arr)
        return arr
    def close(self):
        for c in self.containers.values(): c.close()
        self.containers.clear(); self.decoders.clear(); self.positions.clear(); self.pending.clear(); self.targets.clear()
        self.hardware.clear(); self.hardware_failed.clear(); self.hardware_reformatters.clear()
        if self.owns_cache: self.cache.clear()


def export_video(state, media, fps, output, apply_exposure=True, progress=None, cancel=None, onion=None):
    progress = progress or (lambda p,m:None)
    if not state.length: raise ValueError('La timeline est vide.')
    output = Path(output).resolve()
    extension = output.suffix.lower()
    if extension not in ('.mp4','.mov','.gif','.wav','.mp3'):
        raise ValueError('Choisissez une extension .mp4, .mov, .gif, .wav ou .mp3.')
    try:
        with tempfile.TemporaryFile(dir=output.parent,prefix='.cadence-write-'): pass
    except PermissionError as error:
        raise ValueError('Ce dossier est protégé. Choisissez un autre dossier pour l’export.\n'+str(output.parent)) from error
    audio_only = extension in ('.wav','.mp3')
    sources = list(dict.fromkeys(s.media for s in state.segments if s.media is not None and not s.muted))
    for key in dict.fromkeys(s.media for s in state.segments+state.audio if s.media is not None):
        source = Path(media[key]['path']).resolve()
        if source == output or (output.exists() and source.exists() and source.samefile(output)):
            raise ValueError('Choisissez un fichier différent du média source.')
    required = state.audio if audio_only else state.segments+state.audio
    for key in dict.fromkeys(s.media for s in required if s.media is not None and not s.muted):
        validate_media(media[key])
    for key in dict.fromkeys(s.media for s in state.audio if s.media is not None and not s.muted):
        if media[key].get('audio_pending'):
            from audio_prepare import prepare_audio
            media[key]=prepare_audio(media[key],lambda p,m:progress(0,m),cancel)
    if output.suffix.lower()=='.gif':
        with tempfile.TemporaryDirectory(prefix='cadence-gif-') as tmp:
            intermediate=Path(tmp)/'montage.mp4'
            export_video(state,media,fps,intermediate,apply_exposure,lambda p,m:progress(p*.8,m),cancel,onion)
            partial=output.with_name(output.stem+'.'+uuid.uuid4().hex[:8]+'.partial.gif')
            try:
                run_ffmpeg(['-i',str(intermediate),'-filter_complex','split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer','-an','-loop','0',str(partial)],lambda p,m:progress(.8+.2*p,'Encodage GIF'),cancel,float(state.length/fps))
                partial.replace(output)
            finally:
                if partial.exists(): partial.unlink()
        return str(output)
    partial = output.with_name(output.stem+'.'+uuid.uuid4().hex[:8]+'.partial'+output.suffix)
    with tempfile.TemporaryDirectory(prefix='cadence-export-') as tmp:
        pcm_path = Path(tmp)/'timeline.s16'
        pcm = TimelinePCM(state.audio,media,fps)
        try:
            with pcm_path.open('wb') as out:
                for start in range(0,pcm.samples,RATE):
                    if cancel and cancel.is_set(): raise Cancelled()
                    out.write(pcm.read(start,min(RATE,pcm.samples-start)))
                    progress(.1*start/max(1,pcm.samples),'Assemblage de l’audio')
        finally: pcm.close()
        if audio_only:
            codec = ['-c:a','pcm_s16le','-rf64','auto'] if extension=='.wav' else ['-c:a','libmp3lame','-b:a','192k']
            args = ['-f','s16le','-ar',str(RATE),'-ac','2','-i',str(pcm_path),'-vn',*codec,str(partial)]
            try:
                run_ffmpeg(args,lambda p,m:progress(.1+.9*p,'Encodage audio'),cancel,float(state.length/fps))
                if cancel and cancel.is_set(): raise Cancelled()
                partial.replace(output)
            finally:
                if partial.exists(): partial.unlink()
            progress(1,'Export terminé')
            return str(output)
        first = media[sources[0]] if sources else next(iter(media.values()),{'width':1280,'height':720})
        width,height = first['width']//2*2,first['height']//2*2
        args,filters = [],[]
        for key in sources: args += ['-i',media[key]['path']]
        args += ['-f','s16le','-ar',str(RATE),'-ac','2','-i',str(pcm_path)]
        for idx,key in enumerate(sources):
            occurrences = [j for j,s in enumerate(state.segments) if s.media == key and not s.muted]
            labels = ''.join(f'[src{j}]' for j in occurrences)
            from cadence_change import video_filter
            base = f'[{idx}:v:0]'+video_filter(fps,media[key].get('cadence'))+f',scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1'
            if len(occurrences)>1: base += f',split={len(occurrences)}'
            filters.append(base+labels)
        for i,seg in enumerate(state.segments):
            if seg.media is None or seg.muted:
                filters.append(f'color=c=black:s={width}x{height}:r={fps},trim=end_frame={seg.length},setpts=PTS-STARTPTS[v{i}]')
                continue
            from clip_geometry import geometry_filter,IDENTITY
            geometry=','+geometry_filter(seg,width,height) if seg.crop!=IDENTITY or seg.placement!=IDENTITY or seg.rotation else ''
            filters.append(f'[src{i}]trim=start_frame={seg.start}:end_frame={seg.end},setpts=PTS-STARTPTS'+geometry+f'[v{i}]')
        inputs = ''.join(f'[v{i}]' for i in range(len(state.segments)))
        filters.append(inputs+f'concat=n={len(state.segments)}:v=1:a=0[joined]')
        effect = exposure_filter(state.exposure)+',' if apply_exposure and state.exposure else ''
        if state.flip_h: effect+='hflip,'
        if state.flip_v: effect+='vflip,'
        filters.append('[joined]'+effect+'format=rgba[drawbase]')
        drawbase='drawbase'
        if state.drawings and onion and (onion[0] or onion[1]):
            from drawing import render_layer
            from drawing_cache import DrawingRasterCache
            drawing_cache=DrawingRasterCache()
            for frame in range(state.length):
                if cancel and cancel.is_set(): raise Cancelled()
                image=render_layer(state.drawings,frame,width,height,*onion,cache=drawing_cache)
                if state.flip_h or state.flip_v: image=image.mirrored(state.flip_h,state.flip_v)
                if not image.save(str(Path(tmp)/f'onion-{frame:08d}.png')): raise ValueError('Impossible de préparer les dessins.')
                progress(.1+.15*frame/state.length,'Préparation des pelures')
            index=len(sources)+1
            args += ['-framerate',str(fps),'-i',str(Path(tmp)/'onion-%08d.png')]
            filters.append(f'[{drawbase}][{index}:v]overlay=shortest=1[onionbase]')
            drawbase='onionbase'
        elif state.drawings:
            from drawing import render_marks
            from PySide6.QtCore import Qt
            for key in state.drawings:
                if not key.marks or key.start>=state.length: continue
                if cancel and cancel.is_set(): raise Cancelled()
                image=render_marks(key.marks,width,height)
                flips=Qt.Orientation(0)
                if state.flip_h: flips|=Qt.Orientation.Horizontal
                if state.flip_v: flips|=Qt.Orientation.Vertical
                if flips: image=image.flipped(flips)
                image_path=Path(tmp)/f'drawing-{key.start}.png'
                if not image.save(str(image_path)): raise ValueError('Impossible de préparer les dessins.')
                input_index=len(sources)+1+sum(1 for f in filters if 'overlay=' in f)
                args += ['-loop','1','-framerate',str(fps),'-i',str(image_path)]
                outlabel=f'draw{key.start}'
                filters.append(f"[{drawbase}][{input_index}:v]overlay=shortest=1:enable='gte(n,{key.start})*lt(n,{key.end})'[{outlabel}]")
                drawbase=outlabel
        filters.append(f'[{drawbase}]format=yuv420p[out]')
        script = Path(tmp)/'filters.txt'
        script.write_text(';\n'.join(filters),encoding='utf-8')
        args += ['-/filter_complex',str(script),'-map','[out]','-map',f'{len(sources)}:a:0','-c:v','libx264','-preset','fast','-crf','18','-r',str(fps),'-c:a','aac','-b:a','192k','-movflags','+faststart',str(partial)]
        try:
            run_ffmpeg(args,lambda p,m:progress(.1+.9*p,'Encodage vidéo et audio'),cancel,float(Fraction(state.length,1)/fps))
            if cancel and cancel.is_set(): raise Cancelled()
            partial.replace(output)
        finally:
            if partial.exists(): partial.unlink()
    progress(1,'Export terminé')
    return str(output)


def prepare_batch(paths,fps=None,progress=None,cancel=None,quality='native',defer_audio=False):
    """Bounded parallel import, ordered results and monotone progress."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cancel=cancel or threading.Event(); progress=progress or (lambda p,m:None)
    if not paths: return []
    rate=Fraction(fps or probe(paths[0])['fps']); fractions=[0.0]*len(paths); lock=threading.Lock(); last=[0.0]
    def report(index,value,message):
        with lock:
            fractions[index]=max(fractions[index],value); now=time.monotonic()
            if now-last[0]>.12 or all(v>=1 for v in fractions):
                last[0]=now; progress(sum(fractions)/len(paths),f'{sum(v>=1 for v in fractions)}/{len(paths)} médias · {message}')
    # Deduplicate paths to avoid simultaneous writers into one media cache.
    unique=list(dict.fromkeys(str(Path(p).resolve()) for p in paths)); results={}
    def work(path):
        indices=[i for i,p in enumerate(paths) if str(Path(p).resolve())==path]
        def update(value,message):
            for i in indices: report(i,value,message)
        if cancel.is_set(): raise Cancelled()
        return prepare_media(path,rate,update,cancel,quality=quality,defer_audio=defer_audio)
    with ThreadPoolExecutor(max_workers=min(2,len(unique))) as pool:
        futures={pool.submit(work,p):p for p in unique}
        try:
            for f in as_completed(futures): results[futures[f]]=f.result()
        except Exception:
            cancel.set()
            raise
    return [results[str(Path(p).resolve())] for p in paths]
