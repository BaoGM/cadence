# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid
import zipfile
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from affine import pixel
from drawing import render_marks, vector_path, pressure_size
from cadence_change import rounded


def native_strokes(marks, width, height):
    strokes = []
    for mark in marks:
        # Erasing and group opacity are compositing operations, not independent strokes.
        if mark.tool in ('text', 'eraser', 'group'):
            return None
        matrix = pixel(mark.transform, width, height)
        sx = math.hypot(matrix.m11(), matrix.m12())
        sy = math.hypot(matrix.m21(), matrix.m22())
        if abs(sx-sy) > 1e-5 or abs(matrix.m11()*matrix.m21()+matrix.m12()*matrix.m22()) > 1e-5:
            return None
        color = QColor(mark.color)
        rgba = [color.redF(), color.greenF(), color.blueF(), mark.opacity]
        if mark.tool == 'brush':
            paths = [(mark.points, False)]
        else:
            paths = []
            for polygon in vector_path(mark, width, height).toSubpathPolygons():
                points = [(p.x()/width, p.y()/height, 1.) for p in polygon]
                closed = len(points)>2 and points[0] == points[-1]
                paths.append((points[:-1] if closed else points, closed))
        for points, closed in paths:
            output = []
            for x, y, pressure in points:
                point = matrix.map(QPointF(x*width, y*height))
                radius = max(.35, mark.size*height*pressure_size(mark, pressure)/2)*sx/height
                output.append([point.x()/width, point.y()/height, radius])
            if output:
                strokes.append(dict(points=output, color=rgba, cyclic=closed))
    return strokes


def build_bundle(keys, root, owner, width, height, timeline_fps, host_fps, origin, offset,
                 camera, mode, before=0, after=0, opacity=1., progress=None, cancel=None):
    revision = uuid.uuid4().hex
    if not re.fullmatch('[0-9a-f]{32}',owner): raise ValueError('Invalid drawing identifier')
    folder = Path(root).resolve()/owner/revision
    folder.mkdir(parents=True, exist_ok=False)
    ratio = Fraction(host_fps)/Fraction(timeline_fps)
    mapping = lambda frame: Fraction(str(origin))+(Fraction(frame)-Fraction(1,2)-offset)*ratio
    result = dict(version=1, owner=owner, revision=revision, camera=camera, mode=mode,
                  width=width, height=height, keys=[], before=before, after=after,
                  ghost_opacity=opacity, collapsed=0)
    try:
        if len(keys)>10000:
            raise ValueError('Trop de clés pour un seul transfert (10 000 maximum).')
        for index, key in enumerate(keys):
            if cancel and cancel.is_set():
                from media import Cancelled
                raise Cancelled()
            start, end = math.ceil(mapping(key.start)), math.ceil(mapping(key.end))
            if not -1000000 <= start <= end <= 1000000:
                raise ValueError('Les dessins dépassent la plage prise en charge par le logiciel 3D.')
            if start == end:
                result['collapsed'] += 1
                continue
            if not key.marks:
                continue
            name = f'{index:06d}.png'
            if not render_marks(key.marks, width, height).save(str(folder/name), 'PNG'):
                raise OSError('Impossible de créer les images de dessin.')
            native = native_strokes(key.marks, width, height) if mode == 'native' else None
            # Sample the Cadence opacity on each destination frame, including the first neighbour.
            envelope = {start: 1., end-1: 1., end: 0., start-1: 0.}
            for radius, base, direction in ((after,key.start,-1),(before,key.end-1,1)):
                if radius <= 0:
                    continue
                lo, hi = sorted((mapping(base),mapping(base+direction*(radius+1))))
                for frame in range(math.floor(lo)-1, math.ceil(hi)+2):
                    source = rounded((Fraction(frame)-Fraction(str(origin)))/ratio)+offset
                    distance = source-base if direction>0 else base-source
                    if distance >= 1-1e-7:
                        envelope[frame] = max(0., opacity*(radius-distance+1)/(radius+1))
            result['keys'].append(dict(start=start,end=end,image=name,
                sha256=hashlib.sha256((folder/name).read_bytes()).hexdigest(),
                strokes=native, envelope=sorted(envelope.items())))
            if progress: progress((index+1)/max(1,len(keys)), 'Préparation des dessins')
        if mode=='blue_pencil':
            build_blue_archive(result,folder,cancel)
        elif mode=='images':
            build_image_sequence(result,folder,cancel)
        path = folder/'manifest.json'
        path.write_text(json.dumps(result,separators=(',',':'),allow_nan=False),encoding='utf-8')
        if path.stat().st_size>64*1024*1024:
            raise ValueError('Le transfert dépasse 64 Mo de géométrie. Choisissez le mode images.')
        return str(path)
    except BaseException:
        shutil.rmtree(folder)
        raise


