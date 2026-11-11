# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


def module(host):
    if host not in ('blender','maya'): raise ValueError('Unsupported host')
    path = Path(__file__).with_name('cadence_drawings_'+host+'.py')
    spec = importlib.util.spec_from_file_location('cadence_drawings_'+host, path)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    return target


def load_bundle(path, root):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(Path(root).resolve()) or path.name!='manifest.json':
        raise ValueError('Drawing transfer path outside the allowed folder')
    if path.stat().st_size>64*1024*1024: raise ValueError('Drawing transfer too large')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1 or data.get('mode') not in ('native','images','blue_pencil'):
        raise ValueError('Unsupported drawing transfer')
    for name in ('owner','revision'):
        if not re.fullmatch('[0-9a-f]{32}',data.get(name,'')): raise ValueError('Invalid drawing identifier')
    if not isinstance(data.get('camera'),str) or len(data['camera'])>1024: raise ValueError('Invalid camera')
    for dimension in ('width','height'):
        if type(data.get(dimension)) is not int or not 2<=data[dimension]<=4096: raise ValueError('Invalid image size')
    keys=data.get('keys')
    if not isinstance(keys,list) or len(keys)>10000: raise ValueError('Invalid drawing keys')
    for key in keys:
        if any(type(key.get(n)) is not int for n in ('start','end')) or not -1000000<=key['start']<key['end']<=1000000:
            raise ValueError('Invalid drawing range')
        if not re.fullmatch(r'\d{6}\.png',key.get('image','')): raise ValueError('Invalid drawing image')
        image=(path.parent/key['image']).resolve(strict=True)
        if image.parent!=path.parent or image.stat().st_size>128*1024*1024: raise ValueError('Invalid image path or size')
        if hashlib.sha256(image.read_bytes()).hexdigest()!=key['sha256']: raise ValueError('Drawing image checksum mismatch')
        for frame,alpha in key['envelope']:
            if type(frame) is not int or not -1001000<=frame<=1001000 or not isinstance(alpha,(int,float)) or not math.isfinite(alpha) or not 0<=alpha<=1:
                raise ValueError('Invalid drawing opacity')
        for stroke in key.get('strokes') or []:
            if len(stroke['points'])>1000000 or len(stroke['color'])!=4: raise ValueError('Invalid stroke')
            for point in stroke['points']:
                if len(point)!=3 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1000 for v in point):
                    raise ValueError('Invalid stroke point')
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in stroke['color']):
                raise ValueError('Invalid stroke color')
    sequence=data.get('sequence',[])
    if not isinstance(sequence,list) or len(sequence)>25000: raise ValueError('Invalid drawing sequence')
    previous=-1001001
    total=0
    for item in sequence:
        frame=item.get('frame')
        if type(frame) is not int or not previous<frame<=1001000: raise ValueError('Invalid sequence frame')
        previous=frame
        if not re.fullmatch(r'composite\.\d{6}\.png',item.get('image','')): raise ValueError('Invalid sequence image')
        image=(path.parent/item['image']).resolve(strict=True)
        if image.parent!=path.parent or image.stat().st_size>128*1024**2: raise ValueError('Invalid sequence image path or size')
        total+=image.stat().st_size
        if total>2*1024**3: raise ValueError('Drawing sequence too large')
        with image.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=item.get('sha256'): raise ValueError('Drawing image checksum mismatch')
    if data['mode']=='blue_pencil':
        if data.get('archive')!='blue-pencil.zip' or not re.fullmatch(r'Cadence_[0-9a-f]{32}_[0-9a-f]{8}',data.get('layer_name','')):
            raise ValueError('Invalid Blue Pencil archive')
        archive=(path.parent/data['archive']).resolve(strict=True)
        if archive.parent!=path.parent or archive.stat().st_size>2*1024**3: raise ValueError('Invalid Blue Pencil archive size')
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=data['archive_sha256']: raise ValueError('Blue Pencil archive checksum mismatch')
        import zipfile
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist())>25001 or sum(i.file_size for i in z.infolist())>2*1024**3 or any(not re.fullmatch(r'drawings/(drawings.xml|frame_[+-]\d+\.png)',i.filename) for i in z.infolist()):
                raise ValueError('Invalid Blue Pencil archive entries')
    return data, path.parent


def execute(host, message, root):
    target=module(host)
    if message['type']=='drawing_cameras':
        return dict(type='drawing_cameras',cameras=target.cameras())
    if message['type']=='drawing_remove':
        if message.get('scope')!='all_cadence': raise ValueError('Invalid drawing removal scope')
        target.clear()
        return dict(type='drawing_result',request=message['request'],ok=True,removed=True)
    data,folder=load_bundle(message['path'],root)
    result=target.apply(data,folder)
    return dict(type='drawing_result',request=message['request'],ok=True,**result)
