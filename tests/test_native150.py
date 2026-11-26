# SPDX-License-Identifier: GPL-3.0-only
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import numpy as np
from model import TimelinePCM,Segment,RATE,sample_at
from test_native140 import rgb_pixels
import native_render


def test_parallel_native_strides_and_concurrent_callers():
    rng=np.random.default_rng(150)
    a=rng.integers(0,256,(1203,2406,3),dtype=np.uint8)[::-1,::2]
    b=rng.integers(0,256,(1203,2406,3),dtype=np.uint8)[::-1,::2]
    def run(index):
        mode=('overlay','difference','single')[index%3]
        table=native_render._table(.7,mode,.37,2.2,True)
        expected=table[a] if mode=='single' else table.reshape(-1)[(a.astype(np.uint16)<<8)|b]
        actual=native_render.rgb_image(a,b,mode=mode,ev=.7,opacity=.37,gain=2.2,swapped=True)
        assert actual is not None
        np.testing.assert_array_equal(rgb_pixels(actual),expected)
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(run,range(48)))


def test_audio_index_matches_full_scan_at_every_edit(tmp_path):
    data=np.random.default_rng(19).integers(-32768,32767,(RATE*2,2),dtype=np.int16)
    path=tmp_path/'audio.s16'; data.tofile(path)
    fps=Fraction(30000,1001)
    segments=tuple(Segment(None if i%7==0 else 'a',i%9,i%9+1,muted=i%11==0,reversed=i%3==0) for i in range(1000))
    pcm=TimelinePCM(segments,{'a':{'audio':str(path)}},fps)
    regions=[]
    for timeline_frame, segment in enumerate(segments):
        if segment.media and not segment.muted:
            a,b=sample_at(timeline_frame,fps),sample_at(timeline_frame+1,fps)
            sa,sb=sample_at(segment.start,fps),sample_at(segment.end,fps)
            indices=sa+np.arange(b-a,dtype=np.int64)*(sb-sa)//(b-a)
            regions.append((a,b,data[indices[::-1] if segment.reversed else indices]))
    try:
        for frame in range(-1,1002):
            start=max(0,sample_at(frame,fps)-5); count=min(4000,max(0,pcm.samples-start))
            expected=np.zeros((count,2),dtype='<i2')
            for a,b,samples in regions:
                l,r=max(a,start),min(b,start+count)
                if r>l:
                    expected[l-start:r-start]=samples[l-a:r-a]
            assert pcm.read(start,count)==expected.tobytes()
    finally: pcm.close()
