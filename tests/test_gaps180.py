# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from model import Document,State,Segment,empty_duration
from drawing import Mark,DrawingKey


def contents(track):
    return [(s.media,f if s.media else None) for s in track for f in range(s.start,s.end)]


@pytest.mark.parametrize('length',[4,10,16])
@pytest.mark.parametrize('track',['linked','video','audio'])
@pytest.mark.parametrize('leave_gap',[False,True])
def test_move_fills_gap_and_only_overflow_shifts_destination(length,track,leave_gap,tmp_path):
    video=(Segment(None,0,10),Segment('b',0,10),Segment('a',0,length))
    d=Document();d.media={k:dict(id=k,frames=100) for k in ('a','b')};d.state=State(video)
    old=d.state;assert d.move_range(20,20+length,0,track,leave_gap)
    selected=d.state.audio if track=='audio' else d.state.segments
    values=contents(selected);assert values[:length]==[('a',i) for i in range(length)]
    assert values.index(('b',0))==max(10,length)
    if track!='linked':
        other=contents(d.state.segments if track=='audio' else d.state.audio)
        assert other[:old.length]==contents(video) and all(key is None for key,_ in other[old.length:])
    assert sum(s.length for s in d.state.audio)==d.state.length
    d.save(tmp_path/'gap.cadence');assert Document.load(tmp_path/'gap.cadence').state==d.state
    moved=d.state;d.undo();assert d.state==old;d.redo();assert d.state==moved


def test_source_before_gap_keeps_source_gap_option():
    initial=(Segment('a',0,4),Segment('b',0,6),Segment(None,0,10),Segment('b',6,16))
    for leave_gap,first_dest,last_dest in [(True,12,20),(False,8,16)]:
        d=Document();d.state=State(initial);assert d.move_range(0,4,12,leave_gap=leave_gap)
        values=contents(d.state.segments)
        assert values[first_dest:first_dest+4]==[('a',i) for i in range(4)]
        assert values.index(('b',6))==last_dest


def test_linked_drop_does_not_overwrite_occupied_audio():
    video=(Segment(None,0,10),Segment('b',0,10),Segment('a',0,4))
    audio=(Segment(None,0,2),Segment('b',0,18),Segment('a',0,4))
    d=Document();d.state=State(video,audio_segments=audio);assert d.move_range(20,24,0,leave_gap=True)
    assert contents(d.state.audio)[4:22]==[('b',i) for i in range(18)]
    assert contents(d.state.segments).index(('b',0))==12


def test_audio_destination_snaps_to_audio_and_can_land_inside_audio_gap():
    d=Document();d.state=State((Segment('b',0,24),),audio_segments=(Segment(None,0,10),Segment('b',0,10),Segment('a',0,4)))
    assert d.snap_destination(5,'audio')==5 and d.snap_destination(5)==0
    assert d.move_range(20,24,5,'audio',True)
    assert contents(d.state.audio)[5:9]==[('a',i) for i in range(4)]
    assert contents(d.state.audio).index(('b',0))==10
    assert d.state.segments==(Segment('b',0,24),)


def test_filling_gap_preserves_destination_drawings_and_linked_keys(tmp_path):
    one=Mark(points=((.2,.5,1),));two=replace(one,color='#00ff00');three=replace(one,color='#0000ff')
    d=Document();d.media={k:dict(id=k,frames=100) for k in ('a','b')}
    d.state=State((Segment(None,0,10),Segment('b',0,10),Segment('a',0,4)),drawings=(DrawingKey(1,3,(one,)),DrawingKey(12,14,(two,)),DrawingKey(20,24,(three,))))
    assert d.move_range(20,24,0,leave_gap=True)
    assert next(k for k in d.state.drawings if k.start==12).marks==(two,)
    overlap=next(k for k in d.state.drawings if k.start==1)
    assert tuple(m.children[0] for m in overlap.marks)==(one,three)
    assert not any(k.start>=20 for k in d.state.drawings)
    d.save(tmp_path/'draw-gap.cadence');assert Document.load(tmp_path/'draw-gap.cadence').state==d.state


def test_adjacent_empty_segments_are_one_available_range():
    assert empty_duration((Segment(None,0,3),Segment(None,0,7),Segment('a',0,4)),2)==8
