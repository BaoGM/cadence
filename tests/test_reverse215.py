# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from clip_trim import trim_media
from composite_media import frame_layers
from model import Document, Segment, State, TimelinePCM, compact, locate, sample_at, slice_segments
from test_tracks1170 import two_tracks


def frames(segments):
    return [locate(segments,i) for i in range(sum(s.length for s in segments))]


def test_reverse_occurrence_undo_project_session_and_linked_audio(tmp_path):
    from session import read_session, write_snapshot
    doc,upper,lower = two_tracks()
    clip = Segment('a',4,16,rotation=90)
    doc.state = replace(doc.state,segments=(clip,clip),audio_segments=None,position=15,
                        frame_markers=(13,),selection=(12,24),selected_clips=((upper,12,24),))
    original = doc.state
    assert doc.reverse_clip(upper,'video',15)
    expected = replace(clip,reversed=True)
    assert doc.state.segments == (clip,expected)
    assert doc.state.audio == (clip,expected)
    assert doc.state.position == original.position and doc.state.selected_clips == original.selected_clips
    assert doc.state.frame_markers == original.frame_markers and doc.state.second_track == original.second_track
    assert [item[-1] for item in frame_layers(doc.state,doc.media,12)] == [15,12]
    assert [item[-1] for item in frame_layers(doc.state,doc.media,23)] == [4,23]
    assert len(doc.undo_stack) >= 1 and doc.undo() and doc.state == original
    assert doc.redo()
    current = doc.state
    path = tmp_path/'project.cadence'
    doc.save(path)
    assert doc.format_version() == 21 and Document.load(path).state.segments == current.segments
    snapshot = tmp_path/'session.json'
    write_snapshot(snapshot,(current,doc.media,doc.fps,doc.review,None,True),{})
    assert read_session(snapshot)[1].state.tracks == current.tracks
    assert doc.reverse_clip(upper,'video',15) and doc.state.tracks == original.tracks
    assert doc.format_version() == 16 and 'reversed' not in doc.to_data()['state']['segments'][0]
    assert not doc.reverse_clip(lower,'audio',1000)
    assert doc.reverse_clip(upper,'audio',1,linked=False)
    assert doc.state.audio[0].reversed and not doc.state.segments[0].reversed


def test_reverse_splits_and_copies_and_trims_in_screen_order():
    doc = Document()
    clip = Segment('m',4,14,reversed=True)
    doc.media = {'m':dict(frames=20)}
    doc.state = State((Segment(None,0,2),clip,Segment(None,0,3)))
    start = frames(doc.state.segments)
    doc.select(4,9)
    assert doc.copy() == 5 and frames(doc.clipboard) == start[4:9]
    assert doc.split_at(8)
    assert frames(doc.state.segments) == start
    assert doc.undo()
    assert trim_media(doc,doc.active_track_id,'video',1,True,3,True)
    assert trim_media(doc,doc.active_track_id,'video',1,False,-2,True)
    assert doc.state.segments[1] == replace(clip,start=6,end=11)
    assert trim_media(doc,doc.active_track_id,'video',1,True,-3,True)
    assert trim_media(doc,doc.active_track_id,'video',1,False,2,True)
    assert doc.state.segments[1] == clip and frames(doc.state.segments) == start
    assert compact(slice_segments((clip,),0,3)+slice_segments((clip,),3,10)) == (clip,)
    forward = replace(clip,start=14,end=16,reversed=False)
    assert compact((clip,forward)) == (clip,forward)


def test_reverse_audio_keeps_channels_and_reads_across_fractional_boundaries(tmp_path):
    fps = Fraction(30000,1001)
    samples = (np.arange(sample_at(18,fps)) % 8191).astype('<i2')
    stereo = np.column_stack((samples,-samples))
    path = tmp_path/'stereo.s16'
    path.write_bytes(stereo.tobytes())
    data = {'m':dict(audio=str(path))}
    leading = Segment(None,0,3)
    clip = Segment('m',2,13)
    forward = TimelinePCM((leading,clip),data,fps)
    backward = TimelinePCM((leading,replace(clip,reversed=True)),data,fps)
    try:
        start = sample_at(3,fps)
        original = np.frombuffer(forward.read(start,forward.samples-start),'<i2').reshape(-1,2)
        result = b''.join(backward.read(i,min(293,backward.samples-i)) for i in range(start,backward.samples,293))
        assert result == original[::-1].tobytes()
    finally:
        forward.close()
        backward.close()


@pytest.mark.parametrize('disk',[True,False])
def test_lossless_reverse_export_both_paths_and_actual_mp4(tmp_path,monkeypatch,disk):
    import reverse_export
    from media import export_video, prepare_media
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    monkeypatch.setattr(reverse_export,'MEMORY_LIMIT',0 if disk else 2**60)
    info = prepare_media(Path(__file__).resolve().parents[1]/'assets/Demonstration.mp4')
    media = {info['id']:info}
    clip = Segment(info['id'],24,31)
    state = State((replace(clip,reversed=True),clip))
    new,outputs,keys = reverse_export.prepare_reversed_video(state,media,[clip.media],Fraction(24),tmp_path,lambda *_:None,None)
    def decode(path):
        with av.open(str(path)) as movie:
            return [f.to_ndarray(format='rgb24') for f in movie.decode(video=0)]
    with av.open(info['path']) as movie:
        expected = [f.to_ndarray(format='rgb24') for i,f in zip(range(31),movie.decode(video=0)) if i>=24]
    reversed_pixels = decode(outputs[keys[0]]['path'])
    assert len(keys) == 2 and new.segments[1] == clip
    assert len(reversed_pixels) == 7
    for actual,source in zip(reversed_pixels,reversed(expected)):
        assert np.array_equal(actual,source)
    export = tmp_path/'reversed.mp4'
    export_video(state,media,Fraction(24),export)
    result = decode(export)
    assert len(result) == 14
    for actual,source in zip(result,list(reversed(expected))+expected):
        assert np.abs(actual.astype(int)-source).mean() < 4
    if not disk:
        from studio_export import sequence_folder
        front=replace(clip,placement=(0.,0.,.5,.5),reversed=True)
        alpha=tmp_path/'overlay.png'
        export_video(State((front,)),media,Fraction(24),alpha,profile='png')
        files=sorted(sequence_folder(alpha).glob('*.png'))
        assert len(files)==len(expected)
        for image,source in zip(files,reversed(expected)):
            with av.open(str(image)) as movie:
                rgba=next(movie.decode(video=0)).to_ndarray(format='rgba')
            assert rgba[50,100,3]==255 and rgba[-2,-2,3]==0
            assert np.abs(rgba[2:260,2:470:2,:3].astype(int)-source[4:520:2,4:940:4]).mean()<10
