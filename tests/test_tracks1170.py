# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import json

import pytest

from drawing import DrawingKey
from model import Document, Segment, State, with_tracks


def media(key,frames=40):
    return dict(id=key,name=key,path=key+'.mp4',fps='24',frames=frames,width=128,height=72)


def two_tracks(first=40,second=60):
    doc=Document()
    doc.append_media([media('a',first)])
    first_id=doc.active_track_id
    doc.add_media_track()
    second_id=doc.active_track_id
    doc.append_media([media('b',second)])
    return doc,first_id,second_id


def test_independent_tracks_selection_delete_and_atomic_undo():
    doc,first,second=two_tracks()
    original=doc.state
    doc.select(10,20)
    assert doc.delete()
    assert [t.length for t in doc.state.tracks]==[40,50]
    assert doc.undo() and [t.length for t in doc.state.tracks]==[40,60]
    doc.select_track(first,extend=True)
    doc.select(10,20)
    assert doc.delete()
    assert [t.length for t in doc.state.tracks]==[30,50]
    assert doc.undo() and doc.state.tracks==original.tracks


def test_clipboards_preserve_both_tracks_and_audio():
    doc,first,second=two_tracks()
    doc.select_track(first,extend=True)
    doc.select(5,10)
    assert doc.copy()==5
    doc.state=replace(doc.state,position=15)
    assert doc.paste()
    assert [t.length for t in doc.state.tracks]==[45,65]
    for track,key in zip(doc.state.tracks,('a','b')):
        from model import locate
        assert locate(track.segments,15)==(key,5)
        assert locate(track.audio,15)==(key,5)


def test_paste_at_global_cursor_pads_only_destination():
    doc,first,second=two_tracks(10,40)
    doc.select_track(first)
    doc.select(0,5); doc.copy()
    doc.state=replace(doc.state,position=30)
    doc.paste()
    assert [t.length for t in doc.state.tracks]==[35,40]
    assert doc.state.segments[1]==Segment(None,0,20)
    assert doc.state.second_track.segments==(Segment('b',0,40),)


def test_track_order_removal_and_undo_preserve_identity():
    doc,first,second=two_tracks()
    assert doc.reorder_media_track(second,-1)
    assert doc.state.track_info.id==second and doc.active_track_id==second
    assert doc.state.segments==(Segment('b',0,60),)
    assert doc.remove_media_track(second)
    assert len(doc.state.tracks)==1 and doc.state.track_info.id==first
    assert doc.undo() and len(doc.state.tracks)==2
    assert not doc.add_media_track()


def test_effects_follow_selected_track():
    doc,first,second=two_tracks()
    doc.exposure(1.5)
    assert [t.exposure for t in doc.state.tracks]==[0,1.5]
    doc.set_track_effect('Flip',flip_h=True)
    assert [t.flip_h for t in doc.state.tracks]==[False,True]
    doc.select_track(first,extend=True); doc.exposure(-1)
    assert [t.exposure for t in doc.state.tracks]==[-1,-1]


def test_global_drawings_stay_when_only_one_track_is_edited():
    doc,first,second=two_tracks()
    doc.state=replace(doc.state,drawings=(DrawingKey(30,31,()),),frame_markers=(35,))
    doc.select(0,10); doc.delete()
    assert doc.state.drawings[0].start==30
    assert doc.state.frame_markers==(35,)
    doc.select_track(first,extend=True); doc.select(0,10); doc.delete()
    assert doc.state.drawings[0].start==20


def test_save_restores_both_tracks_order_and_reference(tmp_path):
    doc,first,second=two_tracks()
    doc.expand_track_audio(second,True)
    doc.reorder_media_track(second,-1)
    doc.review={'reference_track':first}
    path=tmp_path/'two.cadence'
    doc.save(path)
    restored=Document.load(path)
    assert restored.state==doc.state
    assert restored.review==doc.review
    assert set(restored.media)=={'a','b'}
    assert restored.format_version()==16
    data=json.loads(path.read_text())
    data['state']['second_track']['segments'][0]['end']=1000
    with pytest.raises(ValueError): Document.from_data(data)


def test_old_project_loads_one_track_with_collapsed_audio():
    doc=Document(); doc.append_media([media('old')])
    data=doc.to_data(); data['version']=15
    data['state'].pop('track_info'); data['state'].pop('second_track')
    restored=Document.from_data(data)
    assert len(restored.state.tracks)==1
    assert not restored.state.track_info.audio_expanded
    assert restored.state.segments==doc.state.segments


def test_cut_paste_short_track_preserves_range_alignment():
    doc,first,second=two_tracks(10,40)
    doc.select_track(first,extend=True)
    doc.select(5,20)
    assert doc.cut()==15
    assert [t.length for t in doc.state.tracks]==[5,25]
    doc.state=replace(doc.state,position=20)
    assert doc.paste()
    assert [t.length for t in doc.state.tracks]==[35,40]
    from model import locate
    assert locate(doc.state.tracks[0].segments,20)==('a',5)
    assert locate(doc.state.tracks[1].segments,20)==('b',5)
    assert locate(doc.state.tracks[0].segments,25)[0] is None


def test_canvas_aspect_survives_track_reordering():
    from composite_media import canvas_size
    doc,first,second=two_tracks()
    doc.media['b'].update(width=72,height=128)
    assert canvas_size(doc.state,doc.media)==(128,72)
    doc.reorder_media_track(second,-1)
    assert canvas_size(doc.state,doc.media)==(128,72)


def test_cadence_change_on_selected_or_both_tracks(monkeypatch):
    from fractions import Fraction
    import threading
    from track_cadence import plan_tracks,build_tracks
    doc,first,second=two_tracks()
    doc.state=replace(doc.state,drawings=(DrawingKey(30,31,()),),frame_markers=(35,))
    def prepare(path,fps,progress,cancel,quality,cadence):
        old=next(m for m in doc.media.values() if m['path']==path)
        return dict(old,id=old['id']+'-converted',frames=old['frames']*2,cadence=cadence)
    monkeypatch.setattr('media.prepare_media',prepare)
    def convert():
        return build_tracks(doc.state,doc.media,doc.fps,plan_tracks(doc,keys=set(doc.media)),Fraction(12),'speed',True,'native',lambda *a:None,threading.Event())[0]
    changed=convert()
    assert [t.length for t in changed.tracks]==[40,120]
    assert changed.drawings==doc.state.drawings and changed.frame_markers==(35,)
    doc.select_track(first,extend=True)
    changed=convert()
    assert [t.length for t in changed.tracks]==[80,120]
    assert changed.drawings[0].start==60 and changed.frame_markers==(70,)
