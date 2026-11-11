# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import subprocess
import numpy as np
import pytest
from test_drawing import application,window
from clip_geometry import apply_geometry
from model import Segment
from media import ffmpeg,prepare_media,PreviewReader

@pytest.mark.parametrize('operation',['fit','crop','source'])
@pytest.mark.parametrize('layout',['padded','reversed'])
def test_geometry_accepts_strided_decoded_images(application,operation,layout):
    storage=np.zeros((90,652,3),np.uint8)
    rgb=storage[:,:638]; rgb[:,:319,0]=210; rgb[:,319:,2]=190
    if layout=='reversed': rgb=rgb[::-1,::-1]
    assert not rgb.flags.c_contiguous
    original=rgb.copy(); seg=Segment('a',0,1)
    if operation=='crop': seg=replace(seg,crop=(.5,0,.5,1),placement=(.1,.1,.8,.8))
    kwargs=dict(aspect=16/9,show_source=operation=='source')
    expected=apply_geometry(rgb.copy(),seg,**kwargs)
    actual=apply_geometry(rgb,seg,**kwargs)
    np.testing.assert_array_equal(actual,expected)
    np.testing.assert_array_equal(rgb,original)
    assert actual.flags.c_contiguous and actual.shape==(90,160,3)

def test_import_capture_with_unaligned_width_into_existing_viewer(window,application,tmp_path):
    source=tmp_path/'capture-638x350.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=red:s=638x350:r=12:d=0.25','-c:v','libx264',str(source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media=prepare_media(source); reader=PreviewReader()
    try:
        rgb=reader.read(media,0)
        assert rgb.shape==(350,638,3)
        viewer=window.viewer; viewer.geometry_segment=Segment(media['id'],0,media['frames']); viewer.geometry_aspect=16/9
        viewer.set_frame(rgb)
        assert viewer.image.width()==round(350*16/9) and viewer.image.height()==350
        center=viewer.image.pixelColor(viewer.image.width()//2,175)
        assert center.red()>230 and center.green()<15 and center.blue()<15
    finally: reader.close()

def test_shortcut_customizations_survive_separator_cleanup(window):
    from preferences import defaults,validate
    registry=window.action_registry; data=defaults(registry)
    for key,shortcut in [('Affichage/Flop - miroir horizontal','Ctrl+Alt+H'),('Affichage/Flip - miroir vertical','Ctrl+Alt+V')]:
        assert key in registry
        del data['shortcuts'][key]
        data['shortcuts'][key.replace(' - ',' \u2014 ')]=shortcut
    migrated=validate(data,registry)
    assert migrated['shortcuts']['Affichage/Flop - miroir horizontal']=='Ctrl+Alt+H'
    assert migrated['shortcuts']['Affichage/Flip - miroir vertical']=='Ctrl+Alt+V'
