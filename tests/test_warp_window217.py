# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest

from model import Segment
from time_warp import mapping
from time_warp_ui import merge_visible_curve, visible_curve


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('bounds',[(4,8),(1,7),(3,10),(0,3),(10,12)])
def test_warp_window_preserves_hidden_source_and_methods(bounds, reverse):
    original=((3,10,'blend'),(6,5,'rife'),(9,1,'motion'))
    clip=Segment('cube',*bounds,reversed=reverse,warp=original)
    view=visible_curve(clip)
    assert view[0][0]==0 and view[-1][0]==clip.length-1
    for pos in range(clip.length):
        b,f,_=mapping(view,pos)
        want,sub,_=mapping(original,clip.source_frame(pos))
        assert b+f==pytest.approx(want+sub)
    altered=list(view)
    for i in (0,-1):
        x,y,m=altered[i]
        altered[i]=(x,8.5,m)
    saved=merge_visible_curve(clip,tuple(altered))
    restored=replace(clip,start=0,end=12,warp=saved)
    for frame in range(12):
        i=restored.source_frame(frame)
        if clip.start<=i<clip.end: continue
        a,b,method=mapping(saved,i)
        oa,ob,old_method=mapping(original,i)
        assert a+b==pytest.approx(oa+ob)
        if b: assert method==old_method
