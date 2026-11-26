# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest

from model import Document, Segment, compact
from time_warp import mapping, normalized, points, target, video_sample
from time_warp_ui import reverse_axis


CURVE=((5,5,'blend'),(9,7,'held'),(12,7,'held'),(17,5,'held'))


def test_curve_samples_hold_reverse_and_return_to_original_outside():
    assert mapping(CURVE,6)==(5,.5,'blend')
    assert mapping(CURVE,10)==(7,0.,'held')
    base,frac,mode=mapping(CURVE,13)
    assert (base,mode)==(6,'held') and frac==pytest.approx(.6)
    assert mapping(CURVE,17)==(5,0.,'held')
    assert mapping(CURVE,18)==(18,0.,'held')
    assert not normalized(((3,3,'rife'),(16,16,'held')))
    assert reverse_axis(reverse_axis(CURVE,22),22)==CURVE


def test_split_trim_and_reverse_keep_the_curve_with_the_occurrence(tmp_path):
    doc=Document()
    doc.media={'cube':dict(id='cube', frames=32, has_video=True, path='cube.mov')}
    one=Segment('cube',5,18,warp=CURVE)
    two=Segment('cube',18,23)
    doc.state=replace(doc.state,segments=(one,two),audio_segments=(replace(one,warp=()),two))
    assert compact((one,two))==(one,two)
    assert target(doc)[-1]==one
    assert doc.split_at(4)
    assert [clip.warp for clip in doc.state.segments]==[CURVE,CURVE,()]
    assert not any(clip.warp for clip in doc.state.audio)
    restored=one.sliced(-4,one.length+3)
    assert restored.start==1 and restored.end==21
    info=doc.media['cube']
    assert video_sample(info,restored,4)==(info,4)
    assert video_sample(info,restored,19)==(info,19)
    path=tmp_path/'cube.cadence';doc.save(path)
    assert Document.load(path).state==doc.state and doc.format_version()==23
    assert doc.undo() and doc.state.segments==(one,two)


@pytest.mark.parametrize('invalid',[
    ((5,2,'rife'),(5,6,'held')), ((0,-1,'held'),(2,2,'held')),
    ((0,1,'command'),(2,2,'held')), ((True,1,'blend'),(3,3,'held')),
])
def test_invalid_curves_are_rejected(invalid):
    with pytest.raises(ValueError): points(invalid)


@pytest.mark.parametrize('second',[False,True])
def test_session_snapshot_repairs_217_version_and_validates_curve(tmp_path,second):
    import json
    from session import read_session, write_snapshot
    doc=Document()
    doc.media={'cube':dict(id='cube', frames=32, has_video=True, path='cube.mov')}
    clip=Segment('cube',5,18,warp=CURVE)
    if second:
        doc.add_media_track()
        doc.state=replace(doc.state,second_track=replace(doc.state.second_track,segments=(clip,)))
    else:
        doc.state=replace(doc.state,segments=(clip,))
    path=tmp_path/'session.json'
    write_snapshot(path,(doc.state,doc.media,doc.fps,doc.review,None,True),{})
    payload,restored=read_session(path)
    assert payload['document']['version']==23 and restored.state==doc.state
    for version in range(11,23):
        payload['document']['version']=version
        path.write_text(json.dumps(payload),encoding='utf-8')
        assert read_session(path)[1].state==doc.state
        with pytest.raises(ValueError,match='Courbe temporelle'):
            Document.from_data(payload['document'])
    state=payload['document']['state']
    track=state['second_track'] if second else state
    track['segments'][0]['warp'][0][1]=32
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError,match='Courbe temporelle'):
        read_session(path)
