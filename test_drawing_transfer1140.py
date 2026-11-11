# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import threading

import pytest
from PySide6.QtWidgets import QApplication

from drawing import DrawingKey, Mark, render_marks
from drawing_transfer import build_bundle, native_strokes
from integrations.cadence_drawings import load_bundle
from model import Document
from test_sync1120 import application,link,pump


@pytest.fixture
def keys():
    brush=Mark(points=((.1,.2,.5),(.8,.7,1.)),size=.03)
    text=Mark(tool='text',points=((.1,.2,1.),),text='Hello',size=.1)
    return (DrawingKey(10,13,(brush,)),DrawingKey(17,20,(text,)))


def bundle(tmp_path,keys,**options):
    return build_bundle(keys,tmp_path,'a'*32,320,180,Fraction(24),options.pop('host_fps',Fraction(24)),
        options.pop('origin',101),options.pop('offset',0),'Camera','native',**options)


def test_bundle_timing_ghost_first_frame_and_fidelity(application,tmp_path,keys):
    path=bundle(tmp_path,keys,before=3,after=3,opacity=.8)
    data,folder=load_bundle(path,tmp_path)
    assert (data['keys'][0]['start'],data['keys'][0]['end'])==(111,114)
    envelope=dict(data['keys'][0]['envelope'])
    assert envelope[110]==pytest.approx(.6) and envelope[114]==pytest.approx(.6)
    assert envelope[109]==pytest.approx(.4) and envelope[115]==pytest.approx(.4)
    assert envelope[107]==0 and envelope[117]==0
    assert data['keys'][0]['strokes'] and data['keys'][1]['strokes'] is None
    from PySide6.QtGui import QImage
    assert QImage(str(folder/data['keys'][1]['image'])).convertToFormat(QImage.Format_ARGB32_Premultiplied)==render_marks(keys[1].marks,320,180)


def test_mapping_offset_fractional_rate_collapsed_keys(application,tmp_path,keys):
    path=bundle(tmp_path,(DrawingKey(0,1,keys[0].marks),DrawingKey(1,2,keys[0].marks)),host_fps=Fraction(12),origin=1,offset=0)
    data,_=load_bundle(path,tmp_path)
    assert data['collapsed']==1
    assert data['keys'][0]['start']==1 and data['keys'][0]['end']==2


def test_fallback_transforms_and_vector_shapes(application,keys):
    assert native_strokes((replace(keys[0].marks[0],tool='eraser'),),320,180) is None
    assert native_strokes((replace(keys[0].marks[0],transform=(2.,0.,0.,1.,0.,0.)),),320,180) is None
    for tool in ('arrow','rectangle','ellipse'):
        paths=native_strokes((Mark(tool=tool,points=((.1,.1,1.),(.9,.9,1.))),),320,180)
        assert paths and all(len(path['points'])>=2 for path in paths)


def test_bundle_guards_and_cancel(application,tmp_path,keys):
    path=bundle(tmp_path,keys)
    data,folder=load_bundle(path,tmp_path)
    with pytest.raises(ValueError): load_bundle(path,tmp_path/'elsewhere')
    (folder/data['keys'][0]['image']).write_bytes(b'wrong')
    with pytest.raises(ValueError,match='checksum'): load_bundle(path,tmp_path)
    cancel=threading.Event(); cancel.set()
    before=set((tmp_path/('a'*32)).iterdir())
    from media import Cancelled
    with pytest.raises(Cancelled): bundle(tmp_path,keys,cancel=cancel)
    assert set((tmp_path/('a'*32)).iterdir())==before


def test_owner_survives_save_load_and_new_projects_differ():
    first=Document(); data=first.to_data()
    assert Document.from_data(data).drawing_transfer_id==first.drawing_transfer_id
    assert Document().drawing_transfer_id!=first.drawing_transfer_id
    del data['drawing_transfer_id']
    assert len(Document.from_data(data).drawing_transfer_id)==32


def test_blue_pencil_archive_exposures_and_ghost_pixels(application,tmp_path,keys):
    import zipfile
    import xml.etree.ElementTree as ET
    from PySide6.QtGui import QImage
    from drawing import render_layer
    path=build_bundle(keys,tmp_path,'b'*32,320,180,Fraction(24),Fraction(24),1,0,'persp','blue_pencil',3,3,.8)
    data,folder=load_bundle(path,tmp_path)
    with zipfile.ZipFile(folder/data['archive']) as archive:
        tree=ET.fromstring(archive.read('drawings/drawings.xml'))
        camera=tree.find('camera'); layer=camera.find('layer')
        assert camera.get('name')=='persp' and layer.get('name')==data['layer_name']
        frames={int(f.get('time')):f.get('file') for f in layer.findall('frame')}
        for frame in range(7,25):
            previous=max(f for f in frames if f<=frame)
            actual=QImage.fromData(archive.read('drawings/'+frames[previous])).convertToFormat(QImage.Format_ARGB32_Premultiplied)
            expected=render_layer(keys,frame-1,320,180,before=3,after=3,ghost_opacity=.8)
            assert actual==expected, frame
    archive=folder/data['archive']
    archive.write_bytes(archive.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='checksum'): load_bundle(path,tmp_path)


def test_transfer_protocol_success_failure_and_timeline_survives(application,link,tmp_path,keys):
    from types import SimpleNamespace
    from integrations.cadence_bridge import Bridge
    host=dict(frame=1.,start=1.,end=100.,fps=24.)
    bridge=Bridge('blender',lambda:dict(host),lambda frame:host.update(frame=frame))
    def execute(target,message,root):
        if message['type']=='drawing_cameras': return dict(type='drawing_cameras',cameras=['Camera'])
        data,_=load_bundle(message['path'],root)
        return dict(type='drawing_result',request=message['request'],ok=True,keys=len(data['keys']),native=1,images=1,collapsed=0)
    bridge.drawings=SimpleNamespace(execute=execute)
    def wait(predicate): pump(application,lambda:(bridge.tick(),predicate())[1])
    try:
        wait(lambda:link.metadata is not None and link.cameras==['Camera'] and link.last_position is not None)
        from integrations.cadence_bridge import endpoint_path
        path=bundle(endpoint_path().parent/'drawing_transfers',keys)
        link.drawing_request='test'; link.drawing_bundle=path
        assert link.send(dict(type='drawing_send',path=path,request='test'))
        wait(lambda:link.drawing_request is None)
        assert '2' in link.transfer_status and not Path(path).exists()
        link.window.seek(20); wait(lambda:host['frame']==21.)
        assert not link.window.errors
        link.drawing_request='bad'
        link.send(dict(type='drawing_send',path=str(tmp_path/'missing.json'),request='bad'))
        wait(lambda:link.drawing_request is None)
        assert link.window.errors and link.peer and link.metadata
    finally: bridge.close()