def composite_frames(data,folder,cancel=None):
    from collections import OrderedDict
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    keys=data['keys']; events={}
    for index,key in enumerate(keys):
        for frame,alpha in key['envelope']:
            events.setdefault(frame,{})[index]=alpha
    if len(events)>25000:
        raise ValueError('Le transfert dépasse 25 000 images. Réduisez la portée des pelures.')
    active={}; cache=OrderedDict(); used=0; previous=None
    for frame,changes in sorted(events.items()):
        if cancel and cancel.is_set():
            from media import Cancelled
            raise Cancelled()
        for index,alpha in changes.items():
            if alpha>0: active[index]=alpha
            else: active.pop(index,None)
        def order(index):
            key=keys[index]
            return -max(key['start']-frame,frame-key['end']+1,0)
        composition=tuple((index,active[index]) for index in sorted(active,key=order))
        if composition==previous: continue
        previous=composition
        image=QImage(data['width'],data['height'],QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent)
        painter=QPainter(image)
        try:
            for index,alpha in composition:
                ink=cache.pop(index,None)
                if ink is None:
                    ink=QImage(str(folder/keys[index]['image'])); used+=ink.sizeInBytes()
                cache[index]=ink
                painter.setOpacity(alpha); painter.drawImage(0,0,ink)
            while used>128*1024*1024 and cache:
                _,ink=cache.popitem(last=False); used-=ink.sizeInBytes()
        finally: painter.end()
        yield frame,image


def build_image_sequence(data,folder,cancel=None):
    data['sequence']=[]
    total=0
    for index,(frame,image) in enumerate(composite_frames(data,folder,cancel)):
        name=f'composite.{index:06d}.png'
        if not image.save(str(folder/name),'PNG'): raise OSError('Impossible de créer les images de dessin.')
        payload=(folder/name).read_bytes(); total+=len(payload)
        if total>2*1024**3: raise ValueError('Le transfert dépasse 2 Go. Réduisez la portée des pelures.')
        data['sequence'].append(dict(frame=frame,image=name,sha256=hashlib.sha256(payload).hexdigest()))


def build_blue_archive(data,folder,cancel=None):
    from PySide6.QtCore import QIODevice,QBuffer,QByteArray
    tree=ET.Element('bluePencil'); camera=ET.SubElement(tree,'camera',name=data['camera'])
    layer_name='Cadence_'+data['owner']+'_'+data['revision'][:8]
    layer=ET.SubElement(camera,'layer',name=layer_name,isStatic='false',isActive='true',isLocked='false',isVisible='true')
    archive=folder/'blue-pencil.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as target:
        for frame,image in composite_frames(data,folder,cancel):
            payload=QByteArray(); buffer=QBuffer(payload); buffer.open(QIODevice.WriteOnly)
            if not image.save(buffer,'PNG'): raise OSError('Impossible de créer les images de dessin.')
            name=f'frame_{frame:+08d}.png'
            target.writestr('drawings/'+name,bytes(payload))
            if target.fp.tell()>2*1024**3:
                raise ValueError('Le transfert dépasse 2 Go. Réduisez la portée des pelures.')
            ET.SubElement(layer,'frame',time=str(frame),file=name)
        target.writestr('drawings/drawings.xml',ET.tostring(tree,encoding='utf-8',xml_declaration=True))
    data['archive']='blue-pencil.zip'; data['layer_name']=layer_name
    with archive.open('rb') as stream:
        data['archive_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
