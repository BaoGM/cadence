# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import dataclass,replace
import numpy as np
from PySide6.QtCore import QRectF,QSize,Qt
from PySide6.QtGui import QImage,QPainter


def canvas_size(state,media):
    keys=list(dict.fromkeys(s.media for track in state.tracks for s in track.segments if s.media in media))
    if state.second_track is not None: keys=[key for key in media if key in keys]
    first=next((media[key] for key in keys if media[key].get('has_video',True)),None)
    return (first['width'],first['height']) if first else (1280,720)


def frame_layers(state,media,frame,identities=None):
    result=[]
    for track in state.tracks:
        if identities is not None and track.info.id not in identities: continue
        at=0
        for segment in track.segments:
            if at<=frame<at+segment.length:
                if segment.media is not None and not segment.muted:
                    result.append((track,segment,media[segment.media],segment.start+frame-at))
                break
            at+=segment.length
    return result


@dataclass
class LayerFrame:
    layers: tuple
    size: tuple

    def compose(self,geometry_identity=None,geometry=None,show_source=False,exposures=None):
        from clip_geometry import rect_pixels,IDENTITY
        from media import exposure_lut
        width,height=self.size
        target=QImage(width,height,QImage.Format.Format_RGB888); target.fill(Qt.GlobalColor.black)
        painter=QPainter(target); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            for track,segment,rgb in reversed(self.layers):
                if geometry is not None and track.info.id in (geometry_identity if isinstance(geometry_identity,tuple) else (geometry_identity,)):
                    segment=replace(segment,crop=IDENTITY,placement=IDENTITY,rotation=0) if show_source else geometry
                exposure=exposures.get(track.info.id,track.exposure) if exposures else track.exposure
                rgb=exposure_lut(exposure)[rgb] if exposure else rgb
                rgb=np.ascontiguousarray(rgb)
                image=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888)
                base=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); base.fill(Qt.GlobalColor.transparent)
                fit=image.size().scaled(QSize(width,height),Qt.AspectRatioMode.KeepAspectRatio)
                p=QPainter(base); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawImage(QRectF((width-fit.width())/2,(height-fit.height())/2,fit.width(),fit.height()),image); p.end()
                x,y,cw,ch=rect_pixels(segment.crop,width,height)
                crop=base.copy(x,y,min(cw,width-x),min(ch,height-y))
                dx,dy,dw,dh=rect_pixels(segment.placement,width,height)
                fit=crop.size().scaled(QSize(dw,dh),Qt.AspectRatioMode.KeepAspectRatio)
                painter.save()
                painter.translate(width if track.flip_h else 0,height if track.flip_v else 0)
                painter.scale(-1 if track.flip_h else 1,-1 if track.flip_v else 1)
                painter.translate(dx+dw/2,dy+dh/2); painter.rotate(segment.rotation)
                painter.drawImage(QRectF(-fit.width()/2,-fit.height()/2,fit.width(),fit.height()),crop)
                painter.restore()
        finally: painter.end()
        return np.frombuffer(target.bits(),np.uint8).reshape(height,target.bytesPerLine())[:,:width*3].reshape(height,width,3).copy()


def decode_layers(reader,layers,size,cancel):
    decoded=tuple((track,segment,reader.read(media,index,cancel)) for track,segment,media,index in layers)
    # Keep the selected preview resolution; full-size source dimensions define only its aspect ratio.
    width=max((rgb.shape[1] for track,segment,rgb in decoded),default=640)
    width=min(size[0],width); height=max(2,round(width*size[1]/size[0]))
    return LayerFrame(decoded,(width,height))


class MixedPCM:
    def __init__(self,state,media,fps):
        from model import TimelinePCM,sample_at
        self.parts=[]; self.samples=sample_at(state.length,fps)
        try:
            for track in state.tracks: self.parts.append(TimelinePCM(track.audible,media,fps))
        except BaseException:
            self.close(); raise

    def read(self,start,count):
        count=max(0,min(count,self.samples-start))
        output=np.zeros((count,2),np.int32)
        for pcm in self.parts:
            chunk=np.frombuffer(pcm.read(start,count),dtype='<i2').reshape(-1,2)
            output[:len(chunk)]+=chunk
        return np.clip(output,-32768,32767).astype('<i2').tobytes()

    def close(self):
        for pcm in self.parts: pcm.close()
        self.parts.clear()
