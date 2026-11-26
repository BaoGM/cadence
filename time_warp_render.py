# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
import math
from pathlib import Path
import os
import subprocess
import tempfile

import numpy as np

from time_warp import mapping, render_path


def tool_path(method):
    from PySide6.QtCore import QSettings
    names = {'rife':'rife-ncnn-vulkan.exe', 'nvidia':'NVEncC64.exe'}
    name = names[method]
    saved = QSettings('CadenceStudio', 'Interpolation').value(method, '')
    for value in (saved, os.environ.get('CADENCE_'+method.upper()),
                  Path(__file__).parent/'vendor'/'interpolation'/method/name):
        if not value:
            continue
        exe = Path(value)
        if exe.is_absolute() and exe.name.lower() == name.lower() and exe.is_file():
            if method == 'rife' and not (exe.parent/'rife-v4.6'/'flownet.bin').is_file():
                continue
            return exe
    return None


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        from media import Cancelled
        raise Cancelled()


def run_tool(exe, args, cancel):
    if exe is None:
        raise ValueError('Configurez le moteur d’interpolation dans Time Warp.')
    with tempfile.TemporaryFile() as log:
        with subprocess.Popen([str(exe),*map(str,args)], cwd=exe.parent, stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
            try:
                while proc.poll() is None:
                    check_cancel(cancel)
                    try: proc.wait(.12)
                    except subprocess.TimeoutExpired: pass
                check_cancel(cancel)
            finally:
                if proc.poll() is None: proc.kill()
                proc.wait()
        if proc.returncode:
            log.seek(max(0,log.seek(0,os.SEEK_END)-1800))
            raise RuntimeError(exe.name+' — '+log.read().decode('utf-8',errors='replace').strip())


def ffv1(path, frames, fps, width, height, alpha=False):
    import av
    with av.open(str(path),'w',format='nut') as movie:
        stream = movie.add_stream('ffv1',rate=fps)
        stream.width,stream.height,stream.pix_fmt = width,height,'bgra' if alpha else 'bgr0'
        stream.codec_context.gop_size=1
        for index,rgb in enumerate(frames):
            frame=av.VideoFrame.from_ndarray(rgb,format='rgba' if alpha else 'rgb24')
            frame.pts=index
            frame.time_base=1/fps
            for packet in stream.encode(frame): movie.mux(packet)
        for packet in stream.encode(): movie.mux(packet)


def rgb_info(path, fps, frames, width, height):
    return dict(proxy=str(path),fps=str(fps),frames=frames,proxy_width=width,proxy_height=height)


class Samples:
    # One block on disk bounds interpolator storage even for a long clip.
    def __init__(self, root, source, reader, cancel):
        self.root,self.source,self.reader,self.cancel=root,source,reader,cancel
        self.block=None
        self.staging=None

    def close(self):
        if self.staging:
            self.staging.cleanup()
            self.staging=None

    def sample(self, index, fraction, method):
        rgb=self.reader.read(self.source,index)
        if method=='held' or not fraction: return rgb
        next_rgb=self.reader.read(self.source,index+1)
        if method=='blend':
            return np.rint(rgb.astype(np.float32)*(1-fraction)+next_rgb*fraction).astype(np.uint8)
        quarter=int(fraction*4+.5)
        if quarter in (0,4): return rgb if quarter==0 else next_rgb
        # Never synthesize a transition across a pronounced scene cut.
        delta=np.abs(rgb[::8,::8].astype(np.int16)-next_rgb[::8,::8])
        if delta.mean()>55 and (delta.max(axis=2)>48).mean()>.75: return rgb
        first=index//24*24
        if self.block!=(method,first):
            self.make_block(method,first)
        number=(index-first)*4+quarter
        if method=='rife':
            import av
            with av.open(str(self.bank/f'{number+1:08d}.png')) as image:
                return next(image.decode(video=0)).to_ndarray(format='rgb24')
        return self.bank_reader.read(self.bank,number)

    def make_block(self,method,first):
        from media import PreviewReader, run_ffmpeg
        self.release_block()
        self.staging=tempfile.TemporaryDirectory(dir=self.root)
        directory=Path(self.staging.name)
        stop=min(first+25,self.source['frames'])
        count=stop-first
        fps=Fraction(self.source['fps'])
        w,h=self.source['proxy_width'],self.source['proxy_height']
        group=directory/'block.nut'
        def frames():
            for at in range(first,stop):
                check_cancel(self.cancel)
                yield self.reader.read(self.source,at)
        ffv1(group,frames(),fps,w,h)
        if method=='rife':
            exe=tool_path(method)
            inputs=directory/'in'; inputs.mkdir()
            self.bank=directory/'out'; self.bank.mkdir()
            run_ffmpeg(['-i',str(group),'-threads','1',str(inputs/'%08d.png')],cancel=self.cancel)
            args=['-i',inputs,'-o',self.bank,'-n',str(count*4),'-m','rife-v4.6','-f','%08d.png']
            run_tool(exe,args,self.cancel)
        else:
            output=directory/'bank.nut'
            if method=='motion':
                # Replicated end poses supply the lookahead required by minterpolate.
                padded=(max(64,w+w%2),max(64,h+h%2))
                filters=(f'pad={padded[0]}:{padded[1]},tpad=start=1:start_mode=clone:stop=3:stop_mode=clone,'
                         f'minterpolate=fps={fps*4}:mi_mode=mci,trim=start_frame=4,setpts=PTS-STARTPTS,'
                         f'format=bgr0,crop={w}:{h}:0:0')
                run_ffmpeg(['-i',str(group),'-vf',filters,'-c:v','ffv1','-g','1',str(output)],cancel=self.cancel)
            else:
                exe=tool_path(method)
                encoded=directory/'gpu.mp4'
                gpu_input=directory/'input.mkv'
                # Pad to an encoder-compatible YUV surface, then restore the exact image area.
                padded=(max(160,w+w%2),max(128,h+h%2))
                run_ffmpeg(['-i',str(group),'-vf',f'pad={padded[0]}:{padded[1]}','-pix_fmt','yuv420p',
                            '-c:v','libx264','-qp','0','-preset','ultrafast',str(gpu_input)],cancel=self.cancel)
                run_tool(exe,['--avsw','-i',gpu_input,'--codec','h264','--cqp','10',
                              '--vpp-fruc',f'fps={fps.numerator*4}/{fps.denominator}',
                              '-o',encoded],self.cancel)
                if padded!=(w,h):
                    run_ffmpeg(['-i',str(encoded),'-vf',f'format=bgr0,crop={w}:{h}:0:0','-c:v','ffv1','-g','1',str(output)],cancel=self.cancel)
                else: output=encoded
            self.bank=rgb_info(output,fps*4,(count-1)*4+1,w,h)
            self.bank_reader=PreviewReader()
        self.block=method,first

    def release_block(self):
        if getattr(self,'bank_reader',None) is not None:
            self.bank_reader.close()
            self.bank_reader=None
        self.close()
        self.block=None


class ChannelReader:
    def __init__(self,reader,matte):
        self.reader,self.matte=reader,matte

    def read(self,source,index):
        rgba=self.reader.read(source,index)
        alpha=rgba[:,:,3:4]
        if self.matte: return np.repeat(alpha,3,axis=2)
        return ((rgba[:,:,:3].astype(np.uint16)*alpha+127)//255).astype(np.uint8)


class AlphaSamples:
    def __init__(self,folder,source,reader,cancel):
        self.reader,self.source=reader,source
        self.colour=Samples(folder,source,ChannelReader(reader,False),cancel)
        self.matte=Samples(folder,source,ChannelReader(reader,True),cancel)

    def sample(self,index,fraction,method):
        if not fraction or method=='held': return self.reader.read(self.source,index)
        premultiplied=self.colour.sample(index,fraction,method)
        alpha=self.matte.sample(index,fraction,method)[:,:,0:1]
        rgb=np.minimum(255,np.rint(premultiplied.astype(np.float32)*255/np.maximum(1,alpha)))
        return np.concatenate((rgb.astype(np.uint8),alpha),axis=2)

    def release_block(self):
        self.colour.release_block()
        self.matte.release_block()


def ensure_render(info, curve, progress, cancel):
    from media import PreviewReader, run_ffmpeg
    from cadence_change import video_filter
    import av
    path=render_path(info,curve)
    check_cancel(cancel)
    if path.is_file(): return path
    path.parent.mkdir(parents=True,exist_ok=True)
    fps=Fraction(info['fps'])
    low=math.floor(min(p[1] for p in curve))
    high=math.ceil(max(p[1] for p in curve))
    alpha=info.get('has_alpha',False)
    start,end=curve[0][0],curve[-1][0]
    if max(end,high)>=info['frames']: raise ValueError('Courbe temporelle invalide.')
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        folder=Path(temporary)
        normal=folder/'source.nut'
        filters=video_filter(fps,info.get('cadence'))+f',trim=start_frame={low}:end_frame={high+1},setpts=PTS-STARTPTS'
        run_ffmpeg(['-i',info['path'],'-map','0:v:0','-an','-vf',filters,'-c:v','ffv1','-g','1','-pix_fmt','bgra' if alpha else 'bgr0',str(normal)],
                   lambda p,m:progress(p*.25,'Préparation du Time Warp'),cancel,float((high-low+1)/fps))
        with av.open(str(normal)) as movie:
            stream=movie.streams.video[0]
            width,height=stream.width,stream.height
        reader=PreviewReader()
        source=dict(rgb_info(normal,fps,high-low+1,width,height),read_alpha=alpha)
        samples=(AlphaSamples if alpha else Samples)(folder,source,reader,cancel)
        def mapped_frames():
            for frame in range(start,end+1):
                check_cancel(cancel)
                previous,frac,method=mapping(curve,frame)
                progress(.25+.75*(frame-start)/(end-start+1),'Calcul du Time Warp')
                yield samples.sample(previous-low,frac,method)
        result=folder/'result.nut'
        try: ffv1(result,mapped_frames(),fps,width,height,alpha)
        finally:
            samples.release_block()
            reader.close()
        check_cancel(cancel)
        if not path.is_file():
            try: result.replace(path)
            except PermissionError:
                if not path.is_file(): raise
    return path
