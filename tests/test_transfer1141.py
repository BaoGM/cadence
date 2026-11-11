# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
import json

import pytest
from PySide6.QtGui import QImage

from drawing import DrawingKey, Mark, render_layer
from drawing_transfer import build_bundle
from integrations.cadence_drawings import load_bundle
from sync3d import to_cadence
from test_sync1120 import application


@pytest.mark.parametrize('rate',[Fraction(12),Fraction(30),Fraction(30000,1001)])
@pytest.mark.parametrize('before,after',[(0,0),(3,1),(1,4)])
def test_destination_frames_match_live_sync(application,tmp_path,rate,before,after):
    keys=(DrawingKey(10,13,(Mark(points=((.1,.2,1),(.8,.6,1)),color='#ff6433'),)),
          DrawingKey(16,20,(Mark(tool='ellipse',points=((.2,.2,1),(.8,.8,1)),color='#19ce58'),)))
    path=build_bundle(keys,tmp_path,'d'*32,160,90,Fraction(24),rate,1001,4,'persp','images',before,after,.8)
    data,folder=load_bundle(path,tmp_path)
    frames={item['frame']:QImage(str(folder/item['image'])).convertToFormat(QImage.Format_ARGB32_Premultiplied) for item in data['sequence']}
    for frame in range(1000,1040):
        source=to_cadence(frame,1001,rate,Fraction(24),4)
        expected=render_layer(keys,source,160,90,before,after,.8)
        previous=[f for f in frames if f<=frame]
        if previous: assert frames[max(previous)]==expected,(frame,source,rate)
        else: assert not any(bytes(expected.constBits())),(frame,source)
    item=data['sequence'][0]; (folder/item['image']).write_bytes(b'bad')
    with pytest.raises(ValueError,match='checksum'):load_bundle(path,tmp_path)


def test_disabled_cadence_onion_is_not_exported(application,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QCheckBox,QSpinBox
    import drawing_transfer
    from sync3d import TimelineLink
    from model import Document
    from fractions import Fraction
    from threading import Event
    captured={}
    def build(*args):captured['before'],captured['after']=args[11:13]; return 'unused'
    monkeypatch.setattr(drawing_transfer,'build_bundle',build)
    onion=QCheckBox(); onion.setChecked(False)
    before=QSpinBox();before.setValue(3)
    after=QSpinBox();after.setValue(4)
    ghost=QSpinBox();ghost.setValue(80)
    window=SimpleNamespace(doc=Document(),job=None,drawing=SimpleNamespace(finish=lambda:None,onion=onion,before=before,after=after,ghost=ghost),begin_task=lambda name,task,done:task(None,Event()))
    link=SimpleNamespace(window=window,metadata={'fps':Fraction(24)},drawing_capability=True,drawing_request=None,cameras=['persp'],host='maya',origin=lambda:1,offset=0,token='test',changed=SimpleNamespace(emit=lambda:None))
    TimelineLink.send_drawings(link,'persp','blue_pencil',True)
    assert captured=={'before':0,'after':0}


@pytest.mark.parametrize('size,blank', [((1,1),False),((19,27),False),((33,64),True)])
def test_exr_roundtrip_with_independent_decoder(tmp_path,size,blank):
    import av
    import numpy as np
    from integrations.cadence_drawings_maya import write_exr
    height,width=size
    pixels=np.zeros((height,width,4),dtype=np.float32) if blank else np.random.default_rng(1141).uniform(-.5,3,(height,width,4)).astype(np.float32)
    pixels[:,:,3]=np.clip(pixels[:,:,3],0,1)
    original=pixels.copy()
    path=tmp_path/'drawing.exr'
    write_exr(path,pixels)
    with av.open(str(path)) as container:
        decoded=next(container.decode(video=0))
        assert decoded.format.name=='gbrapf16le'
        for plane,channel in zip(decoded.planes,(1,2,0,3)):
            actual=np.frombuffer(plane,dtype='<f2').reshape(height,-1)[:,:width]
            np.testing.assert_array_equal(actual,pixels[:,:,channel].astype('<f2'))
    np.testing.assert_array_equal(pixels,original)
