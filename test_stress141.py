# SPDX-License-Identifier: GPL-3.0-only
import random
from pathlib import Path
from dataclasses import replace
import numpy as np
from drawing import Mark,DrawingKey,render_layer
from drawing_cache import DrawingRasterCache
from model import Segment
from timeline_index import SegmentIndex,visible_keys
from test_native140 import application


def test_segment_index_matches_linear_and_rebuilds_after_edit():
    rng=random.Random(81);segments=tuple(Segment('x',0,rng.randrange(1,90)) for _ in range(12000))
    index=SegmentIndex()
    for start,end in [(0,0),(-2,5),(30,100),(9000,9100),(600000,600100)]:
        expected=[];at=0
        for i,seg in enumerate(segments):
            if at+seg.length>=start and at<=end: expected.append((i,at,seg))
            at+=seg.length
        assert list(index.visible(segments,start,end))==expected
    changed=(Segment('y',0,500),)+segments
    assert next(index.visible(changed,490,500))==(0,0,changed[0])
    assert list(index.visible((),0,100))==[]


def test_visible_keys_keep_boundary_and_long_exposures():
    keys=(DrawingKey(0,50,()),DrawingKey(80,81,()),DrawingKey(90,1000,()))
    for start,end in [(0,1),(49,50),(50,79),(81,90),(200,300),(1001,2000)]:
        assert list(visible_keys(keys,start,end))==[k for k in keys if k.end>=start and k.start<=end]


def test_decoder_closes_old_sources_and_reopens_exact_frame(tmp_path):
    import shutil
    from media import PreviewReader
    source=Path(__file__).parent/'assets/Demonstration.mp4'
    reader=PreviewReader(budget=0,max_containers=3);medias=[];expected=None
    try:
        for i in range(20):
            path=tmp_path/f'{i}.mp4';shutil.copyfile(source,path)
            media=dict(proxy=str(path),fps='24',frames=192,proxy_width=240,proxy_height=135)
            medias.append(media);frame=reader.read(media,55)
            if expected is None: expected=frame.copy()
            assert len(reader.containers)<=3 and len(reader.decoders)<=3 and len(reader.positions)<=3
        assert np.array_equal(reader.read(medias[0],55),expected)
    finally: reader.close()
    assert not reader.containers and not reader.decoders and not reader.positions


def test_onion_cache_over_capacity_reuses_nearest_keys(application,monkeypatch):
    import drawing
    keys=tuple(DrawingKey(i,i+1,(Mark(tool='rectangle',points=((0,0,1),(1,1,1)),color=f'#{0x117711+i:06x}'),)) for i in range(15))
    cache=DrawingRasterCache(5*100*60*4);calls=[];original=drawing.render_marks
    def counted(marks,width,height,**kwargs): calls.append(id(marks));return original(marks,width,height,**kwargs)
    monkeypatch.setattr(drawing,'render_marks',counted)
    expected=render_layer(keys,7,100,60,7,7,.8)
    calls.clear();assert render_layer(keys,7,100,60,7,7,.8,cache)==expected
    calls.clear();assert render_layer(keys,7,100,60,7,7,.8,cache)==expected
    assert len(calls)==10 and cache.bytes<=cache.budget and cache.admitted is None
    for frame in (8,9,8,7,6):
        assert render_layer(keys,frame,100,60,7,7,.8,cache)==render_layer(keys,frame,100,60,7,7,.8)
        assert cache.bytes<=cache.budget
        nearest=sorted(keys,key=lambda key:abs(key.start-frame))[:5]
        assert {id(key.marks) for key in nearest}=={identity[0] for identity in cache.entries}
